# Reports

This folder is the **only** source of numbers for the UNICEF Femtech Ventures application form
and for any public claim about MILA. A number that is not in a committed file here does not
exist: not from a terminal, not from a notebook, not from a conversation.

## What goes here

| File | Written by | Content |
|---|---|---|
| `YYYY-MM-DD_measurement.md` | `scripts/measure.py` | Human-readable report: configuration, results tables, spot-check, incidents, caveats |
| `YYYY-MM-DD_measurement.json` | `scripts/measure.py` | The same numbers, machine-readable, with numerators and denominators |
| `YYYY-MM-DD_spotcheck.csv` | `scripts/measure.py`, then two human raters | 50 generator sentences with their cited chunk id and the judge score; rater columns filled by hand |
| `metrics_YYYY-MM-DD.json` / `.csv` | `scripts/export_metrics.py` | Public, k-anonymised aggregates from the `events` table |
| `junit-*.xml` | CI only, uploaded as artifacts | Never committed |

`YYYY-MM-DD` is the date passed with `--date` (default: the day the script ran), in UTC.

Reports so far: `2026-10-20_measurement.md` (+ `.json`, `_spotcheck.csv`), a **dry run with
mock providers** on the demo knowledge base. It proves the pipeline and the datasets run; its
numbers are not results (rule 3). The spot-check sheet's rater columns are still empty.

## Rules

1. **Only committed reports count.** The form quotes a value together with the file name and
   the git commit of the report. Reviewers can re-run `measure.py` at that commit.
2. **Reports are never edited after the fact.** A new run produces a new file with a new date.
   If a report is wrong, commit a short `YYYY-MM-DD_erratum.md` next to it that says what was
   wrong and which later report supersedes it.
3. **Dry runs are not results.** A report whose header says `DRY RUN (mock providers)` proves
   that the pipeline runs; its numbers describe mock behaviour and are never quoted. Every
   section lists the providers (`llm`, `judge`, `stt`, `tts`, `embedder`) it was computed with,
   so a reader can tell at a glance what was measured.
4. **Lexical-judge support rates are upper bounds** until the spot-check sheet for the same
   date has been labelled by two raters and the agreement is reported.
5. **Small samples are suppressed.** Groups with fewer than `MILA_K_ANONYMITY` (5)
   observations appear as counts only; the public metrics export never goes below k.
6. **No user content.** Reports contain dataset ids, counts, ratios, provider names, hashes and
   the anonymised usability comments collected under `eval/usability_protocol.md`. Nothing
   else from a session is ever written here.
7. A measurement report that is meant to be cited is committed together with its `.json`,
   the spot-check sheet, and the `eval/` datasets at the state used for the run.

## How to produce one

```bash
make install                 # once
make measure                 # dry run with mock providers: reports/<today>_measurement.md
MILA_LLM_PROVIDER=openai_compatible MILA_LLM_BASE_URL=http://localhost:8001/v1 \
MILA_JUDGE_PROVIDER=llm MILA_STT_PROVIDER=faster_whisper MILA_EMBEDDER=bge_m3 \
make measure                 # real providers: the header no longer says DRY RUN
```

Then read the "Caveats" section before committing, and commit the report with the message
`report: <date> measurement (<providers>)`.
