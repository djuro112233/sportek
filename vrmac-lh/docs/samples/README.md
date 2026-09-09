# Voice samples

> This directory is empty on purpose. **No recording of a real human voice is in this repository.**
> Everything the prototype uses today is either a synthetic tone or a text fixture, and both are
> labelled as such wherever a number derived from them is shown.

Two different things are needed, and they are not interchangeable.

## 1. A real host voice sample, for the pitch demo

**What it is for.** The 7-minute script (`demo.md`) has the host record ~30 seconds of Montenegrin
live in the wizard. Microphones fail: a browser blocks the permission, the room has no working input,
the laptop picks the wrong device. The documented fallback is to click *Upload* in step 2 of the
wizard and hand it a file from this directory. It is the demo's insurance policy, not a fixture — the
real speech-to-text provider transcribes it exactly as it would a live recording.

**How to record one.**

1. Ask a real host (or an ambassador speaking as themselves — say which in the file name), in
   Montenegrin, Latin script. Roughly 20–40 seconds is enough: about the length of the live take.
2. Content should be what a host actually says and nothing a model may invent — the kind of offer, the
   village, a room, the walk to the sea. It is fine, and useful, if the person mentions a price or a
   season *in passing*: the point of step 5 of the wizard is that those spoken words stay inside the
   description and the structured fields are still typed and confirmed by hand.
3. No names, no phone numbers, no e-mail addresses, no address. `services/extraction.py` strips a
   leading self-introduction, but do not rely on that in a public demo.
4. Any container the upload endpoint accepts: `.webm`, `.ogg`, `.oga`, `.wav`, `.m4a`, `.mp3`,
   `.mp4`, at most **25 MB** (`app/services/onboarding.py: AUDIO_EXTENSIONS`, `MAX_AUDIO_BYTES`). A
   phone voice memo is fine.
5. **Get consent in writing before recording**, covering the recording itself and its use in a public
   demonstration, and keep the signed note next to the file. The consent record the platform writes
   (`consent_records`, text version v1) covers a host publishing a *listing*; it does not cover
   recording a person for a pitch.

**Where to put it.** In this directory, with a name that says what it is, e.g.
`host-demo-cnr-01.m4a`, plus a short `.md` note beside it naming the speaker's role (not their name),
the date, the language and where the consent note is filed. Keep it small enough to live in the
repository; if it cannot, put a pointer here instead of the file.

The uploaded audio is deleted from the server as soon as it has been transcribed
(`KEEP_AUDIO=false`), so using the sample in the demo leaves nothing behind on the API host.

## 2. The five word-error-rate samples — **synthetic stand-ins, must be replaced**

`GET /api/kpi/quality` publishes the speech-to-text word error rate on a Montenegrin
**elderly-speaker** set. Elderly rural speakers are exactly the group voice-first onboarding is built
for, and exactly the group a Whisper model trained on broadcast speech gets wrong, so the figure is
worth measuring and worth being honest about.

Today it is not a measurement of a recogniser at all:

* `backend/seed_data/stt_eval_set.json` carries five entries with `is_synthetic: true` and
  `speaker_note: "synthetic stand-in for an elderly Montenegrin speaker — replace with a consented
  recording"`.
* The audio (`seed_data/stt_fixtures/elderly-cnr-0*.wav`) is a 2-second 220 Hz tone. Nobody speaks on
  it.
* With `STT_PROVIDER=fixture` the "recognised" text is read from the sidecar `.txt` next to it, which
  differs from the reference by a word or two so that the arithmetic is visibly non-zero.

So the number measures the *pipeline* — that the eval set loads, the WER is computed, the rows are
stored and the dashboard reads them — not the recogniser. A local run gives a mean WER of about 0.075
over the five samples; **that figure must never be quoted as speech-to-text quality.** Every row
carries `is_synthetic_sample = true` and the summary carries `is_synthetic`, so the label cannot
quietly disappear. `docs/decisions.md` §12 tracks this as an **ACTION**.

### Replacing them

No code changes — only files and flags.

1. Record **five** consented samples of elderly Montenegrin speakers, in the conditions the pilot will
   actually meet: a kitchen, a courtyard, wind, a dialect, a speaker who trails off. A clean studio
   recording would flatter the number and defeat the purpose.
2. Write down the **reference text** for each one by hand — what the person actually said, verbatim,
   with normal orthography. That transcript is the ground truth the WER is measured against; do not
   generate it with a recogniser.
3. Put the audio under `backend/seed_data/<audio_dir>/`. `audio_dir` is a field of
   `stt_eval_set.json` and defaults to `stt_fixtures`; a separate directory such as `stt_samples`
   keeps real recordings apart from the test fixtures, and only that one field has to change.
4. Update `stt_eval_set.json`: for each sample set `sample_id`, `audio_file`, `reference_text`, a
   `speaker_note` that describes the speaker without identifying them (age band, village, recording
   conditions), and `is_synthetic: false`. Set the document-level `is_synthetic` to `false` and
   replace the `_note`.
5. Delete the sidecar `.txt` files for those samples, so nothing can silently fall back to the fixture
   provider, and remove the tone WAVs.
6. Run the evaluation against a **real** provider:

   ```bash
   cd backend && . .venv/bin/activate
   STT_PROVIDER=faster-whisper python -m app.cli stt-eval     # or STT_PROVIDER=eu_api
   ```

   The summary and every stored row then report `is_synthetic: false`, and the dashboard drops the
   warning by itself.
7. Keep the consent notes for all five recordings with the project's paperwork, and record in this
   file where they are filed.

`tests/test_stt_eval.py` asserts the eval set has five samples, that each fixture transcript differs
from its reference and that the synthetic flag reaches the summary. After the replacement the flag
assertions have to be revisited together with the file.

## The fixture provider is for tests only

`STT_PROVIDER=fixture` (`app/providers/stt.py: FixtureSTT`) does not listen to the audio. It looks for
a transcript in `<uploaded file>.txt`, then `<stem>.txt`, then
`backend/seed_data/stt_fixtures/<stem>.txt`, and returns that text; it raises `FileNotFoundError` when
none exists, and logs a warning on every call:

```
STT fixture used for <file> — test/demo fallback only, not real speech-to-text
```

It exists so CI can exercise upload → save → transcribe → delete without downloading a model and
without recording anyone. **Never run a live demo with it**: it would show a transcript that has
nothing to do with what was said. The demo stack uses `STT_PROVIDER=faster-whisper` (local CPU, the
shipped default) or `eu_api`.

`seed_data/stt_fixtures/README.md` describes the fixture files themselves, including the standard-library
snippet that regenerates the tone WAVs.
