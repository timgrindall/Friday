# Version 0.60

"""
Friday - Voice and Text Assistant
Named after the character Friday from Robinson Crusoe

Runs as a single program - no separate server/client needed.
Just: python friday.py

Dev mode (verbose logging + text input):
    python friday.py -dev
"""

# ── TODO ─────────────────────────────────────────────────────────
# [x] Streaming responses in dev/text mode with mid-stream cutoff
# [ ] Piper TTS for higher quality local voice fallback
# [x] Research Mistral 4 Small — ruled out, exceeds available RAM on low-end hardware
# [ ] Update README to reflect single-file architecture and new config vars
# ─────────────────────────────────────────────────────────────────

import os
import sys
import json
import wave
import tempfile
import threading
import io
import warnings
import logging
from datetime import datetime
from io import BytesIO

# Suppress noisy startup messages
warnings.filterwarnings("ignore")
logging.getLogger("werkzeug").setLevel(logging.ERROR)
logging.getLogger("urllib3").setLevel(logging.ERROR)

import numpy as np
import sounddevice as sd
import whisper
import requests
from pynput import keyboard
from dotenv import load_dotenv
from flask import Flask, request, send_file, jsonify, stream_with_context, Response

load_dotenv()

# ── Colors ────────────────────────────────────────────────────────

def _enable_windows_ansi():
    """Enable ANSI escape codes on Windows console."""
    if sys.platform == 'win32':
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)

_enable_windows_ansi()

class C:
    GREEN   = "\033[92m"
    CYAN    = "\033[96m"
    YELLOW  = "\033[93m"
    RESET   = "\033[0m"

# ── Dev mode ─────────────────────────────────────────────────────

DEV_MODE = "-dev" in sys.argv

# ── Configuration ────────────────────────────────────────────────

OLLAMA_MODEL     = "mistral"
OLLAMA_URL       = "http://localhost:11434"
MEMORY_FILE      = "friday_memory.json"
TOKEN_CAP        = 1000
SERVER_PORT      = 5001
SERVER_URL       = f"http://localhost:{SERVER_PORT}"
TEXT_HISTORY_TURNS  = 2     # Number of previous exchanges to include in text mode (0 = disabled)
VOICE_HISTORY_TURNS = 1     # Number of previous exchanges to include in voice mode (0 = disabled)
MAX_RESPONSE_TOKENS      = 160   # Max tokens for voice responses (Ollama's num_predict)
MAX_TEXT_RESPONSE_TOKENS = 800   # Max tokens for text/streaming responses

SERPAPI_KEY        = os.getenv("SERPAPI_KEY", "")
ELEVENLABS_KEY     = os.getenv("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE   = os.getenv("ELEVENLABS_VOICE_ID", "JBFqnCBsd6RMkjVDRZzb")

TEMP_DIR     = tempfile.gettempdir()
AUDIO_INPUT  = os.path.join(TEMP_DIR, "friday_input.wav")
AUDIO_OUTPUT = os.path.join(TEMP_DIR, "friday_output.wav")

SYSTEM_PROMPT_VOICE = (
    "You are Friday, a helpful voice assistant. "
    "Give clear, natural responses of 1-2 sentences suitable for speaking aloud. "
    "Be conversational and informative. "
    "If you are not sure about something, say so rather than guessing."
)

SYSTEM_PROMPT_TEXT = (
    "You are Friday, a helpful assistant. "
    "Give well-structured, clear, and informative responses of 3-4 sentences. "
    "If you are not sure about something, say so rather than guessing."
)

# ── Flask App ────────────────────────────────────────────────────

app = Flask(__name__)


# ── Memory ───────────────────────────────────────────────────────

def load_history():
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE) as f:
                history = json.load(f)
            if DEV_MODE:
                print(f"[MEMORY] Loaded {len(history)} messages")
            return history
        except Exception as e:
            print(f"[MEMORY] Failed to load: {e}")
    return []


def save_history(history):
    try:
        with open(MEMORY_FILE, "w") as f:
            json.dump(history, f, indent=2)
    except Exception as e:
        print(f"[MEMORY] Failed to save: {e}")


def estimate_tokens(history):
    return sum(len(m["content"]) for m in history) // 4


def trim_for_context(history):
    """Return a trimmed copy of history that fits within TOKEN_CAP.
    The original full history is never modified."""
    context = list(history)
    while estimate_tokens(context) > TOKEN_CAP and len(context) > 2:
        context.pop(0)
        if context and context[0]["role"] == "assistant":
            context.pop(0)
    if DEV_MODE:
        print(f"[MEMORY] {len(history)} messages in archive, {len(context)} sent to Ollama (~{estimate_tokens(context)} tokens)")
    return context


conversation_history = load_history()


# ── Core Pipeline ─────────────────────────────────────────────────

print("[FRIDAY] Loading Whisper...") if DEV_MODE else None
whisper_model = whisper.load_model("base")
print("[FRIDAY] Whisper ready") if DEV_MODE else None


def transcribe_audio(audio_bytes):
    try:
        with open(AUDIO_INPUT, "wb") as f:
            f.write(audio_bytes)
        result = whisper_model.transcribe(AUDIO_INPUT)
        text = result["text"].strip()
        if DEV_MODE:
            print(f"  Heard: {text}")
        return text
    except Exception as e:
        print(f"[ERROR] Transcription failed: {e}")
        return None


def is_online():
    try:
        requests.get("https://1.1.1.1", timeout=3)
        return True
    except Exception:
        return False


def web_search(query):
    if not is_online():
        if DEV_MODE:
            print("[SEARCH] Offline, skipping")
        return []
    try:
        params = {"q": query, "api_key": SERPAPI_KEY, "num": 5, "engine": "google"}
        response = requests.get("https://serpapi.com/search", params=params, timeout=5)
        results = response.json()
        search_results = []
        if "organic_results" in results:
            for r in results["organic_results"][:3]:
                search_results.append({"title": r.get("title", ""), "snippet": r.get("snippet", "")})
        if DEV_MODE:
            print(f"[SEARCH] {len(search_results)} results")
        return search_results
    except Exception as e:
        if DEV_MODE:
            print(f"[ERROR] Search failed: {e}")
        return []


SEARCH_TRIGGERS = (
    "today", "current", "latest", "now", "weather", "news",
    "price", "stock", "score", "who won", "what is happening",
    "recent", "right now", "this week", "this year", "tomorrow",
    "forecast", "standings", "results", "update", "happening"
)

def get_search_query(query, text_mode=False):
    """
    Returns an optimised search query string if a web search is needed, or None if not.
    Voice mode: keyword match only (fast).
    Text mode: asks Mistral to decide AND generate the query in one call.
    """
    q = query.lower()

    # Fast path: keyword match — use raw query for voice, let Mistral refine for text
    if any(trigger in q for trigger in SEARCH_TRIGGERS):
        if not text_mode:
            return query  # voice: just use the raw query
        # Fall through to Mistral to get a better query

    # Text mode only: ask Mistral to decide and generate a search query
    if SERPAPI_KEY and text_mode:
        try:
            response = requests.post(
                f"{OLLAMA_URL}/api/chat",
                json={
                    "model": OLLAMA_MODEL,
                    "messages": [
                        {
                            "role": "user",
                            "content": (
                                f'Does answering this question require current information from after 2023? '
                                f'If YES, reply with only a concise web search query (no explanation, no quotes). '
                                f'If NO, reply with only the word NO.\n\nQuestion: {query}'
                            )
                        }
                    ],
                    "stream": False,
                    "options": {"num_predict": 20}
                },
                timeout=20
            )
            if response.status_code == 200:
                answer = response.json()["message"]["content"].strip().strip("\"'")
                if DEV_MODE:
                    print(f"  Search query: {answer}")
                if answer.upper() == "NO" or answer.upper().startswith("NO "):
                    return None
                return answer  # Mistral's optimised search query
        except Exception:
            if DEV_MODE:
                status("Web search skipped (Ollama busy)")
            # Fall back to raw query on failure
            return query if any(trigger in q for trigger in SEARCH_TRIGGERS) else None

    return None


META_PATTERNS = (
    "last thing i asked",
    "last thing i said",
    "what did i ask",
    "what was my last question",
    "what did i last ask",
    "previous question",
    "last question",
)

def check_meta_question(query):
    """If the user is asking about their own previous message, answer directly from history."""
    q = query.lower()
    if any(p in q for p in META_PATTERNS):
        # Find the most recent user message before this one
        user_messages = [m["content"] for m in conversation_history if m["role"] == "user"]
        if len(user_messages) >= 2:
            return f"Your last question was: \"{user_messages[-2]}\""
        else:
            return "I don't have any previous questions in memory."
    return None


def generate_response(user_query, search_results, system_prompt, use_history=True, max_turns=None):
    global conversation_history

    # Handle meta-questions about conversation history directly
    meta_answer = check_meta_question(user_query)
    if meta_answer:
        conversation_history.append({"role": "user", "content": user_query})
        conversation_history.append({"role": "assistant", "content": meta_answer})
        save_history(conversation_history)
        return meta_answer

    content = user_query
    if search_results:
        results_text = "\n".join([f"- {r['title']}: {r['snippet']}" for r in search_results])
        content = f"{user_query}\n\nSearch results:\n{results_text}"

    conversation_history.append({"role": "user", "content": content})

    if not use_history:
        context = [{"role": "user", "content": content}]
    elif max_turns is not None:
        # Take the last N complete exchanges (2 messages each) plus the current message
        tail = conversation_history[-(max_turns * 2 + 1):]
        context = tail
    else:
        context = trim_for_context(conversation_history)

    if DEV_MODE:
        print(f"  {len(context)} message(s) sent to Ollama")

    try:
        response = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": OLLAMA_MODEL,
                "messages": [{"role": "system", "content": system_prompt}] + context,
                "stream": False,
                "options": {"num_predict": MAX_RESPONSE_TOKENS},
            },
            timeout=300
        )

        if response.status_code == 200:
            answer = response.json()["message"]["content"].strip()
            if DEV_MODE:
                print(f"  Response: {answer}")
            conversation_history.append({"role": "assistant", "content": answer})
            save_history(conversation_history)
            return answer
        else:
            if DEV_MODE:
                print(f"[ERROR] Ollama error: {response.status_code} — {response.text}")
            return "I'm having trouble processing that."

    except requests.exceptions.ConnectionError:
        return "Ollama is not running. Please start it with: ollama serve"
    except Exception as e:
        if DEV_MODE:
            print(f"[ERROR] Response failed: {e}")
        return "I'm sorry, I had trouble processing that."


def text_to_speech(text):
    return tts_elevenlabs(text) if ELEVENLABS_KEY and is_online() else tts_local(text)


def tts_elevenlabs(text):
    try:
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE}?output_format=pcm_16000"
        headers = {"xi-api-key": ELEVENLABS_KEY, "Content-Type": "application/json"}
        payload = {
            "text": text,
            "model_id": "eleven_monolingual_v1",
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}
        }
        response = requests.post(url, headers=headers, json=payload, timeout=30)

        if response.status_code == 200:
            wav_buffer = io.BytesIO()
            with wave.open(wav_buffer, 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16000)
                wf.writeframes(response.content)
                # Pad with 300ms of silence to prevent last syllable clipping
                wf.writeframes(bytes(int(16000 * 0.3) * 2))
            audio_bytes = wav_buffer.getvalue()
            if DEV_MODE:
                print(f"[TTS] ElevenLabs ({len(audio_bytes)} bytes)")
            return audio_bytes
        else:
            if DEV_MODE:
                print(f"[TTS] ElevenLabs error {response.status_code}, falling back")
            return tts_local(text)

    except Exception as e:
        if DEV_MODE:
            print(f"[ERROR] ElevenLabs failed: {e}, falling back")
        return tts_local(text)


def tts_local(text):
    try:
        import pyttsx3
        engine = pyttsx3.init()
        engine.setProperty("rate", 150)
        engine.setProperty("volume", 0.9)
        engine.save_to_file(text, AUDIO_OUTPUT)
        engine.runAndWait()
        with open(AUDIO_OUTPUT, "rb") as f:
            audio_bytes = f.read()
        if DEV_MODE:
            print(f"[TTS] Local ({len(audio_bytes)} bytes)")
        return audio_bytes
    except Exception as e:
        if DEV_MODE:
            print(f"[ERROR] Local TTS failed: {e}")
        return None


# ── Flask Routes ──────────────────────────────────────────────────

def status(message):
    """Print a status message to the terminal for both voice and text modes."""
    print(f"\n  {C.CYAN}⟳ {message}{C.RESET}", flush=True)


@app.route("/process", methods=["POST"])
def process_voice():
    try:
        if DEV_MODE:
            print("\n" + "="*50)
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Voice command...")
        if "audio" not in request.files:
            return {"error": "No audio"}, 400
        audio_bytes = request.files["audio"].read()
        user_query = transcribe_audio(audio_bytes)
        if not user_query:
            return {"error": "Transcription failed"}, 500
        search_query = get_search_query(user_query, text_mode=False)
        if search_query:
            status("Searching the web...")
            search_results = web_search(search_query)
        else:
            search_results = []
        status("Thinking...")
        response_text = generate_response(user_query, search_results, SYSTEM_PROMPT_VOICE, use_history=True, max_turns=VOICE_HISTORY_TURNS)
        response_audio = text_to_speech(response_text)
        if response_audio:
            return send_file(BytesIO(response_audio), mimetype="audio/wav")
        return {"error": "TTS failed"}, 500
    except Exception as e:
        if DEV_MODE:
            print(f"[ERROR] {e}")
        return {"error": str(e)}, 500


@app.route("/process_text", methods=["POST"])
def process_text():
    try:
        if DEV_MODE:
            print("\n" + "="*50)
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Text query...")
        data = request.get_json()
        if not data or "text" not in data:
            return {"error": "No text"}, 400
        user_query = data["text"].strip()
        if not user_query:
            return {"error": "Empty query"}, 400
        search_query = get_search_query(user_query, text_mode=True)
        search_results = web_search(search_query) if search_query else []
        response_text = generate_response(user_query, search_results, SYSTEM_PROMPT_TEXT, use_history=TEXT_HISTORY_TURNS > 0, max_turns=TEXT_HISTORY_TURNS if TEXT_HISTORY_TURNS > 0 else None)
        return jsonify({"response": response_text})
    except Exception as e:
        if DEV_MODE:
            print(f"[ERROR] {e}")
        return {"error": str(e)}, 500


@app.route("/process_text_stream", methods=["POST"])
def process_text_stream():
    """Streaming text route — tokens arrive as they're generated."""
    try:
        data = request.get_json()
        if not data or "text" not in data:
            return {"error": "No text"}, 400
        user_query = data["text"].strip()
        if not user_query:
            return {"error": "Empty query"}, 400

        if DEV_MODE:
            print("\n" + "="*50)
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Text query (stream)...")

        search_query = get_search_query(user_query, text_mode=True)
        if search_query:
            status("Searching the web...")
            search_results = web_search(search_query)
        else:
            search_results = []
        status("Thinking...")

        # Build context same as generate_response
        content = user_query
        if search_results:
            results_text = "\n".join([f"- {r['title']}: {r['snippet']}" for r in search_results])
            content = f"{user_query}\n\nSearch results:\n{results_text}"

        conversation_history.append({"role": "user", "content": content})
        if TEXT_HISTORY_TURNS > 0:
            context = conversation_history[-(TEXT_HISTORY_TURNS * 2 + 1):]
        else:
            context = [{"role": "user", "content": content}]

        if DEV_MODE:
            print(f"  {len(context)} message(s) sent to Ollama")

        def generate():
            full_response = []
            try:
                with requests.post(
                    f"{OLLAMA_URL}/api/chat",
                    json={
                        "model": OLLAMA_MODEL,
                        "messages": [{"role": "system", "content": SYSTEM_PROMPT_TEXT}] + context,
                        "stream": True,
                        "options": {"num_predict": MAX_TEXT_RESPONSE_TOKENS},
                    },
                    stream=True,
                    timeout=300
                ) as r:
                    for line in r.iter_lines():
                        if line:
                            chunk = json.loads(line)
                            token = chunk.get("message", {}).get("content", "")
                            if token:
                                full_response.append(token)
                                yield token
                            if chunk.get("done"):
                                break
            except Exception as e:
                if DEV_MODE:
                    print(f"[ERROR] Stream failed: {e}")
            finally:
                # Save completed response to history
                answer = "".join(full_response)
                if answer:
                    conversation_history.append({"role": "assistant", "content": answer})
                    save_history(conversation_history)

        return Response(stream_with_context(generate()), mimetype="text/plain")

    except Exception as e:
        if DEV_MODE:
            print(f"[ERROR] {e}")
        return {"error": str(e)}, 500



    return jsonify({"status": "online", "messages": len(conversation_history)})


@app.route("/memory/clear", methods=["POST"])
def clear_memory():
    global conversation_history
    conversation_history = []
    save_history(conversation_history)
    if DEV_MODE:
        print("[MEMORY] Cleared")
    return jsonify({"status": "cleared"})


# ── Client Interface ──────────────────────────────────────────────

class Friday:
    def __init__(self):
        self.recording = False
        self.audio_frames = []
        self.active = False
        self.running = False
        self.playback_done = threading.Event()

        self.CHANNELS = 1
        self.RATE = 16000
        self.INPUT_FILE = AUDIO_INPUT
        self.OUTPUT_FILE = AUDIO_OUTPUT

    def _print_banner(self):
        print(f"\n{C.GREEN}" + "="*50)
        print("FRIDAY - STANDBY")
        print("="*50 + f"{C.RESET}")
        print(f"Model:   {OLLAMA_MODEL}")
        print(f"Memory:  {MEMORY_FILE}")
        print(f"TTS:     {'ElevenLabs' if ELEVENLABS_KEY else 'pyttsx3 (local)'}")
        print(f"Search:  {'SerpAPI' if SERPAPI_KEY else 'Disabled'}")
        if DEV_MODE:
            print(f"Mode:    DEV (text input enabled)")
        print("\nPress Enter to activate.\n")

    def _print_active(self):
        print(f"\n{C.GREEN}" + "="*50)
        print("FRIDAY - ACTIVE")
        print("="*50 + f"{C.RESET}")
        voice_hint = "hold SPACE to record, release to send" if sys.platform == 'win32' else "Enter to start, Enter to send"
        print(f"\n  Enter      - Voice ({voice_hint})")
        if DEV_MODE:
            print("  T + Enter  - Text query")
        print("  quit       - Exit\n")

    def _go_standby(self):
        self.active = False
        print("\n[Standby] Press Enter to activate.\n")

    # ── Voice ─────────────────────────────────────────────────────

    def start_recording(self):
        if self.recording:
            return
        self.recording = True
        self.audio_frames = []
        print("[Mic] Recording...")

        def callback(indata, frames, time, status):
            if self.recording:
                self.audio_frames.append(indata.copy())

        self.stream = sd.InputStream(
            samplerate=self.RATE, channels=self.CHANNELS,
            dtype='int16', callback=callback
        )
        self.stream.start()

    def stop_recording(self):
        if not self.recording:
            return None
        self.recording = False
        try:
            self.stream.stop()
            self.stream.close()
            if not self.audio_frames:
                return None
            audio_data = np.concatenate(self.audio_frames, axis=0)
            # Prepend 500ms of silence so Whisper doesn't mishear the first words
            silence = np.zeros((int(self.RATE * 0.5), self.CHANNELS), dtype=np.int16)
            audio_data = np.concatenate([silence, audio_data])
            with wave.open(self.INPUT_FILE, 'wb') as wf:
                wf.setnchannels(self.CHANNELS)
                wf.setsampwidth(2)
                wf.setframerate(self.RATE)
                wf.writeframes(audio_data.tobytes())
            if DEV_MODE:
                print("[OK] Recording saved")
            return self.INPUT_FILE
        except Exception as e:
            print(f"[ERROR] Recording failed: {e}")
            return None

    def _suppress_echo(self):
        """Disable terminal echo."""
        if sys.platform == 'win32':
            import ctypes
            import ctypes.wintypes
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.GetStdHandle(-10)  # STD_INPUT_HANDLE
            mode = ctypes.wintypes.DWORD()
            kernel32.GetConsoleMode(handle, ctypes.byref(mode))
            self._old_console_mode = mode.value
            # Clear ENABLE_ECHO_INPUT (0x0004) and ENABLE_LINE_INPUT (0x0002)
            kernel32.SetConsoleMode(handle, mode.value & ~0x0006)
        else:
            try:
                import termios, tty
                self._old_termios = termios.tcgetattr(sys.stdin)
                tty.setcbreak(sys.stdin.fileno())
            except Exception:
                self._old_termios = None

    def _restore_echo(self):
        """Restore terminal echo."""
        if sys.platform == 'win32':
            if hasattr(self, '_old_console_mode'):
                import ctypes
                kernel32 = ctypes.windll.kernel32
                handle = kernel32.GetStdHandle(-10)
                kernel32.SetConsoleMode(handle, self._old_console_mode)
        else:
            try:
                import termios
                if hasattr(self, '_old_termios') and self._old_termios:
                    termios.tcsetattr(sys.stdin, termios.TCSADRAIN, self._old_termios)
            except Exception:
                pass

    def _cancel_recording(self):
        self.recording = False
        if hasattr(self, 'stream'):
            try:
                self.stream.stop()
                self.stream.close()
            except:
                pass

    def do_voice_session(self):
        if sys.platform == 'win32':
            self._voice_pynput()
        else:
            self._voice_enter()

    def _voice_pynput(self):
        import time
        import msvcrt
        while msvcrt.kbhit():
            msvcrt.getwch()
        time.sleep(0.1)
        self._suppress_echo()
        print("Hold SPACE to record, release to send. ESC to cancel.\n")
        space_released = threading.Event()
        cancelled = threading.Event()

        def on_press(key):
            if key == keyboard.Key.space:
                if not self.recording:
                    self.start_recording()
            elif key == keyboard.Key.esc:
                cancelled.set()
                space_released.set()
                return False

        def on_release(key):
            if key == keyboard.Key.space:
                space_released.set()
                return False

        with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
            space_released.wait()
            listener.stop()

        self._restore_echo()

        if cancelled.is_set():
            self._cancel_recording()
            print("Cancelled.\n")
            return

        wav_file = self.stop_recording()
        if wav_file:
            threading.Thread(target=self._send_voice, args=(wav_file,), daemon=True).start()

    def _drain_stdin(self):
        """Flush any buffered input (e.g. from holding Enter) before the next prompt."""
        import termios
        termios.tcflush(sys.stdin, termios.TCIFLUSH)

    def _voice_enter(self):
        print("Press Enter to start recording.\n")
        input()
        self._drain_stdin()
        self.start_recording()
        print("Press Enter to send.\n")
        input()
        self._drain_stdin()
        wav_file = self.stop_recording()
        if wav_file:
            threading.Thread(target=self._send_voice, args=(wav_file,), daemon=True).start()

    def _send_voice(self, wav_file):
        try:
            import time
            print("\n[>>] Sending to Friday...")
            t_start = time.time()
            with open(wav_file, 'rb') as f:
                response = requests.post(f"{SERVER_URL}/process", files={'audio': f}, timeout=300)
            if response.status_code == 200:
                elapsed = time.time() - t_start
                print(f"  {C.GREEN}✓ Response ready ({elapsed:.1f}s){C.RESET}")
                self._play_audio(response.content, t_start)
        except Exception as e:
            print(f"  {C.YELLOW}[!!] Error: {e}{C.RESET}")

    def _play_audio(self, audio_bytes, t_start=None):
        import time
        if not audio_bytes:
            self.playback_done.set()
            return
        try:
            with open(self.OUTPUT_FILE, 'wb') as f:
                f.write(audio_bytes)
            if DEV_MODE:
                print("[>>] Playing response...\n")
            with wave.open(self.OUTPUT_FILE, 'rb') as wf:
                framerate = wf.getframerate()
                audio_data = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)
                silence = np.zeros(int(framerate * 0.3), dtype=np.int16)
                audio_data = np.concatenate([silence, audio_data])
                sd.play(audio_data, samplerate=framerate)
                sd.wait()
            if t_start:
                print(f"  {C.GREEN}✓ Playback complete ({time.time() - t_start:.1f}s total){C.RESET}\n")
        except Exception as e:
            print(f"  {C.YELLOW}[ERROR] Playback failed: {e}{C.RESET}\n")
        finally:
            self.playback_done.set()

    # ── Text (dev mode only) ──────────────────────────────────────

    def do_text_session(self):
        print("Text mode. Blank line to exit.\n")
        while True:
            print("> ", end="", flush=True)
            try:
                text = input().strip()
            except EOFError:
                return
            if not text:
                return
            try:
                self._stream_text_response(text)
            except Exception as e:
                print(f"[!!] Error: {e}")

    def _stream_text_response(self, text):
        """Stream response tokens to terminal. Press Enter to cut off mid-stream."""
        import time
        stop_event = threading.Event()

        def watch_for_enter():
            input()
            stop_event.set()

        watcher = threading.Thread(target=watch_for_enter, daemon=True)
        watcher.start()

        t_start = time.time()
        try:
            with requests.post(
                f"{SERVER_URL}/process_text_stream",
                json={"text": text},
                stream=True,
                timeout=300
            ) as response:
                if response.status_code != 200:
                    print(f"[!!] Server error: {response.status_code}")
                    return
                print("\nFriday: ", end="", flush=True)
                for chunk in response.iter_content(chunk_size=None):
                    if stop_event.is_set():
                        response.close()
                        elapsed = time.time() - t_start
                        print(f" {C.YELLOW}[stopped at {elapsed:.1f}s]{C.RESET}")
                        break
                    if chunk:
                        print(chunk.decode("utf-8"), end="", flush=True)
                else:
                    elapsed = time.time() - t_start
                    print(f"\n  {C.GREEN}✓ Done ({elapsed:.1f}s){C.RESET}\n")
        except requests.exceptions.ChunkedEncodingError:
            print(f"\n  {C.YELLOW}[stopped]{C.RESET}")
        except Exception as e:
            print(f"\n  {C.YELLOW}[!!] Stream error: {e}{C.RESET}")

    # ── Main Loop ─────────────────────────────────────────────────

    def _voice_loop(self):
        """Continuous voice loop — runs in background thread for both normal and dev mode."""
        while self.running:
            self.playback_done.clear()
            self.do_voice_session()
            self.playback_done.wait()

    def _start_voice_loop(self):
        """Start the voice loop in a background thread and watch stdin for commands."""
        self.running = True

        if not DEV_MODE:
            # Normal mode: start continuous voice loop immediately
            voice_thread = threading.Thread(target=self._voice_loop, daemon=True)
            voice_thread.start()
        else:
            voice_thread = None

        while self.running:
            cmd = input().strip().lower()
            if cmd == "quit":
                self.running = False
                print("Goodbye.")
                sys.exit(0)
            elif cmd in ("v", "") and DEV_MODE:
                # Dev mode: trigger a single voice session on demand
                self.do_voice_session()
            elif cmd == "t" and DEV_MODE:
                # Pause voice loop if running, do text session, then restart
                if voice_thread and voice_thread.is_alive():
                    self.running = False
                    voice_thread.join(timeout=2)
                self.do_text_session()
                self.running = True

    def run(self):
        self._print_banner()
        # Flush any buffered keypresses before listening
        if sys.platform == 'win32':
            import msvcrt
            while msvcrt.kbhit():
                msvcrt.getwch()
        while True:
            cmd = input().strip().lower()

            if cmd == "quit":
                print("Goodbye.")
                sys.exit(0)

            if not self.active:
                if cmd == "":
                    self.active = True
                    if DEV_MODE:
                        self._print_active()
                    self._start_voice_loop()
                continue


# ── Entry Point ───────────────────────────────────────────────────

if __name__ == "__main__":
    server_thread = threading.Thread(
        target=lambda: app.run(host="0.0.0.0", port=SERVER_PORT, debug=False, use_reloader=False),
        daemon=True
    )
    server_thread.start()

    import time
    time.sleep(2)

    friday = Friday()
    try:
        friday.run()
    except KeyboardInterrupt:
        print("\nShutting down Friday...")
