# Friday

Personal assistant that runs on your local machine named after the character Friday from Robinson Crusoe.

No cloud AI required. Everything runs locally using Whisper for speech-to-text and Mistral 7B via Ollama for responses. ElevenLabs is supported for high quality voice output with automatic fallback to local TTS.

---

## Features

- 🎤 **Voice input** — hold SPACE to record, release to send
- ⌨️ **Text input** — type queries directly in the terminal
- 🧠 **Local LLM** — Mistral 7B via Ollama, no cloud AI required
- 🔊 **ElevenLabs TTS** — high quality voice responses (optional, falls back to pyttsx3)
- 💾 **Persistent memory** — conversation history saved between sessions
- 🌐 **Web search** — optional SerpAPI integration for real-time information
- 🔒 **Private** — audio and queries never leave your machine (unless using optional APIs)
- 🛠️ **Dev mode** — verbose logging for debugging

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

Create a `.env` file in the project folder:

```
# Required for ElevenLabs voice (optional - falls back to pyttsx3)
ELEVENLABS_API_KEY=sk_your_key_here
ELEVENLABS_VOICE_ID=JBFqnCBsd6RMkjVDRZzb

# Required for web search (optional)
SERPAPI_KEY=your_key_here
```

Both are optional — Friday works without any API keys using local TTS and Mistral's training data.

---

## Usage

```bash
# Terminal 1 - start Ollama
ollama serve

# Terminal 2 - start Friday
python friday.py

# Dev mode (verbose logging)
python friday.py -dev
```

Once running, press **Enter** to activate, then:

| Command | Action |
|---------|--------|
| `V` + Enter | Voice mode — hold SPACE to record, release to send |
| `T` + Enter | Text mode — type queries, blank line or ESC to exit |
| `S` + Enter | Standby |
| `ESC` | Exit current mode, return to standby |
| `quit` | Exit Friday |

---

## Settings

Key settings at the top of `friday.py`:

```python
OLLAMA_MODEL = "mistral"   # swap to "phi" for faster but lower quality
TOKEN_CAP    = 2000        # max conversation history tokens
```

Response length is controlled by `num_predict` in `generate_response()`:

```python
"num_predict": 160   # increase for longer responses
```

---

## Clearing Memory

To wipe conversation history and start fresh, delete the memory file:

```bash
# Windows
del friday_memory.json

# Mac/Linux
rm friday_memory.json
```

Or via the API while Friday is running:

```bash
curl -X POST http://localhost:5001/memory/clear
```

---

## Stack

| Component | Library | Notes |
|-----------|---------|-------|
| Speech to Text | [Whisper](https://github.com/openai/whisper) | Runs locally |
| LLM | [Ollama](https://ollama.ai) + Mistral 7B | Runs locally |
| Text to Speech | [ElevenLabs](https://elevenlabs.io) | Optional, falls back to pyttsx3 |
| Web Search | [SerpAPI](https://serpapi.com) | Optional |
| Audio I/O | [sounddevice](https://python-sounddevice.readthedocs.io) | Cross-platform |
| Server | [Flask](https://flask.palletsprojects.com) | Internal, runs in background thread |

---

## Hardware Notes

Friday runs on CPU only. Response times vary by hardware:

| Hardware | Response Time |
|----------|--------------|
| Laptop CPU (no GPU) | 20-60 seconds |
| Desktop CPU | 10-30 seconds |
| Dedicated GPU | 2-5 seconds |

For faster responses on limited hardware, try `ollama pull phi` and set `OLLAMA_MODEL = "phi"`.

---

## Privacy

- Voice recording and transcription happen entirely on your machine
- Queries are sent to Ollama running locally
- ElevenLabs receives only the text response for TTS (if API key is set)
- SerpAPI receives only the search query (if API key is set)
- Conversation history is stored locally in `friday_memory.json`

---

## Author Notes

I intentionally used a small model for running on small machines so it may feel limited at times, but it's still amazing software. This entire project was created using the free version of Claude.ai by Anthropic and started as simply as a hypothetical project which then became real when Claude asked, "Would you like me to create the files for this project?". A few iterations and user testing later, we got to version 5 as you see here.

The amazing thing about this piece of software is that no personal info is shared across the web. It all runs locally on your machine. I wish software like this could become the future of AI instead of being stuck with a subscription to a cloud provider.
