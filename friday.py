# Version 0.14

"""
Friday - Voice and Text Assistant
Named after the character Friday from Robinson Crusoe

Runs as a single program - no separate server/client needed.
Just: python friday.py

Dev mode (verbose logging + text input):
    python friday.py -dev
"""

import os
import sys
import json
import wave
import tempfile
import threading
import io
from datetime import datetime
from io import BytesIO

import numpy as np
import sounddevice as sd
import whisper
import requests
from pynput import keyboard
from dotenv import load_dotenv
from flask import Flask, request, send_file, jsonify

load_dotenv()

# ── Dev mode ─────────────────────────────────────────────────────

DEV_MODE = "-dev" in sys.argv

# ── Configuration ────────────────────────────────────────────────

OLLAMA_MODEL     = "mistral"
OLLAMA_URL       = "http://localhost:11434"
MEMORY_FILE      = "friday_memory.json"
TOKEN_CAP        = 2000
SERVER_PORT      = 5001
SERVER_URL       = f"http://localhost:{SERVER_PORT}"

SERPAPI_KEY        = os.getenv("SERPAPI_KEY", "")
ELEVENLABS_KEY     = os.getenv("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE   = os.getenv("ELEVENLABS_VOICE_ID", "JBFqnCBsd6RMkjVDRZzb")

TEMP_DIR     = tempfile.gettempdir()
AUDIO_INPUT  = os.path.join(TEMP_DIR, "friday_input.wav")
AUDIO_OUTPUT = os.path.join(TEMP_DIR, "friday_output.wav")

SYSTEM_PROMPT_VOICE = (
    "You are Friday, a helpful voice assistant. "
    "Give clear, natural responses of 3-4 sentences suitable for speaking aloud. "
    "Be conversational and informative."
)

SYSTEM_PROMPT_TEXT = (
    "You are Friday, a helpful assistant. "
    "Give well-structured, clear, and informative responses of 3-4 sentences."
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


def trim_history(history):
    while estimate_tokens(history) > TOKEN_CAP and len(history) > 2:
        history.pop(0)
        if history and history[0]["role"] == "assistant":
            history.pop(0)
    if DEV_MODE:
        print(f"[MEMORY] {len(history)} messages (~{estimate_tokens(history)} tokens)")
    return history


conversation_history = load_history()


# ── Core Pipeline ─────────────────────────────────────────────────

print("[FRIDAY] Loading Whisper...")
whisper_model = whisper.load_model("base")
print("[FRIDAY] Whisper ready")


def transcribe_audio(audio_bytes):
    try:
        with open(AUDIO_INPUT, "wb") as f:
            f.write(audio_bytes)
        result = whisper_model.transcribe(AUDIO_INPUT)
        text = result["text"].strip()
        if DEV_MODE:
            print(f"[STT] {text}")
        return text
    except Exception as e:
        print(f"[ERROR] Transcription failed: {e}")
        return None


def web_search(query):
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


def generate_response(user_query, search_results, system_prompt):
    global conversation_history

    content = user_query
    if search_results:
        results_text = "\n".join([f"- {r['title']}: {r['snippet']}" for r in search_results])
        content = f"{user_query}\n\nSearch results:\n{results_text}"

    conversation_history.append({"role": "user", "content": content})
    conversation_history = trim_history(conversation_history)

    try:
        response = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": OLLAMA_MODEL,
                "messages": [{"role": "system", "content": system_prompt}] + conversation_history,
                "stream": False,
                "options": {"num_predict": 300},
            },
            timeout=180
        )

        if response.status_code == 200:
            answer = response.json()["message"]["content"].strip()
            if DEV_MODE:
                print(f"[RESPONSE] {answer}")
            conversation_history.append({"role": "assistant", "content": answer})
            save_history(conversation_history)
            return answer
        else:
            if DEV_MODE:
                print(f"[ERROR] Ollama error: {response.status_code}")
            return "I'm having trouble processing that."

    except requests.exceptions.ConnectionError:
        return "Ollama is not running. Please start it with: ollama serve"
    except Exception as e:
        if DEV_MODE:
            print(f"[ERROR] Response failed: {e}")
        return "I'm sorry, I had trouble processing that."


def text_to_speech(text):
    return tts_elevenlabs(text) if ELEVENLABS_KEY else tts_local(text)


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
        search_results = web_search(user_query) if SERPAPI_KEY else []
        if DEV_MODE and not SERPAPI_KEY:
            print("[SEARCH] Skipped")
        response_text = generate_response(user_query, search_results, SYSTEM_PROMPT_VOICE)
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
        if DEV_MODE:
            print(f"[TEXT] {user_query}")
        search_results = web_search(user_query) if SERPAPI_KEY else []
        if DEV_MODE and not SERPAPI_KEY:
            print("[SEARCH] Skipped")
        response_text = generate_response(user_query, search_results, SYSTEM_PROMPT_TEXT)
        return jsonify({"response": response_text})
    except Exception as e:
        if DEV_MODE:
            print(f"[ERROR] {e}")
        return {"error": str(e)}, 500


@app.route("/health", methods=["GET"])
def health():
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

        self.CHANNELS = 1
        self.RATE = 16000
        self.INPUT_FILE = AUDIO_INPUT
        self.OUTPUT_FILE = AUDIO_OUTPUT

    def _print_banner(self):
        print("\n" + "="*50)
        print("FRIDAY - STANDBY")
        print("="*50)
        print(f"Model:   {OLLAMA_MODEL}")
        print(f"Memory:  {MEMORY_FILE}")
        print(f"TTS:     {'ElevenLabs' if ELEVENLABS_KEY else 'pyttsx3 (local)'}")
        print(f"Search:  {'SerpAPI' if SERPAPI_KEY else 'Disabled'}")
        if DEV_MODE:
            print(f"Mode:    DEV (text input enabled)")
        print("\nPress Enter to activate.\n")

    def _print_active(self):
        print("\n" + "="*50)
        print("FRIDAY - ACTIVE")
        print("="*50)
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
            if DEV_MODE:
                print("[>>] Sending to Friday...")
            with open(wav_file, 'rb') as f:
                response = requests.post(f"{SERVER_URL}/process", files={'audio': f}, timeout=180)
            if response.status_code == 200:
                self._play_audio(response.content)
        except Exception as e:
            print(f"[!!] Error: {e}")

    def _play_audio(self, audio_bytes):
        if not audio_bytes:
            return
        try:
            with open(self.OUTPUT_FILE, 'wb') as f:
                f.write(audio_bytes)
            if DEV_MODE:
                print("[>>] Playing response...\n")
            with wave.open(self.OUTPUT_FILE, 'rb') as wf:
                framerate = wf.getframerate()
                audio_data = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)
                # Prepend 300ms of silence so the audio device is primed before speech starts
                silence = np.zeros(int(framerate * 0.3), dtype=np.int16)
                audio_data = np.concatenate([silence, audio_data])
                sd.play(audio_data, samplerate=framerate)
                sd.wait()
            if DEV_MODE:
                print("[OK] Done\n")
        except Exception as e:
            print(f"[ERROR] Playback failed: {e}\n")

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
                if DEV_MODE:
                    print("[>>] Sending to Friday...")
                response = requests.post(
                    f"{SERVER_URL}/process_text",
                    json={"text": text},
                    timeout=180
                )
                if response.status_code == 200:
                    reply = response.json().get("response", "")
                    if reply:
                        print("\n" + "-"*50)
                        print(f"Friday: {reply}")
                        print("-"*50 + "\n")
            except Exception as e:
                print(f"[!!] Error: {e}")

    # ── Main Loop ─────────────────────────────────────────────────

    def run(self):
        self._print_banner()
        while True:
            cmd = input().strip().lower()

            if not self.active:
                if cmd == "":
                    self.active = True
                    self._print_active()
                elif cmd == "quit":
                    print("Goodbye.")
                    sys.exit(0)
                continue

            if cmd == "quit":
                print("Goodbye.")
                sys.exit(0)
            elif cmd == "t" and DEV_MODE:
                self.do_text_session()
            else:
                # Enter (empty string) or anything unrecognised → voice session
                self.do_voice_session()


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
