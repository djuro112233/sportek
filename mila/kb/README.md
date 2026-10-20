# MILA knowledge base

Everything MILA says is tied to a chunk of a document listed in `manifest.yaml`. No
document, no answer: the pipeline withholds and refers instead.

## Layout

```
kb/
  manifest.yaml     the list of sources (schema version 1, 27 entries; see the header comment for fields)
  demo/en/*.md      11 demo documents in English
  demo/sr/*.md      the same 11 topics in Serbian/Bosnian/Montenegrin (Latin script, ijekavian; language: sr)
  downloads/        WHO documents fetched on demand: 4 PDFs and 1 saved web page (git-ignored)
```

## Sources

* **WHO primary sources** (`who-*`, 5 entries): the Family planning global handbook (2022
  edition), the antenatal care recommendations (2016), the self-care interventions guideline
  (2022 revision), the postnatal care recommendations (2022) and the adolescent pregnancy
  fact sheet (a web page, saved as `.html`). They are licensed CC BY-NC-SA 3.0 IGO and are
  **not** stored in the repository. Their manifest `url`s are the WHO landing pages: set each
  one to the direct PDF link, then run `scripts/ingest_kb.py --download` on a machine with
  network access (it fails behind restrictive proxies), verify the licence text in the file
  and pin its `sha256` in the manifest. Until then they show up under `missing_files` in the
  ingest report. Until a clinician fills in `reviewed_by`, they are `public_unreviewed` and
  are used in demo mode only.
* **Demo documents** (`demo-*`, 22 entries): short, project-authored paraphrases of WHO
  guidance, eleven topics in two languages. Apache-2.0, not clinically reviewed, written for
  demo mode. They never contain doses, product names with quantities, diagnoses or test
  interpretation. Each file starts with an HTML comment that says so. This is the whole
  knowledge base of a fresh checkout and of the compose stack.

## Review status

| `reviewed_by` | `status`  | `Source.review_status` | used for answers              |
|---------------|-----------|------------------------|-------------------------------|
| empty         | (none)    | `public_unreviewed`    | only when `MILA_DEMO_MODE=true` |
| non-empty     | (none)    | `reviewed`             | always                        |
| any           | `blocked` | `blocked`              | never                         |

## Ingesting

```
cd mila
.venv/bin/python scripts/ingest_kb.py                      # everything that is present (make ingest)
.venv/bin/python scripts/ingest_kb.py --only demo-en-contraception-methods,demo-sr-contraception-methods
.venv/bin/python scripts/ingest_kb.py --download           # also fetch missing WHO files (network)
.venv/bin/python scripts/ingest_kb.py --database-url postgresql+psycopg://... --embedder bge_m3
.venv/bin/python scripts/ingest_kb.py --manifest /path/to/other/manifest.yaml -v
```

The script prints the `IngestReport` as JSON and exits 1 when a document errored or a
`--only` id is missing (see `docs/knowledge-base.md`, section 7).

Ingestion is versioned by the file's sha256: an unchanged file is a no-op, a changed file
creates a new `SourceVersion`, retires the old one and deletes its chunks. Chunk ids are
`<id>:<sha256[:8]>:<n>`.

## Adding a document

1. Put the file under `kb/` (or set `download: true` and a direct PDF `url`).
2. Add a manifest entry with a stable `id`, the real title, publisher, year, licence and
   `allowed_topics` (a subset of `TOPIC_CLASSES` in `app/core/types.py`).
3. Run the ingest script; check `chunks_by_doc` in the printed report.
4. Ask a clinician to review it; record `reviewed_by` and `reviewed_on`.
