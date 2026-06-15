# Friday

> **Branch: Friday-ver-2** — This branch is a major architectural refactor targeting v1.0. Flask has been removed entirely; all processing now happens via direct function calls with no internal HTTP server.

A personal AI assistant that runs entirely on your local machine, named after the character Friday from Robinson Crusoe.

**Everything runs in a single Python file.** No separate server/client needed — just `python friday.py`.

No cloud AI required. All processing uses Whisper (speech-to-text) and Mistral 7B via Ollama (responses). ElevenLabs is supported for high-quality voice output with automatic fallback to local TTS via pyttsx3.

---

## Features

- 🎤 **Voice input** — hold SPACE to record, release to send
- ⌨️ **Text input** (dev mode) — type queries directly with streaming responses
- 🧠 **Local LLM** — Mistral 7B via Ollama, no cloud AI required
- 🔊 **ElevenLabs TTS** — high quality voice responses (optional, falls back to pyttsx3)
- 💾 **Persistent memory** — conversation history saved between sessions
- 🌐 **Web search** — optional SerpAPI integration for time-sensitive queries
- 🔒 **Private** — audio and queries never leave your machine (unless using optional APIs)
- 🛠️ **Dev mode** — verbose logging, text input, and streaming responses with mid-stream cutoff

---

## Requirements

- Python 3.10+
- [Ollama](https://ollama.ai) installed and running
- Mistral model: `ollama pull mistral`

---

## Installation

```bash
git clone https://github.com/timgrindall/friday
cd friday
pip install -r requirements.txt
```

---

## Configuration

Create a `.env` file in the project folder (optional — Friday works without any API keys):

```
# For high-quality voice output (optional)
ELEVENLABS_API_KEY=sk_your_key_here
ELEVENLABS_VOICE_ID=JBFqnCBsd6RMkjVDRZzb

# For Piper voice selection (optional, default: en_US-lessac-medium)
PIPER_VOICE=en_US-lessac-medium

# For real-time web search (optional)
SERPAPI_KEY=your_key_here
```

All are optional. Without them, Friday uses local TTS (Piper if installed, otherwise pyttsx3) and relies on Mistral's training data for answers.

---

## Usage

### Normal Mode (Voice-only)

```bash
python friday.py
```

Press **Enter** to activate, then:
- Hold **SPACE** to record voice input
- Release **SPACE** to send and hear the response
- Press **Enter** to exit voice mode

### Dev Mode (Verbose + Text input + Streaming)

```bash
python friday.py -dev
```

Commands in dev mode:
- **V** (or blank) + Enter — Voice session
- **T** + Enter — Text mode (type queries, see streaming responses in real-time)
- **quit** + Enter — Exit

In text mode, press **Enter** while a response is streaming to cut it off mid-stream.

---

## Configuration Variables

Adjust these at the top of `friday.py` to customize behavior:

```python
# Model and server
OLLAMA_MODEL = "mistral"          # Swap to "phi" for faster, lower-quality responses
OLLAMA_URL = "http://localhost:11434"
TOKEN_CAP = 1000                  # Max conversation history tokens before trimming

# Conversation context (how many past exchanges to include)
TEXT_HISTORY_TURNS = 2            # Include last 2 exchanges in text mode
VOICE_HISTORY_TURNS = 1           # Include last 1 exchange in voice mode
MAX_RESPONSE_TOKENS = 160         # Max tokens for voice responses (keep brief)
MAX_TEXT_RESPONSE_TOKENS = 800    # Max tokens for text/dev mode responses

# Memory
MEMORY_FILE = "friday_memory.json"
```

### Response Length

Voice responses are limited to ~1-2 sentences via `MAX_RESPONSE_TOKENS = 160`. Text responses allow up to ~3-4 sentences via `MAX_TEXT_RESPONSE_TOKENS = 800`.

To increase response length, raise these values. Example:

```python
MAX_RESPONSE_TOKENS = 300  # Allows longer voice responses
```

---

## Voice Output Quality Tiers

Friday uses a **three-tier fallback system** for voice output:

### 1. **ElevenLabs** (Best Quality)
- Natural, expressive speech
- Requires `ELEVENLABS_API_KEY` in `.env`
- Requires internet connection
- Commercial-grade quality

### 2. **Piper** (Good Quality, Fully Local)
- Natural-sounding speech, no API key needed
- Fully offline — no internet required
- Included in `requirements.txt`
- First time use: Piper auto-downloads a ~50-100MB voice model
- Available voices: See [Piper voices](https://github.com/rhasspy/piper/blob/master/VOICES.md)
- Default: `en_US-lessac-medium` (clear, natural, medium speed)

**Custom voice (optional):**

Add to your `.env`:

```
PIPER_VOICE=en_US-libritts_r-medium
```

Other recommended voices:
- `en_US-lessac-medium` (default, very clear)
- `en_US-libritts_r-medium` (natural, warm)
- `en_US-ryan-high` (bright, energetic)
- `en_US-ljspeech-high` (classic, widely tested)

### 3. **pyttsx3** (Basic Fallback)
- Built-in, minimal setup
- Lower audio quality
- Fast, no downloads needed
- Used if Piper is not installed

**Friday automatically chooses:**
1. ElevenLabs if API key is set and online
2. Piper if installed (on first use, downloads voice model)
3. pyttsx3 as ultimate fallback

---

## Clearing Memory

To wipe conversation history and start fresh:

```bash
# Windows
del friday_memory.json

# Mac/Linux
rm friday_memory.json
```

---

## Stack

| Component | Library | Notes |
|-----------|---------|-------|
| Speech to Text | [Whisper](https://github.com/openai/whisper) | Runs locally |
| LLM | [Ollama](https://ollama.ai) + Mistral 7B | Runs locally |
| Text to Speech | [ElevenLabs](https://elevenlabs.io) → [Piper](https://github.com/rhasspy/piper) → pyttsx3 | ElevenLabs (best), Piper (good local), pyttsx3 (basic fallback) |
| Web Search | [SerpAPI](https://serpapi.com) | Optional, triggered by keywords |
| Audio I/O | [sounddevice](https://python-sounddevice.readthedocs.io) | Cross-platform |
| Keyboard | [pynput](https://pypi.org/project/pynput/) | Global hotkeys for voice recording |

---

## Hardware Notes

Friday runs on CPU only. Response times depend on hardware:

| Hardware | Response Time |
|----------|--------------|
| Laptop CPU (no GPU) | 20-60 seconds |
| Desktop CPU | 10-30 seconds |
| Dedicated GPU | 2-5 seconds |

For faster responses on limited hardware, try:

```bash
ollama pull phi
```

Then set in `friday.py`:

```python
OLLAMA_MODEL = "phi"
```

(Phi is smaller and faster but less capable than Mistral.)

---

## Privacy

- Voice recording and transcription happen entirely on your machine
- Queries are sent to Ollama running locally (your machine)
- **ElevenLabs receives only the final text response** for TTS (if API key is set)
- **SerpAPI receives only the search query** (if API key is set)
- Conversation history is stored locally in `friday_memory.json`

---

## Web Search

Friday automatically triggers web search for time-sensitive queries containing keywords like:

- Time references: "today", "current", "latest", "now", "recent", "this week"
- Data/results: "weather", "stock", "score", "standings", "who won"
- Public figures: "elon musk", "trump", "biden", etc.
- Companies: "spacex", "tesla", "openai", "google", etc.
- Trending topics: "mars mission", "crypto", "war", "inflation", etc.

Web search requires `SERPAPI_KEY` in your `.env` file and an active internet connection. If disabled or offline, Friday falls back to its training data.

---

## Dev Mode Features

### Streaming Text Responses

In dev mode with text input (`T` + Enter), responses stream token-by-token to your terminal in real-time. This lets you see Friday "thinking" as it generates responses.

Press **Enter** while the response is streaming to cut it off early.

### Verbose Logging

Dev mode prints detailed information about:
- Memory loading/saving
- Whisper transcription results
- Web search triggers and results
- Token counts and history trimming
- API latency

Useful for debugging and understanding how Friday processes your queries.

---

## Troubleshooting

### "Cannot connect to Ollama"

Make sure Ollama is running:

```bash
ollama serve
```

### Audio not working

On Windows, if audio fails, check your sound settings. On WSL, you may need PulseAudio configuration — see [WSL audio setup](https://learn.microsoft.com/en-us/windows/wsl/tutorials/wsl-audio).

On Mac/Linux, ensure `sounddevice` can access your audio devices:

```bash
# Reinstall with system dependency
pip install --upgrade sounddevice
```

### Slow responses

If responses take 30+ seconds, consider switching to the faster `phi` model:

```bash
ollama pull phi
```

Then set `OLLAMA_MODEL = "phi"` in `friday.py`.

---

## Author Notes

This entire project was created using Claude.ai (the free version by Anthropic) and started as a hypothetical conversation that became real. The amazing thing about Friday is that **no personal data is shared across the internet** when using the local TTS fallback — it all runs on your machine.

Friday uses a small language model intentionally, so it may feel limited at times, but it's incredible software for privacy-conscious users who want a local AI assistant without cloud dependencies or subscriptions.

---

## Version

**0.65** — Added Piper TTS for higher-quality local voice output. Three-tier TTS system: ElevenLabs → Piper → pyttsx3. Auto-downloads voice models on first use. Updated README with new configuration variables and troubleshooting.
