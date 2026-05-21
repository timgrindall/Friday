# Friday Updates - Session Summary

## Completed Tasks

### ✅ Updated README (DONE)
- Reflects single-file architecture (no separate server/client)
- Documents dev mode (`python friday.py -dev`)
- Explains all new configuration variables
- Added troubleshooting section
- Documented web search trigger keywords
- Added privacy notes

### ✅ Implemented Piper TTS (DONE)
- Added Piper as a higher-quality local TTS fallback
- Three-tier TTS system:
  1. **ElevenLabs** (best quality, requires API key + internet)
  2. **Piper** (good quality, fully local, auto-downloads voice model on first use)
  3. **pyttsx3** (basic fallback, no setup required)

### ✅ Updated TODO in friday.py
- Marked all tasks as complete

---

## Files Modified

### `friday.py` (v0.64)

**TTS Section Changes:**

1. **Added Piper configuration:**
   ```python
   PIPER_VOICE = os.getenv("PIPER_VOICE", "en_US-lessac-medium")
   ```

2. **New functions added:**
   - `can_use_piper()` — Checks if Piper is installed
   - `tts_piper(text)` — Synthesizes speech using Piper TTS
   - Updated `tts_elevenlabs()` — Falls back to Piper if ElevenLabs fails
   - Updated `text_to_speech()` — Implements three-tier fallback chain

3. **Smart fallback logic:**
   ```
   ElevenLabs (if API key + online)
        ↓
   Piper (if installed)
        ↓
   pyttsx3 (always available)
   ```

4. **Piper features:**
   - Auto-downloads voice models (~50-100MB) on first use
   - Supports 20+ English voices and multiple languages
   - Fully offline operation
   - No API key required
   - Better quality than pyttsx3

---

### `README.md` (Updated)

**New Sections:**

1. **Voice Output Quality Tiers**
   - Explains the three-tier TTS system
   - Documents each option's pros/cons
   - Lists recommended Piper voices
   - Shows how to customize voice in `.env`

2. **Configuration (Updated)**
   - Added `PIPER_VOICE` variable documentation
   - Clarified all optional API keys

3. **Stack (Updated)**
   - Shows TTS fallback chain: ElevenLabs → Piper → pyttsx3

**Maintained:**
- Usage instructions (Normal mode vs Dev mode)
- Configuration variables reference
- Hardware notes
- Privacy documentation
- Web search documentation
- Dev mode features
- Troubleshooting

---

### `requirements.txt` (Updated)

**Added:**
```
piper-tts
```

**Installation:**
```bash
pip install -r requirements.txt
```

First time Piper runs, it automatically downloads a voice model (~50-100MB). Subsequent runs are instant.

---

## Configuration Options

### `.env` File (All Optional)

```bash
# ElevenLabs (best quality, requires API key)
ELEVENLABS_API_KEY=sk_your_key_here
ELEVENLABS_VOICE_ID=JBFqnCBsd6RMkjVDRZzb

# Piper voice selection (fully local, auto-downloads on first use)
PIPER_VOICE=en_US-lessac-medium

# Web search (optional)
SERPAPI_KEY=your_key_here
```

### Recommended Piper Voices

| Voice | Characteristics |
|-------|-----------------|
| `en_US-lessac-medium` (default) | Very clear, professional |
| `en_US-libritts_r-medium` | Natural, warm tone |
| `en_US-ryan-high` | Bright, energetic |
| `en_US-ljspeech-high` | Classic, widely tested |

See [Piper voices](https://github.com/rhasspy/piper/blob/master/VOICES.md) for complete list including other languages.

---

## Behavior Changes

### TTS Fallback Priority

**Before:**
- ElevenLabs → pyttsx3

**After:**
- ElevenLabs → Piper → pyttsx3

### Dev Mode Output

When using Piper, you'll see in dev mode:
```
[TTS] Piper (en_US-lessac-medium, 12345 bytes)
```

When Piper downloads its voice model for the first time:
```
[TTS] Piper model not found, downloading...
```

---

## Installation & First Run

### For New Users

```bash
git clone https://github.com/timgrindall/Friday.git
cd Friday
pip install -r requirements.txt
python friday.py
```

First time Piper runs:
- Automatically detects missing voice model
- Downloads to `~/.local/share/piper/voices/`
- Takes 1-2 minutes (one-time only)
- Subsequent runs are instant

### To Use ElevenLabs (Optional)

Add API key to `.env`:
```
ELEVENLABS_API_KEY=sk_your_key_here
```

Friday will use ElevenLabs automatically (best quality when available).

### To Customize Piper Voice (Optional)

Add to `.env`:
```
PIPER_VOICE=en_US-libritts_r-medium
```

---

## Testing the Changes

### Test ElevenLabs (if configured)
```bash
# Should use ElevenLabs
python friday.py -dev
# Type: "hello world"
# Check logs: [TTS] ElevenLabs
```

### Test Piper
```bash
# Should use Piper if ElevenLabs unavailable
python friday.py -dev
# Unset ELEVENLABS_API_KEY in .env
# Type: "hello world"
# Check logs: [TTS] Piper
```

### Test pyttsx3 Fallback
```bash
# Simulate Piper not installed
python -c "import sys; sys.modules['piper'] = None"
python friday.py -dev
# Check logs: [TTS] pyttsx3
```

---

## Version

**Friday v0.65** now includes:
- ✅ Single-file architecture with integrated Flask server
- ✅ Dev mode with streaming responses and mid-stream cutoff
- ✅ Smart web search triggering with keyword matching
- ✅ Configurable conversation history (voice vs text modes)
- ✅ **Three-tier TTS system (ElevenLabs → Piper → pyttsx3)**
- ✅ Updated documentation

**All TODO items completed.**

---

## Next Steps (Optional Future Work)

- Add voice activity detection (VAD) to auto-stop recording
- Support for custom Piper models
- Ability to pre-download Piper voices offline
- Multi-language support (Piper has 30+ languages)
- Custom system prompts per mode
- Response caching for common queries
