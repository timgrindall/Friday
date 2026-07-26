# Version 1.2

"""
Friday - Voice and Text Assistant
Named after the character Friday from Robinson Crusoe

Runs as a single program - no separate server/client needed.
Just: python friday.py

Flags:
    --text       Text input mode with streaming responses
    --dev        Verbose debug logging
    --local-tts  Force local TTS (Piper/pyttsx3), skip ElevenLabs
    --no-search  Disable web search even if SerpAPI key is present
    --model      Override the Ollama model, e.g. --model mistral

In text mode, press ESC while a response is streaming to cut it off early.
"""

# ── TODO ─────────────────────────────────────────────────────────
# [ ] Research and test wake word / wake on voice feature
# [ ] Text interface — needs further testing across modes and WSL2/Ubuntu before closing
# [ ] Search heuristic over-triggering on non-time-sensitive queries (e.g. "origin of your name")
# [x] Piper: remove dead synthesize_stream_raw code path now that audio_int16_bytes is confirmed
# [ ] Update CHANGELOG for all v1.2 work on version-3 branch
# ─────────────────────────────────────────────────────────────────

import os
import sys
import json
import re
import time
import wave
import tempfile
import threading
import io
import warnings
import logging

# Suppress noisy startup messages
warnings.filterwarnings("ignore")
logging.getLogger("urllib3").setLevel(logging.ERROR)

import numpy as np
import sounddevice as sd
import whisper
import requests
from pynput import keyboard
from dotenv import load_dotenv

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
    DIM    = "\033[2m"
    GREEN  = "\033[92m"
    CYAN   = "\033[96m"
    YELLOW = "\033[93m"
    RESET  = "\033[0m"


# ── Focus Detection (Windows) ─────────────────────────────────────

if sys.platform == 'win32':
    import ctypes
    import ctypes.wintypes

    _TH32CS_SNAPPROCESS = 0x00000002

    class _PROCESSENTRY32(ctypes.Structure):
        _fields_ = [
            ("dwSize",              ctypes.wintypes.DWORD),
            ("cntUsage",            ctypes.wintypes.DWORD),
            ("th32ProcessID",       ctypes.wintypes.DWORD),
            ("th32DefaultHeapID",   ctypes.POINTER(ctypes.c_ulong)),
            ("th32ModuleID",        ctypes.wintypes.DWORD),
            ("cntThreads",          ctypes.wintypes.DWORD),
            ("th32ParentProcessID", ctypes.wintypes.DWORD),
            ("pcPriClassBase",      ctypes.c_long),
            ("dwFlags",             ctypes.wintypes.DWORD),
            ("szExeFile",           ctypes.c_char * 260),
        ]

    def _build_parent_map():
        """Return {pid: parent_pid} for all running processes."""
        k = ctypes.windll.kernel32
        snap = k.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
        if snap == ctypes.wintypes.HANDLE(-1).value:
            return {}
        entry = _PROCESSENTRY32()
        entry.dwSize = ctypes.sizeof(_PROCESSENTRY32)
        parent_map = {}
        try:
            if k.Process32First(snap, ctypes.byref(entry)):
                while True:
                    parent_map[entry.th32ProcessID] = entry.th32ParentProcessID
                    if not k.Process32Next(snap, ctypes.byref(entry)):
                        break
        finally:
            k.CloseHandle(snap)
        return parent_map

    def _foreground_pid():
        u = ctypes.windll.user32
        pid = ctypes.wintypes.DWORD(0)
        u.GetWindowThreadProcessId(u.GetForegroundWindow(), ctypes.byref(pid))
        return pid.value

    def is_console_focused():
        """
        True if the foreground window belongs to this process or any ancestor.
        Handles both classic PowerShell windows and Windows Terminal tabs.
        """
        fg   = _foreground_pid()
        pm   = _build_parent_map()
        pid  = os.getpid()
        seen = set()
        while pid and pid not in seen:
            if pid == fg:
                return True
            seen.add(pid)
            pid = pm.get(pid)
        return False

else:
    def is_console_focused():
        """Non-Windows: always True (focus check not needed)."""
        return True


# ── Status Line ───────────────────────────────────────────────────

class StatusLine:
    """
    Single-line overwriting terminal status with optional animated spinner.

    Normal mode: uses \\r to update a single line in place.
    Dev mode   : degrades to plain print() — rolling output is fine for debugging.

    All public methods are thread-safe.
    """
    _FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    _W = 60  # pad to this width to erase trailing chars

    def __init__(self):
        self._text     = ""
        self._spinning = False
        self._frame    = 0
        self._timer    = None
        self._lock     = threading.Lock()

    def set(self, text, spinner=False):
        """Update the status line. spinner=True animates a braille prefix."""
        with self._lock:
            self._halt()
            self._text     = text
            self._spinning = spinner and not DEV_MODE  # no animation in dev mode
        if DEV_MODE:
            print(f"  {text}")
        elif spinner:
            self._tick()
        else:
            self._draw(text)

    def finish(self, elapsed):
        """Show '✓  X.Xs' for 3 s then reset to 'Ready to listen...'."""
        self.set(f"✓  {elapsed:.1f}s")
        t = threading.Timer(3.0, lambda: self.set("Ready to listen..."))
        t.daemon = True
        t.start()

    def clear(self):
        """Erase the status line (no-op in dev mode)."""
        with self._lock:
            self._halt()
        if not DEV_MODE:
            sys.stdout.write(f"\r{' ' * self._W}\r")
            sys.stdout.flush()

    # ── Internal ──────────────────────────────────────────────────

    def _draw(self, content):
        line = f"  {content}"
        sys.stdout.write(f"\r{line:<{self._W}}\r{line}")
        sys.stdout.flush()

    def _tick(self):
        with self._lock:
            if not self._spinning:
                return
            f = self._FRAMES[self._frame % len(self._FRAMES)]
            self._frame += 1
            text = self._text
        self._draw(f"{f} {text}")
        with self._lock:
            if not self._spinning:
                return
            self._timer = threading.Timer(0.08, self._tick)
            self._timer.daemon = True
            self._timer.start()

    def _halt(self):
        """Stop spinner. Must be called while holding self._lock."""
        self._spinning = False
        if self._timer:
            self._timer.cancel()
            self._timer = None


status = StatusLine()


def dev_log(msg):
    """Muted rolling debug output — only active with --dev."""
    if DEV_MODE:
        print(f"  {C.DIM}{msg}{C.RESET}")


def _clear_screen():
    os.system('cls' if sys.platform == 'win32' else 'clear')


# ── Flags ─────────────────────────────────────────────────────────

DEV_MODE  = "--dev"       in sys.argv  # Verbose debug logging
TEXT_MODE = "--text"      in sys.argv  # Text input mode with streaming responses
LOCAL_TTS = "--local-tts" in sys.argv  # Skip ElevenLabs, force local TTS
NO_SEARCH = "--no-search" in sys.argv  # Disable web search even if SerpAPI key is set

def _get_flag_value(flag, default):
    """Return the value following a flag (e.g. --model mistral), or default if not passed."""
    if flag in sys.argv:
        i = sys.argv.index(flag)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return default

CLI_MODEL = _get_flag_value("--model", None)  # Override OLLAMA_MODEL, e.g. --model mistral

# ── Configuration ────────────────────────────────────────────────

OLLAMA_MODEL     = CLI_MODEL or "gemma4:e4b"
OLLAMA_URL       = "http://localhost:11434"
OLLAMA_THINK     = False   # Set True to enable model "thinking" mode (slower; supported by reasoning models e.g. Gemma 4 E4B)
OLLAMA_KEEP_ALIVE = "30m"  # How long Ollama keeps the model loaded after the last request ("-1" = forever, until Ollama restarts)
MEMORY_FILE      = "friday_memory.json"
TOKEN_CAP        = 1000
TEXT_HISTORY_TURNS  = 2     # Number of previous exchanges to include in text mode (0 = disabled)
VOICE_HISTORY_TURNS = 1     # Number of previous exchanges to include in voice mode (0 = disabled)
MAX_RESPONSE_TOKENS      = 160   # Max tokens for voice responses (Ollama's num_predict)
MAX_TEXT_RESPONSE_TOKENS = 800   # Max tokens for text/streaming responses
MIN_RECORDING_SECONDS    = 0.8   # Discard recordings shorter than this (accidental taps)

SERPAPI_KEY        = os.getenv("SERPAPI_KEY", "")
ELEVENLABS_KEY     = os.getenv("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE   = os.getenv("ELEVENLABS_VOICE_ID", "JBFqnCBsd6RMkjVDRZzb")

# Piper TTS (higher quality than pyttsx3, fully local)
# Models: https://github.com/rhasspy/piper/blob/master/VOICES.md
PIPER_VOICE        = os.getenv("PIPER_VOICE", "en_US-lessac-medium")  # Free, clear, medium quality

AUDIO_DEVICE = None  # Input device index (None = system default; set to an int to pin a specific device)
                     # Run: python -c "import sounddevice as sd; print(sd.query_devices())"

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


def clear_memory():
    """Wipe conversation history from memory and disk."""
    global conversation_history
    conversation_history = []
    save_history(conversation_history)
    if DEV_MODE:
        print("[MEMORY] Cleared")


conversation_history = load_history()


# ── Core Pipeline ─────────────────────────────────────────────────

# Whisper is loaded in __main__ so we can show a spinner during startup
whisper_model = None


def check_ollama():
    """Ping Ollama to confirm it's running before we start."""
    try:
        response = requests.get(f"{OLLAMA_URL}/api/tags", timeout=3)
        return response.status_code == 200
    except Exception:
        return False


def warm_up_ollama():
    """Send a throwaway request so Ollama loads the model into memory now,
    instead of making the first real query pay the cold-load cost."""
    status.set(f"Loading {OLLAMA_MODEL}...", spinner=True)
    err = None
    try:
        requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": OLLAMA_MODEL,
                "messages": [{"role": "user", "content": "Hi"}],
                "stream": False,
                "think": OLLAMA_THINK,
                "keep_alive": OLLAMA_KEEP_ALIVE,
                "options": {"num_predict": 1},
            },
            timeout=120
        )
    except Exception as e:
        err = e
    status.clear()
    if not err:
        dev_log(f"{OLLAMA_MODEL} ready")
    else:
        dev_log(f"Warm-up failed (first response may be slow): {err}")


def _show_banner():
    """Print the minimal startup banner, hold 3 s, then clear and hand off to Ready."""
    tts = "ElevenLabs" if (ELEVENLABS_KEY and is_online() and not LOCAL_TTS) else \
          ("Piper" if can_use_piper() else "pyttsx3")

    msg_count  = len(conversation_history)
    memory_str = f"{msg_count} messages in memory" if msg_count else "no memory yet"

    status.clear()
    print(f"\n  Friday  ·  {OLLAMA_MODEL}  ·  {tts}")
    print(f"  {C.DIM}{memory_str}{C.RESET}")
    if DEV_MODE:
        active = [f"--{f}" for f, v in [
            ("dev", DEV_MODE), ("text", TEXT_MODE),
            ("local-tts", LOCAL_TTS), ("no-search", NO_SEARCH),
        ] if v]
        if active:
            print(f"  {C.DIM}{' '.join(active)}{C.RESET}")
    print()

    time.sleep(3)

    if not DEV_MODE:
        _clear_screen()


def transcribe_audio(wav_path):
    try:
        result = whisper_model.transcribe(wav_path)
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
            print("Search offline, skipping")
        return []
    try:
        params = {"q": query, "api_key": SERPAPI_KEY, "num": 5, "engine": "google"}
        response = requests.get("https://serpapi.com/search", params=params, timeout=10)
        results = response.json()
        search_results = []
        if "organic_results" in results:
            for r in results["organic_results"][:3]:
                search_results.append({"title": r.get("title", ""), "snippet": r.get("snippet", "")})
        if DEV_MODE:
            print(f"  Search: {len(search_results)} results")
        return search_results
    except requests.exceptions.Timeout:
        print(f"  {C.YELLOW}! Search timed out, continuing without results{C.RESET}")
        return []
    except Exception as e:
        if DEV_MODE:
            print(f"[ERROR] Search failed: {e}")
        return []


# ── Search heuristics ─────────────────────────────────────────────
#
# Three independent checks. Any one match triggers a search.
#
# Case 1: Time anchor + question structure
#   A time word is only meaningful if the query is actually asking something
#   factual — "how are we doing today" should not trigger, "what's the
#   weather today" should.
#
# Case 2: Real-time data keywords
#   Words that almost always imply live data regardless of phrasing.
#
# Case 3: Named entity + state verb
#   A capitalised word (proper noun) followed by a present-tense state verb
#   suggests the user wants current information about a specific entity.

_TIME_ANCHORS = {
    "today", "right now", "currently", "at the moment", "latest", "recent",
    "recently", "just announced", "this week", "this month", "this year",
    "tomorrow", "yesterday", "still", "anymore", "now",
}

_QUESTION_WORDS = {
    "what", "who", "when", "where", "how much", "how many", "how is",
    "how are", "is ", "are ", "was ", "were ", "has ", "have ", "did ",
    "does ", "do ",
}

_REALTIME_KEYWORDS = {
    "weather", "forecast", "temperature", "price", "stock", "share price",
    "score", "standings", "results", "who won", "election", "traffic",
    "exchange rate", "crypto", "bitcoin", "inflation", "interest rate", "news",
}


_GREETING_PATTERNS = {
    "how are we", "how are you", "how are things", "how is it going",
    "how am i", "how have you", "how do you do",
}

def _case1_time_anchor_plus_question(q):
    """Time word + question structure, excluding conversational greetings."""
    has_time = any(anchor in q for anchor in _TIME_ANCHORS)
    if not has_time:
        return False
    if any(g in q for g in _GREETING_PATTERNS):
        return False
    has_question = any(qw in q for qw in _QUESTION_WORDS)
    return has_question


def _case2_realtime_keyword(q):
    """Real-time data keyword present."""
    return any(kw in q for kw in _REALTIME_KEYWORDS)


def _case3_named_entity_plus_verb(query, q):
    """
    Proper noun followed within 30 chars by a state verb.
    Excludes the first word of the sentence (likely capitalised due to grammar)
    and single-word proper nouns at position 0.
    e.g. matches: "Is Elon Musk still at Tesla?" "Apple has released..."
    e.g. no match: "What is the capital of France?" "How are you?"
    """
    # Find all proper nouns that are NOT the first word of the query
    words = query.split()
    candidates = [w for w in words[1:] if re.match(r'^[A-Z][a-zA-Z]{2,}$', w)]
    if not candidates:
        return False
    for noun in candidates:
        # Check if a state verb appears within 30 chars after the noun
        pattern = re.escape(noun) + r'.{0,30}( is | are | has | have | does | do | was | still | currently )'
        if re.search(pattern, query):
            return True
    return False


def needs_search(query):
    """
    Returns True if the query is likely to need current information.
    Three independent heuristic checks — any match triggers a search.
    """
    q = " " + query.lower() + " "  # pad so word-boundary checks work at start/end
    if _case1_time_anchor_plus_question(q):
        if DEV_MODE:
            print("  Search: time anchor + question")
        return True
    if _case2_realtime_keyword(q):
        if DEV_MODE:
            print("  Search: real-time keyword")
        return True
    if _case3_named_entity_plus_verb(query, q):
        if DEV_MODE:
            print("  Search: named entity + state verb")
        return True
    return False


def get_search_query(query, text_mode=False):
    """
    Returns the query string if a web search should be performed, or None.
    Both text and voice mode use the same heuristics.
    Returns None immediately if --no-search flag is set.
    """
    if NO_SEARCH:
        return None
    if needs_search(query):
        return query
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
        user_messages = [m["content"] for m in conversation_history if m["role"] == "user"]
        if len(user_messages) >= 2:
            return f"Your last question was: \"{user_messages[-2]}\""
        else:
            return "I don't have any previous questions in memory."
    return None


def generate_response(user_query, search_results, system_prompt, use_history=True, max_turns=None):
    global conversation_history

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
                "think": OLLAMA_THINK,
                "keep_alive": OLLAMA_KEEP_ALIVE,
                "options": {"num_predict": MAX_RESPONSE_TOKENS},
            },
            timeout=600
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


def generate_response_stream(user_query, search_results):
    """
    Generator that yields response tokens directly from Ollama.
    Handles history management and saving. Replaces the /process_text_stream route.
    """
    global conversation_history

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

    full_response = []
    try:
        with requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": OLLAMA_MODEL,
                "messages": [{"role": "system", "content": SYSTEM_PROMPT_TEXT}] + context,
                "stream": True,
                "think": OLLAMA_THINK,
                "keep_alive": OLLAMA_KEEP_ALIVE,
                "options": {"num_predict": MAX_TEXT_RESPONSE_TOKENS},
            },
            stream=True,
            timeout=600
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
    except requests.exceptions.ConnectionError:
        msg = "Ollama is not running. Please start it with: ollama serve"
        yield msg
        full_response.append(msg)
    except Exception as e:
        if DEV_MODE:
            print(f"[ERROR] Stream failed: {e}")
    finally:
        answer = "".join(full_response)
        if answer:
            conversation_history.append({"role": "assistant", "content": answer})
            save_history(conversation_history)


def text_to_speech(text):
    """
    TTS priority chain:
    1. ElevenLabs (best quality, requires API key + internet)
    2. Piper (good quality, fully local, no API key)
    3. pyttsx3 (basic quality, fully local, no setup)
    Use --local-tts flag to skip ElevenLabs and force local TTS.
    """
    if ELEVENLABS_KEY and is_online() and not LOCAL_TTS:
        return tts_elevenlabs(text)
    elif can_use_piper():
        return tts_piper(text)
    else:
        return tts_local(text)


def can_use_piper():
    """Check if piper-tts is installed."""
    try:
        import piper
        return True
    except ImportError:
        return False


def _piper_voice_dir():
    """Platform-appropriate directory for Piper voice models."""
    if sys.platform == 'win32':
        return os.path.join(os.path.expanduser("~"), "piper", "voices")
    return os.path.expanduser("~/.local/share/piper/voices")


def _piper_model_path():
    """Full path to the configured Piper .onnx model file."""
    return os.path.join(_piper_voice_dir(), f"{PIPER_VOICE}.onnx")


def _piper_model_url(filename):
    """Build the Hugging Face download URL for a Piper voice file.
    e.g. en_US-lessac-medium → .../en/en_US/lessac/medium/filename"""
    parts = PIPER_VOICE.split("-")
    if len(parts) < 3:
        return None
    region, name, quality = parts[0], parts[1], parts[2]
    lang = region.split("_")[0]
    base = f"https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/{lang}/{region}/{name}/{quality}"
    return f"{base}/{filename}"


def _ensure_piper_model():
    """Download Piper voice model files at boot if not already present."""
    model_path  = _piper_model_path()
    config_path = model_path + ".json"
    if os.path.exists(model_path) and os.path.exists(config_path):
        dev_log(f"Piper model found: {model_path}")
        return
    status.set(f"Downloading Piper voice ({PIPER_VOICE})...", spinner=True)
    dev_log("Piper model not found, downloading from Hugging Face...")
    os.makedirs(_piper_voice_dir(), exist_ok=True)
    for filename in [f"{PIPER_VOICE}.onnx", f"{PIPER_VOICE}.onnx.json"]:
        dest = os.path.join(_piper_voice_dir(), filename)
        if os.path.exists(dest):
            continue
        url = _piper_model_url(filename)
        if not url:
            dev_log(f"Piper: couldn't parse voice name into URL: {PIPER_VOICE}")
            status.clear()
            return
        dev_log(f"Downloading {url}")
        try:
            r = requests.get(url, stream=True, timeout=300)
            r.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
        except Exception as e:
            dev_log(f"Piper download failed ({filename}): {e}")
            status.clear()
            return
    status.clear()
    dev_log("Piper model ready")


def tts_elevenlabs(text):
    try:
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE}?output_format=pcm_16000"
        headers = {"xi-api-key": ELEVENLABS_KEY, "Content-Type": "application/json"}
        payload = {
            "text": text,
            "model_id": "eleven_flash_v2_5",
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
            return tts_piper(text) if can_use_piper() else tts_local(text)

    except Exception as e:
        if DEV_MODE:
            print(f"[ERROR] ElevenLabs failed: {e}, falling back")
        return tts_piper(text) if can_use_piper() else tts_local(text)


def tts_piper(text):
    """High-quality local TTS using Piper. Model downloaded at boot via _ensure_piper_model()."""
    try:
        from piper.voice import PiperVoice

        model_path = _piper_model_path()
        if not os.path.exists(model_path):
            dev_log(f"Piper model missing at {model_path}, falling back to pyttsx3")
            return tts_local(text)

        voice = PiperVoice.load(model_path, use_cuda=False)
        wav_buffer = io.BytesIO()
        sample_rate = getattr(getattr(voice, 'config', None), 'sample_rate', 22050)

        with wave.open(wav_buffer, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            for chunk in voice.synthesize(text):
                raw = None
                for attr in ('audio_int16_bytes', 'audio', 'audio_bytes', 'data', 'samples'):
                    val = getattr(chunk, attr, None)
                    if val is not None:
                        raw = val.tobytes() if hasattr(val, 'tobytes') else bytes(val)
                        break
                if raw is None:
                    dev_log(f"Unknown chunk format — type: {type(chunk).__name__}, attrs: {[a for a in dir(chunk) if not a.startswith('_')]}")
                    return tts_local(text)
                wf.writeframes(raw)

        audio_bytes = wav_buffer.getvalue()
        dev_log(f"TTS: Piper ({PIPER_VOICE}, {len(audio_bytes)} bytes)")
        return audio_bytes

    except ImportError:
        dev_log("Piper not installed, falling back to pyttsx3")
        return tts_local(text)
    except Exception as e:
        dev_log(f"Piper TTS failed ({e}), falling back to pyttsx3")
        return tts_local(text)


def tts_local(text):
    """Fallback: Basic TTS using pyttsx3 (no setup required)."""
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
            print(f"[TTS] pyttsx3 ({len(audio_bytes)} bytes)")
        return audio_bytes
    except Exception as e:
        if DEV_MODE:
            print(f"[ERROR] Local TTS failed: {e}")
        return None


# ── Processing Functions (replaces Flask routes) ──────────────────

def process_voice(wav_path):
    """
    Full voice pipeline: transcribe → search → LLM → TTS.
    Status line is updated throughout so the UI stays in sync.
    """
    dev_log("Voice command received")

    user_query = transcribe_audio(wav_path)
    if not user_query:
        return None

    search_query = get_search_query(user_query)
    if search_query:
        status.set("Searching...", spinner=True)
        search_results = web_search(search_query)
    else:
        search_results = []

    status.set("Thinking...", spinner=True)
    response_text = generate_response(
        user_query, search_results, SYSTEM_PROMPT_VOICE,
        use_history=True, max_turns=VOICE_HISTORY_TURNS
    )

    status.set("Generating audio...", spinner=True)
    return text_to_speech(response_text)


def process_text(user_query):
    """
    Process a text query and return a response string.
    Replaces the /process_text Flask route.
    """
    dev_log("Text query received")

    search_query = get_search_query(user_query)
    search_results = web_search(search_query) if search_query else []
    return generate_response(
        user_query, search_results, SYSTEM_PROMPT_TEXT,
        use_history=TEXT_HISTORY_TURNS > 0,
        max_turns=TEXT_HISTORY_TURNS if TEXT_HISTORY_TURNS > 0 else None
    )


# ── Client Interface ──────────────────────────────────────────────

class Friday:
    def __init__(self):
        self.recording  = False
        self.audio_frames = []
        self.running    = False
        self.playback_done = threading.Event()

        self.CHANNELS = 1
        self.RATE = 16000
        self.INPUT_FILE  = AUDIO_INPUT
        self.OUTPUT_FILE = AUDIO_OUTPUT
        self.RECORDING_WARMUP_SECONDS = 1.25

    # ── Voice ─────────────────────────────────────────────────────

    def start_recording(self):
        if self.recording:
            return
        self.recording = True
        self.audio_frames = []
        self._recording_started_at = time.time()

        def callback(indata, frames, time_info, status_flag):
            if self.recording and (time.time() - self._recording_started_at) >= self.RECORDING_WARMUP_SECONDS:
                self.audio_frames.append(indata.copy())

        try:
            self.stream = sd.InputStream(
                samplerate=self.RATE, channels=self.CHANNELS,
                dtype='int16', callback=callback,
                device=AUDIO_DEVICE
            )
            self.stream.start()
        except Exception as e:
            self.recording = False
            dev_log(f"Audio device error: {e}")
            dev_log("Available input devices:")
            for i, d in enumerate(sd.query_devices()):
                if d['max_input_channels'] > 0:
                    dev_log(f"  [{i}] {d['name']} ({d['max_input_channels']}ch)")
            status.set("Ready to listen...")
            self.playback_done.set()
            return

        def _set_recording_status():
            if self.recording:
                status.set("● Recording...")

        self._speak_now_timer = threading.Timer(self.RECORDING_WARMUP_SECONDS, _set_recording_status)
        self._speak_now_timer.daemon = True
        self._speak_now_timer.start()

    def stop_recording(self):
        if not self.recording:
            return None
        self.recording = False
        if hasattr(self, '_speak_now_timer'):
            self._speak_now_timer.cancel()
        try:
            self.stream.stop()
            self.stream.close()

            if not self.audio_frames:
                dev_log(f"0 frames captured — hold shorter than {self.RECORDING_WARMUP_SECONDS}s warmup")
                status.set("Ready to listen...")
                return None

            audio_data = np.concatenate(self.audio_frames, axis=0)
            duration_s = len(audio_data) / self.RATE
            dev_log(f"Captured {duration_s:.2f}s of audio ({len(self.audio_frames)} chunks)")

            if duration_s < MIN_RECORDING_SECONDS:
                dev_log(f"Too short ({duration_s:.2f}s < {MIN_RECORDING_SECONDS}s) — discarded")
                status.set("Ready to listen...")
                return None

            # Prepend 1s of silence so Whisper doesn't mishear the first words
            silence = np.zeros((int(self.RATE * 1.0), self.CHANNELS), dtype=np.int16)
            audio_data = np.concatenate([silence, audio_data])
            with wave.open(self.INPUT_FILE, 'wb') as wf:
                wf.setnchannels(self.CHANNELS)
                wf.setsampwidth(2)
                wf.setframerate(self.RATE)
                wf.writeframes(audio_data.tobytes())
            dev_log("Recording saved")
            return self.INPUT_FILE

        except Exception as e:
            dev_log(f"Recording save failed: {e}")
            return None

    def _suppress_echo(self):
        """Disable terminal echo."""
        if sys.platform == 'win32':
            import ctypes
            import ctypes.wintypes
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.GetStdHandle(-10)
            mode = ctypes.wintypes.DWORD()
            kernel32.GetConsoleMode(handle, ctypes.byref(mode))
            self._old_console_mode = mode.value
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
        import msvcrt
        while msvcrt.kbhit():
            msvcrt.getwch()
        time.sleep(0.1)
        self._suppress_echo()

        space_released = threading.Event()
        cancelled = threading.Event()

        def on_press(key):
            if key == keyboard.Key.space:
                if not self.recording and is_console_focused():
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
            status.set("Ready to listen...")
            self.playback_done.set()
            return

        wav_file = self.stop_recording()
        if wav_file:
            threading.Thread(target=self._handle_voice, args=(wav_file,), daemon=True).start()
        else:
            self.playback_done.set()

    def _drain_stdin(self):
        """Flush any buffered input before the next prompt."""
        import termios
        termios.tcflush(sys.stdin, termios.TCIFLUSH)

    def _voice_enter(self):
        input()
        self._drain_stdin()
        self.start_recording()
        input()
        self._drain_stdin()
        wav_file = self.stop_recording()
        if wav_file:
            threading.Thread(target=self._handle_voice, args=(wav_file,), daemon=True).start()
        else:
            self.playback_done.set()

    def _handle_voice(self, wav_file):
        """Call process_voice() directly and play the result."""
        t_start = time.time()
        try:
            audio_bytes = process_voice(wav_file)
            if audio_bytes:
                self._play_audio(audio_bytes, t_start)
            else:
                dev_log("No audio generated")
                status.set("Ready to listen...")
                self.playback_done.set()
        except Exception as e:
            dev_log(f"Voice processing error: {e}")
            status.set("Ready to listen...")
            self.playback_done.set()

    def _play_audio(self, audio_bytes, t_start=None):
        if not audio_bytes:
            self.playback_done.set()
            return
        try:
            with open(self.OUTPUT_FILE, 'wb') as f:
                f.write(audio_bytes)
            status.set("♪ Playing...")
            with wave.open(self.OUTPUT_FILE, 'rb') as wf:
                framerate = wf.getframerate()
                audio_data = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)
                silence = np.zeros(int(framerate * 0.3), dtype=np.int16)
                audio_data = np.concatenate([silence, audio_data])
                sd.play(audio_data, samplerate=framerate)
                sd.wait()
            if t_start:
                status.finish(time.time() - t_start)
            else:
                status.set("Ready to listen...")
        except Exception as e:
            dev_log(f"Playback failed: {e}")
            status.set("Ready to listen...")
        finally:
            self.playback_done.set()

    # ── Text ──────────────────────────────────────────────────────

    def do_text_session(self):
        """Text input loop — active when --text flag is set. 'quit' or Ctrl+C to exit."""
        while True:
            try:
                text = input("\n  > ").strip()
            except (EOFError, KeyboardInterrupt):
                raise
            if not text:
                continue
            if text.lower() == "quit":
                if not DEV_MODE:
                    _clear_screen()
                print("\n  Goodbye.\n")
                sys.exit(0)
            try:
                self._stream_text_response(text)
            except KeyboardInterrupt:
                raise

    def _stream_text_response(self, text):
        """Stream response tokens to terminal. ESC to cut off mid-stream.
        After completion: pause briefly, clear screen, reset to Ready."""
        stop_event  = threading.Event()
        stream_done = threading.Event()
        full_response = []

        def watch_for_esc():
            if stream_done.wait(timeout=0.05):
                return
            try:
                if sys.platform == 'win32':
                    import msvcrt
                    while not stream_done.is_set():
                        if msvcrt.kbhit():
                            if msvcrt.getwch() == '\x1b':
                                stop_event.set()
                                return
                else:
                    from pynput import keyboard as kb
                    def on_press(key):
                        if key == kb.Key.esc:
                            stop_event.set()
                            return False
                    with kb.Listener(on_press=on_press) as listener:
                        stream_done.wait()
                        listener.stop()
            except (EOFError, KeyboardInterrupt):
                stop_event.set()

        threading.Thread(target=watch_for_esc, daemon=True).start()

        t_start = time.time()
        stopped_early = False
        elapsed = 0.0

        search_query = get_search_query(text)
        if search_query:
            status.set("Searching...", spinner=True)
            search_results = web_search(search_query)
        else:
            search_results = []

        status.set("Thinking...", spinner=True)

        try:
            first_token = True
            for token in generate_response_stream(text, search_results):
                if stop_event.is_set():
                    elapsed = time.time() - t_start
                    print(f" {C.YELLOW}[stopped at {elapsed:.1f}s]{C.RESET}")
                    stopped_early = True
                    break
                if first_token:
                    status.clear()
                    print(f"\n  Friday: ", end="", flush=True)
                    first_token = False
                print(token, end="", flush=True)
                full_response.append(token)
            else:
                elapsed = time.time() - t_start
                print(f"\n\n  {C.GREEN}✓ {elapsed:.1f}s{C.RESET}")
        except Exception as e:
            dev_log(f"Stream error: {e}")
        finally:
            stream_done.set()

        if not stopped_early and full_response:
            response_text = "".join(full_response)
            time.sleep(1.0)
            if not DEV_MODE:
                _clear_screen()
            print(f"\n  Friday: {response_text}")
            print(f"\n  {C.GREEN}✓ {elapsed:.1f}s{C.RESET}\n")

    # ── Main Loop ─────────────────────────────────────────────────

    def _voice_loop(self):
        """Continuous voice loop — runs in a background thread."""
        while self.running:
            self.playback_done.clear()
            self.do_voice_session()
            self.playback_done.wait()

    def _run_voice(self):
        """Start the voice loop. Main thread sleeps; Ctrl+C to exit."""
        self.running = True
        voice_thread = threading.Thread(target=self._voice_loop, daemon=True)
        voice_thread.start()
        try:
            while self.running:
                time.sleep(0.1)
        except KeyboardInterrupt:
            self.running = False
            if not DEV_MODE:
                _clear_screen()
            print("\n  Goodbye.\n")
            sys.exit(0)

    def _run_text(self):
        """Text input mode. 'quit' or Ctrl+C to exit."""
        try:
            self.do_text_session()
        except KeyboardInterrupt:
            if not DEV_MODE:
                _clear_screen()
            print("\n  Goodbye.\n")
            sys.exit(0)

    def run(self):
        if TEXT_MODE:
            self._run_text()
        else:
            self._run_voice()


# ── Entry Point ───────────────────────────────────────────────────

if __name__ == "__main__":
    # First-run check — nudge user to run setup if .env is missing
    if not os.path.exists(".env"):
        print(f"\n{C.YELLOW}  ! No .env file found.{C.RESET}")
        print(f"  Looks like this might be your first time running Friday.")
        print(f"  Run {C.GREEN}python setup.py{C.RESET} to install dependencies and configure API keys.")
        print(f"\n  Friday will still run without it — API features will be disabled.\n")
        try:
            input("  Press Enter to continue anyway, or Ctrl+C to run setup first...\n")
        except KeyboardInterrupt:
            print("\n  Run: python setup.py")
            sys.exit(0)

    # Confirm Ollama is reachable before loading anything heavy
    if not check_ollama():
        print(f"\n{C.YELLOW}  ! Cannot reach Ollama.{C.RESET}")
        print(f"  Make sure it's running with: ollama serve\n")
        sys.exit(1)

    # Load Whisper with spinner
    status.set("Loading Whisper...", spinner=True)
    whisper_model = whisper.load_model("base")
    status.clear()
    dev_log("Whisper ready")

    # Load Ollama model with spinner
    warm_up_ollama()

    # If Piper will be the TTS, ensure model is downloaded before we need it
    if can_use_piper() and not (ELEVENLABS_KEY and is_online() and not LOCAL_TTS):
        _ensure_piper_model()

    # Banner → 3 s → clear → Ready
    _show_banner()
    status.set("Ready..." if TEXT_MODE else "Ready to listen...")

    friday = Friday()
    try:
        friday.run()
    except KeyboardInterrupt:
        print("\n  Goodbye.\n")
        sys.exit(0)
