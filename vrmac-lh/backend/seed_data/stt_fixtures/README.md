# STT fixtures (tests and offline demo only)

Used by `STT_PROVIDER=fixture` (`app/providers/stt.py: FixtureSTT`): the transcript is read from
`<stem>.txt` next to the uploaded file's stem. **Never use the fixture provider for a live demo** — it
does not listen to the audio at all.

| File | What it is |
|---|---|
| `host-sample-cnr.txt` | ~120-word transcript in Montenegrin (Latin script) of a **fictional** host describing an apartment in Donja Lastva (2 rooms, up to 4 guests, 45–70 € per night, May–October, ground floor without steps, 300 m from the sea, view of the bay). |
| `host-sample-en.txt` | The same fictional offer described in English. |
| `host-sample-cnr.wav` | **Synthetic upload fixture, NOT a real voice**: 2 seconds, 16 kHz, mono, 16-bit PCM, a quiet 220 Hz tone with 50 ms fades. It exists only so the multipart upload → save → transcribe → delete path can be exercised without recording anyone. With the fixture provider its stem resolves to `host-sample-cnr.txt`. |

Regenerate the WAV (pure standard library):

```python
import math, struct, wave
rate, seconds, freq, amp = 16000, 2.0, 220.0, 0.15
n = int(rate * seconds); frames = bytearray()
for i in range(n):
    t = i / rate
    fade = min(1.0, t / 0.05, (seconds - t) / 0.05)
    frames += struct.pack("<h", int(32767 * amp * fade * math.sin(2 * math.pi * freq * t)))
with wave.open("host-sample-cnr.wav", "wb") as w:
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate); w.writeframes(bytes(frames))
```

Nothing here is personal data: no names, no real providers, no recorded speech. A real host voice sample
for the pitch demo must be recorded by the team (see `docs/samples/README.md`).
