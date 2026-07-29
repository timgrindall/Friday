# Friday Changelog

---

## v1.3 (branch: version-3)
Ubuntu/WSL2 compatibility and startup improvements.

**Linux voice mode**
- Replaced pynput hold-to-talk on Linux with a stdin toggle mode (`_voice_linux`) — SPACE to start recording, SPACE again to stop; works reliably in WSL2 without X server
- `READY_MSG` constant is now platform-aware: Linux shows "Press SPACE to start · SPACE to stop", Windows shows "Ready to listen..."
- `● Recording...` status now appears immediately on SPACE press; `🎤 Speak now...` appears after the 1.25s warmup window
- Added 80ms debounce to `_voice_pynput` `on_release` to handle X11 phantom auto-repeat releases on Linux

**Ctrl+C exit**
- All exit handlers now use `os._exit(0)` instead of `sys.exit(0)` — avoids hanging on daemon thread cleanup
- `_restore_echo()` called explicitly before exit so terminal is never left in cbreak mode
- `\r\033[K` prefix on Goodbye message erases the `^C` echo character from the terminal
- `space_released.wait()` replaced with a 100ms timeout loop that checks `self.running` — listener unblocks cleanly on shutdown

**Startup**
- `print("  Friday is loading...", flush=True)` added before all imports — gives immediate feedback during the 20-60s PyTorch cold-start on Ubuntu
- `status.set("Starting...", spinner=True)` now fires as the first line of `__main__`
- Fixed `NameError` on `READY_MSG` when running on Windows

**Text mode**
- Removed trailing `\n` from the `✓ Xs` done line — eliminates double blank line before the `>` prompt

**Setup and docs**
- `setup.py` now downloads the Piper voice model as part of setup (prompted, one-time, reads `PIPER_VOICE` from `.env` if set)
- README rewritten — cut from 310 lines to 52; configuration details deferred to `setup.py`

---


Complete UI overhaul — minimalist single-line status interface.

**StatusLine**
- New `StatusLine` class replaces all `rich` console output — uses `\r` to update a single terminal line in place, with an animated braille spinner for async states
- In `--dev` mode degrades gracefully to plain `print()` (rolling output)
- States cycle: `● Recording...` → `⠋ Thinking...` → `♪ Playing...` → `✓ Xs` (3 s) → `Ready`
- `finish(elapsed)` shows elapsed time then auto-transitions to `Ready` after 3 s
- `dev_log()` replaces all `if DEV_MODE: print(...)` blocks — muted dim colour, no-op in normal mode
- Removed `rich` dependency from codebase

**Boot sequence**
- Whisper now loads lazily in `__main__` behind a spinner (`Loading Whisper...`) rather than silently at module level
- `warm_up_ollama()` shows a spinner during model load
- Minimal banner (`Friday · model · TTS provider`) displays for 3 s then screen clears to `Ready`
- In `--dev` mode screen is not cleared so warmup logs remain visible

**Voice mode**
- `start_recording()` sets `● Recording...` after the warmup window via timer (not a print)
- `stop_recording()` adds minimum recording length check (`MIN_RECORDING_SECONDS = 0.8`) — accidental taps are silently discarded and status resets to `Ready`
- `process_voice()` drives status through `Searching...` → `Thinking...` → `Generating audio...` spinners
- `_play_audio()` sets `♪ Playing...` then calls `status.finish(elapsed)` on completion
- Cancelled or too-short recordings correctly signal `playback_done` so the voice loop continues

**Text mode**
- `--text` flag replaces `--dev` as the way to enter text mode (dev is now logging only)
- `_stream_text_response()` shows `Searching...` / `Thinking...` spinners before first token, clears status line cleanly when streaming begins
- Screen clears 1.5 s after a complete response and resets to `Ready`
- `quit` or Ctrl+C to exit; blank line no longer exits text mode

**Focus detection**
- Global pynput listener now ignores spacebar presses when the terminal is not the foreground window
- Works with both classic PowerShell and Windows Terminal (walks process ancestor tree via `CreateToolhelp32Snapshot` — no new dependencies)
- Non-Windows always returns `True`

**Other fixes**
- ElevenLabs model updated from deprecated `eleven_monolingual_v1` to `eleven_flash_v2_5`
- Standby mode removed — `run()` now branches directly to `_run_voice()` or `_run_text()`
- `_print_banner()`, `_print_active()`, `_go_standby()`, `_start_voice_loop()` removed
- `VOICE_TEXT` / `--voice` flag removed
- `re` and `time` moved to top-level imports; duplicate `import re` in search heuristics removed

---

## v1.1
Replaced all hand-rolled terminal status printing with `rich` animated spinners.

- Added `rich` as a dependency; `console = Console()` created at module level
- Deleted `status()` function — all call sites replaced with `console.status()` context managers
- `warm_up_ollama()`: spinner wraps the Ollama POST request; result prints after context exits
- `process_voice()`: three sequential spinners — Searching, Thinking, Generating audio
- `_handle_voice()`: heartbeat thread, `response_received` event, and `heartbeat_cleared` event removed entirely — `process_voice()` now owns its own spinners
- `_stream_text_response()`: heartbeat thread, `first_token_received` event, and `heartbeat_cleared` event removed; Searching wraps `web_search()`; Thinking uses `.start()`/`.stop()` to stay alive until the first streaming token arrives; Generating audio wraps `text_to_speech()` under `--voice` flag
- Removed all `\r` erase lines
- Added `rich` to `requirements.txt`

---

## v1.0 (branch: Friday-ver-2)
Major architectural refactor — Flask removed entirely.

- Replaced Flask server/client architecture with direct function calls
- `process_voice(wav_path)` replaces the `/process` route
- `process_text(user_query)` replaces the `/process_text` route
- `generate_response_stream()` is now a direct generator, replaces the `/process_text_stream` route
- `clear_memory()` is now a standalone function (no HTTP endpoint)
- Startup now pings Ollama directly via `check_ollama()` — replaces `/health` route
- Removed Flask, `werkzeug`, and all `SERVER_URL`/`SERVER_PORT` config
- `_send_voice()` renamed to `_handle_voice()` to reflect it no longer sends HTTP requests
- Startup exits with a clear message if Ollama is not reachable (rather than silently failing later)
- Marked `Post-1.0: Remove Flask server/client architecture` TODO as complete

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
