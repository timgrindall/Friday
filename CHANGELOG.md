# Friday Changelog

---

## v0.68
- Changed all flags to double-dash format (`--dev`, `--local`, `--no-search`, `--voice`)
- Fixed missing done message and elapsed time after `--voice` playback in text mode

## v0.67
- Fixed bug where Friday did not recognize keyboard input on first try when in text mode
  (dangling watcher thread was racing with the next `input()` prompt after streaming)

## v0.66
- Added `--local` flag to force local TTS (Piper/pyttsx3) even if ElevenLabs key is present
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
