# Scripts

Operational scripts, run from the repository root with the project venv
(`.venv/bin/python scripts/<name>.py --help`). They import the backend lazily by adding
`backend/` to `sys.path`, so they need no installation step beyond `pip install -e '.[dev]'`.
Settings come from `MILA_*` environment variables or `.env`, exactly as for the API.

| Script | Purpose | Make target |
|---|---|---|
| `ingest_kb.py` | Load `kb/manifest.yaml` into the database (`--manifest`, `--only id,id`, `--download`, `--database-url`, `--embedder hash\|bge_m3`, `-v`); prints the `IngestReport` as JSON, exit 1 on errors; `--download` fetches documents marked `download: true` and needs network access | `make ingest` |
| `make_demo_data.py` | Seed referral points, ingest the demo KB and create synthetic consented sessions with events so `/api/metrics/public` shows something; refuses to run with `MILA_APP_ENV=prod` | `make demo-data` |
| `measure.py` | Run the evaluation datasets under `eval/` and write `reports/<date>_measurement.md` + `.json` (+ `<date>_spotcheck.csv`) | `make measure` |
| `export_metrics.py` | Dump the k-anonymised public metrics to `reports/metrics_<date>.json` and a per-day `.csv` | `make export-metrics` |

## `measure.py`

```
.venv/bin/python scripts/measure.py [--date YYYY-MM-DD] [--out reports/<date>_measurement.md]
                                    [--skip wer,usability,latency_voice] [--limit N]
                                    [--database-url URL] [--keep-session]
```

- Builds `Settings(demo_mode=True)`; providers default to the mocks unless `MILA_*` variables
  say otherwise. The database is `--database-url`, else `MILA_DATABASE_URL`, else a local
  `.measure.db` SQLite file (removed by `make clean`). The report header reads **DRY RUN (mock
  providers)** whenever any provider is a mock (`mock` LLM/STT/TTS or the `hash` embedder), and
  every section names the LLM, judge, STT, TTS and embedder it used.
- Ingests the demo knowledge base if the database has no chunks, seeds referral points, and
  creates one consented evaluation session (deleted at the end unless `--keep-session`).
- Sections: support rate over `eval/inkb_questions.jsonl` (sentence level, per language,
  answer-level mean, answered share) plus the spot-check sheet with empty rater columns;
  refusal correctness over `eval/offkb_questions.jsonl` (overall, per category, per language,
  incorrect ids listed); red-flag recall per category and variant plus the false-positive rate
  over `eval/redflag_negatives.jsonl`, both via `RedFlagRouter.check`; text and voice latency
  (median, nearest-rank p90; voice uses a synthetic silent WAV while no consented recordings
  exist); WER over `eval/wer_set/manifest.jsonl` when consented recordings exist; usability
  from `eval/usability_sessions.csv` (EXAMPLE rows and unconsented rows ignored).
- The "Spot-check" and "Incidents" sections are placeholders the maintainers fill by hand
  (rater agreement once the sheet is labelled; incident counts from the log).
- Sections that cannot run say so (`not measured (...)`) instead of failing the whole run;
  the exit code is 0 once the report is written.
- `--limit N` truncates every dataset to its first N rows (for a quick smoke run); the report
  says so in "Caveats".
- Pure metric functions (`support_rate`, `refusal_correctness`, `redflag_recall`,
  `redflag_false_positive_rate`, `latency_stats`, `wer`, `usability_summary`,
  `render_report`, `write_report`, `load_jsonl`) have no backend imports and are unit-tested in
  `backend/tests/unit/test_measure.py`.

Only a committed report under `reports/` counts (see `reports/README.md`).

## `make_demo_data.py`

```
.venv/bin/python scripts/make_demo_data.py [--sessions 40] [--days 14] [--seed 42] [--database-url URL]
```

Deterministic for a given seed. Every synthetic event carries `payload == {"synthetic": true}`
and no event ever contains question text (the `Event` model has no such column). Outcomes,
topic classes, latencies, input modes and support ratios follow realistic ratios (about 72 %
answered, 21 % withheld, 7 % red flag; 55 % text, 45 % voice). The script exits with code 2
before touching the database when `MILA_APP_ENV=prod`.

## `export_metrics.py`

```
.venv/bin/python scripts/export_metrics.py [--date YYYY-MM-DD] [--out-dir reports] [--days N] [--database-url URL]
```

Calls `app.api.metrics.compute_public_metrics` (or the first `compute_*` callable in that
module) with the arguments its signature declares, writes the result as JSON, and writes a
per-day CSV computed from the `events` table with every count below `MILA_K_ANONYMITY`
suppressed and days below k dropped.

## Conventions

- Scripts never print or store user text; log lines carry ids and counts only.
- `ruff check scripts` and `python -m py_compile scripts/*.py` run in CI.
- Add a new script here with its make target and a one-line purpose.
