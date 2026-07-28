# Friday

A personal AI voice and text assistant that runs entirely on your local machine. Named after the character Friday from Robinson Crusoe.

No cloud AI required. Everything runs locally using Whisper for speech-to-text and a local LLM via Ollama for responses.

---

## Prerequisites

- Python 3.10+
- [Ollama](https://ollama.ai) installed and running
- A local model pulled, e.g. `ollama pull mistral`

---

## Installation

```bash
git clone https://github.com/timgrindall/Friday
cd Friday
python setup.py
```

The setup script installs dependencies and optionally configures API keys for ElevenLabs (voice output) and SerpAPI (web search). Both are optional — Friday works fully offline without them.

---

## Usage

```bash
python friday.py
```

Hold **SPACE** to record, release to send. On Linux, press **SPACE** to start recording, **SPACE** again to stop. Press **Ctrl+C** to exit.

### Flags

| Flag | Effect |
|------|--------|
| `--dev` | Verbose logging |
| `--text` | Text input with streaming responses |
| `--local-tts` | Force local TTS, skip ElevenLabs |
| `--no-search` | Disable web search |
| `--model <name>` | Override the Ollama model |

---

## Privacy

Audio and queries never leave your machine unless you've configured ElevenLabs (sends response text for TTS) or SerpAPI (sends search queries). Conversation history is stored locally in `friday_memory.json`.

