# Friday Changelog

---

## v0.71
- Ctrl+C in text mode now exits cleanly without traceback (EOFError and KeyboardInterrupt caught in watcher thread and text session)
- Changed stream interrupt key from Enter to ESC to avoid accidental cutoffs
- Text session now shows ESC hint on entry
- Search result count now displays in white without checkmark
- Only first sentence of query sent to search for cleaner results
- Vague follow-up queries ("those", "them", "it" etc.) now resolve context from prior conversation before searching
- Renamed --offline-tts to --local-tts

## v0.70
- Increased search timeout from 5s to 10s
- Search timeouts now print a friendly warning and continue without results
- Stream generator now catches Ollama connection errors and yields a clear message instead of silent failure

## v0.69
- Renamed `--offline-tts` flag to `--local-tts`
- Text mode now always performs a web search; voice mode continues to use keyword triggers only
- Updated setup.py to match Friday's color scheme and banner style
- Added first-run detection: if no `.env` is found, Friday prompts the user to run `setup.py`

## v0.68
- Changed all flags to double-dash format (`--dev`, `--local-tts`, `--no-search`, `--voice`)
- Fixed missing done message and elapsed time after `--voice` playback in text mode

## v0.67
- Fixed bug where Friday did not recognize keyboard input on first try when in text mode
  (dangling watcher thread was racing with the next `input()` prompt after streaming)

## v0.66
- Added `--local-tts` flag to force local TTS (Piper/pyttsx3) even if ElevenLabs key is present
- Added `--no-search` flag to disable web search even if SerpAPI key is present
- Added `--voice` flag to enable audio playback in text/dev mode

## v0.65
- Added Piper TTS as a higher-quality local fallback (ElevenLabs → Piper → pyttsx3)
- Fixed startup status showing ElevenLabs even when offline or key not set
- Updated README to reflect single-file architecture and all new config variables
- Added `piper-tts` to requirements.txt

## v0.64
- Streaming responses in dev/text mode with mid-stream cutoff (press Enter to stop)
- Researched Mistral 4 Small — ruled out, exceeds available RAM on low-end hardware
