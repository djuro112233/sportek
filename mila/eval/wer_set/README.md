# WER set: 50 consented utterances for speech-recognition evaluation

This folder holds the reference texts (`manifest.jsonl`) for the word-error-rate measurement
described in `docs/evaluation.md`, section 1.5. The audio files (`audio/u001.wav` ...
`audio/u050.wav`) are **not committed**: they are recorded by consenting adult volunteers and
kept outside git. Until recordings exist, `scripts/measure.py` reports WER as
"not measured (no consented recordings yet)".

## What is recorded

Each volunteer reads a subset of the 50 team-written questions in `manifest.jsonl`, in her own
natural pronunciation. The texts are everyday health questions written by the project team.
They contain **no personal content**: no names, no dates of birth, no places of residence, no
real medical history. Volunteers read the text as written; they do not add anything about
themselves.

## Consent (read aloud and signed before recording)

> I agree to record my voice reading questions written by the MILA project. The recordings are
> used only to measure how well speech recognition understands our languages and dialects. They
> are stored on an encrypted project device, never uploaded to a third-party service, never used
> to train a voice model, and never published. They are linked to a speaker code, not to my name;
> the list that links codes to names is kept by the clinic and destroyed at the end of the pilot.
> I can withdraw at any time by contacting the clinic, and my recordings are then deleted.
> Participation is voluntary and unpaid. I am 18 or older.

The signed form stays with the clinic. `consent_recorded` in the manifest is set to `true`
only after the form is on file; `measure.py` ignores every utterance where it is `false`.

Volunteers under 18 are not recorded.

## Recording instructions

- Format: WAV, 16 kHz sample rate, mono, 16-bit PCM. `ffmpeg -i in.m4a -ac 1 -ar 16000 -sample_fmt s16 audio/u001.wav`.
- One utterance per file, named exactly as the `audio` field in the manifest.
- Quiet room, phone or laptop microphone at 20 to 30 cm, no music or TV; a little background
  noise (street, another room) is acceptable and realistic.
- Start the recording, wait one second, read the sentence once at normal speed, wait one second,
  stop. Do not re-read or correct yourself inside the file; record again instead.
- Keep the wording of the reference. If a volunteer naturally says the sentence slightly
  differently (for example "đe" instead of "gdje"), update the `reference` field to what was
  actually said, so WER measures recognition and not dialect normalisation.
- Fill in `speaker` (the speaker code, e.g. `S03`) and `recorded_on` (ISO date), and set
  `consent_recorded` to `true`.

## Dialect and accent coverage

The 50 utterances are split 20 `sr` (ekavian), 15 `bs` (ijekavian) and 15 `me` (ijekavian,
including Montenegrin colloquial forms such as "đe"). When recruiting speakers, aim to cover:

- Serbian ekavian from Serbia (Belgrade and Vojvodina) and from the Republika Srpska;
- Bosnian ijekavian from Sarajevo, Tuzla and Mostar;
- Montenegrin ijekavian from Podgorica and the coast, and the northern (Bijelo Polje, Pljevlja) speech;
- at least one speaker of a Romani background and one speaker of Albanian mother tongue who
  uses Montenegrin or Serbian daily, because both groups are part of the target population;
- a spread of ages (18 to 25, 26 to 40, over 40) and at least one speaker with a cold or a hoarse voice.

Each speaker records at most 10 utterances so that no single voice dominates the set.

## Manifest fields

| Field | Meaning |
|---|---|
| `id` | `wer-001` ... `wer-050` |
| `audio` | Path relative to this folder, e.g. `audio/u001.wav` |
| `lang` | `sr`, `bs` or `me` |
| `script` | Script of the reference text (`latin`); WER is computed after `normalize_text`, so Cyrillic references are allowed |
| `dialect` | `ekavian` or `ijekavian` |
| `reference` | Exact text read by the speaker |
| `consent_recorded` | `true` only when the signed form is on file |
| `speaker` | Speaker code (empty until recorded) |
| `recorded_on` | ISO date (empty until recorded) |

## Deleting recordings

A volunteer who withdraws has every file listed under her speaker code deleted with
`shred` or an equivalent, and the manifest rows reset (`consent_recorded: false`, `speaker: ""`).
