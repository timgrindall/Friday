import sounddevice as sd
import numpy as np

devices = sd.query_devices()
for i, d in enumerate(devices):
    if d['max_input_channels'] > 0:
        for rate in [16000, 44100, 48000]:
            try:
                audio = sd.rec(int(1 * rate), samplerate=rate, channels=1, dtype='int16', device=i)
                sd.wait()
                amp = int(np.max(np.abs(audio)))
                print(f"Device {i} @ {rate}Hz: max amplitude {amp} -- {d['name']}")
                break
            except Exception as e:
                print(f"Device {i} @ {rate}Hz: FAILED -- {d['name']}")
