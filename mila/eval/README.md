# Evaluation datasets

Everything `scripts/measure.py` reads lives here. All texts are written by the project team;
none comes from a user. Formats, metric definitions and the reporting rules are in
`docs/evaluation.md`; this file is the inventory.

| File | Rows | Used for | Owner |
|---|---|---|---|
| `inkb_questions.jsonl` | 30 (20 `sr`, 10 `en`) | Support rate, answered share, text latency, spot-check sampling | this folder |
| `offkb_questions.jsonl` | 100 (60 `sr`/`bs`/`me`, 40 `en`) | Refusal correctness, text latency | this folder |
| `redflag_inputs.jsonl` | 100 (12 or 13 per category; `sr` 42, `en` 23, `bs` 16, `hr` 11, `me` 8) | Red-flag recall (per category and variant) | safety datasets (written with `backend/tests/adversarial`) |
| `redflag_negatives.jsonl` | 60 near-misses | Red-flag false-positive rate | safety datasets |
| `wer_set/manifest.jsonl` | 50 | WER and voice latency; audio is not committed | `wer_set/README.md` |
| `usability_sessions.csv` | header + `EXAMPLE` row | Usability completion rate, times, comments | `usability_protocol.md` |
| `support_spot_check_template.csv` | 50 empty numbered rows | Human spot-check of the support judge | this folder |

## Schemas

### `inkb_questions.jsonl`

`{"id": "in-001", "lang": "sr", "script": "latin", "text": "...", "topic": "contraception", "source_ids": ["demo-contraception-methods"]}`

Questions the demo knowledge base (`kb/demo/en`) can answer: contraception, emergency
contraception, antenatal contacts, danger signs, nutrition, postnatal care, breastfeeding,
menstrual health, STI basics, adolescent rights, perinatal mental health. `topic` is one of
`TOPIC_CLASSES`; `source_ids` names the manifest entries expected among the citations and is
informational (not scored in v0.1). `measure.py` falls back to the older name
`onkb_questions.jsonl` when this file is absent.

### `redflag_inputs.jsonl` and `redflag_negatives.jsonl`

`{"id": "rf-001", "lang": "sr", "script": "latin", "text": "...", "category": "bleeding_pregnancy", "variant": "plain", "expected": "redflag"}`

Crafted red-flag inputs, 12 or 13 per `RED_FLAG_CATEGORIES` entry, with `variant` one of
`plain`, `typo`, `cyrillic`, `colloquial`, `dialect`, `no_diacritics`, `mixed`. `expected` is
the outcome (`redflag`); recall is scored against `category`. The negatives (`rfn-001` …) have
the same fields with `category` and `expected` set to `none` and are near misses on purpose
(period cramps, spotting between periods, a past fever, "what is pre-eclampsia").

### `offkb_questions.jsonl`

`{"id": "off-001", "lang": "sr", "script": "latin", "text": "...", "category": "off_domain", "expected": "withheld"}`

Questions MILA must withhold. Categories:

| Category | Rows | What it covers |
|---|---|---|
| `off_domain` | 17 | cooking, football, homework, law, everyday matters |
| `dosing_request` | 17 | asks for mg, number of tablets, which drug |
| `diagnosis_request` | 17 | "do I have X" from symptoms |
| `test_interpretation` | 16 | lab values, ultrasound measurements, smear results |
| `unsupported_in_kb` | 17 | health topics outside the demo KB: dental, orthopaedics, oncology, dermatology, ophthalmology, paediatric dosing |
| `manipulation` | 16 | prompt injection and role-play ("ignore your rules", "you are my doctor", fake system messages, appeals to authority) |

60 rows are in `sr`/`bs`/`me` (ekavian and ijekavian; 12 in Cyrillic), 40 in `en`. By
construction no row contains a red-flag situation; a red-flag outcome counts as incorrect.

### `support_spot_check_template.csv`

Columns `sentence_id, question_id, sentence, citation_chunk_id, judge_score, rater1_supported,
rater2_supported, notes`. `measure.py` writes a filled copy as
`reports/<date>_spotcheck.csv` (50 sentences, half judged supported, half unsupported);
two raters fill `rater1_supported` / `rater2_supported` with `supported`, `partially` or
`unsupported` following `docs/evaluation.md`, section 3.

### `usability_sessions.csv`

Columns `participant_id, group, task_completed, time_s, comment1, comment2, comment3,
consent_recorded`. The `EXAMPLE-P00` row documents the format and is skipped by
`measure.py`, as is every row with `consent_recorded=false`.

## Rules

- Keep ids unique and stable; add new rows at the end with the next id. The unit test
  `backend/tests/unit/test_measure.py` checks that every JSONL file here parses, that ids are
  unique and that the row counts above hold.
- Never paste a real user's question into these files, even anonymised.
- Changing a dataset changes the meaning of the numbers: bump the dataset note in the next
  report's "Caveats" and never edit a committed report.
