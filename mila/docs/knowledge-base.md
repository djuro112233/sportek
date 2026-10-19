# Knowledge base

Everything MILA says comes from a chunk of a document listed in `kb/manifest.yaml`. This
document describes the manifest, the licence rules, the review workflow, versioning, chunking,
the translation policy, the ingestion commands and how a clinic adds a national protocol.
The code is `backend/app/kb/` (`ingest.py`, `chunker.py`, `embed.py`) and the models are in
`backend/app/models/entities.py` (`Source`, `SourceVersion`, `Chunk`).

## 1. Manifest schema

`kb/manifest.yaml` is a mapping with a `version` (currently `1`) and a list of `documents`.
`load_manifest()` validates it into the `Manifest` / `ManifestDoc` pydantic models in
`backend/app/kb/ingest.py`; those models are the authoritative schema. Unknown fields are
rejected (`extra="forbid"`), duplicate ids are rejected, and only `id`, `title` and `file`
are required. The fields and their meaning:

| Field | Type | Default | Meaning |
|---|---|---|---|
| `id` | string, lowercase `[a-z0-9._-]`, 1 to 60 chars, starts with a letter or digit | required | Stable identifier, e.g. `who-fp-handbook-2022`. Becomes `Source.id` and the prefix of every chunk id. Never reuse an id for a different document. |
| `title` | string | required | Full title as printed on the document. Shown in citations. |
| `file` | relative path inside `kb/`, no `..` | required | `demo/en/<name>.md` for demo paraphrases, `downloads/<name>.pdf` for fetched documents (git-ignored), `national/<name>.pdf` for protocols supplied by the clinic. |
| `publisher` | string | `""` | Organisation that published it (WHO, a ministry, a professional society). |
| `year` | integer | none | Year of the edition. |
| `url` | string | `""` | Where the document is published; required for `download: true`; shown in citations. |
| `licence` | string | `""` | Exact licence name, e.g. `CC BY-NC-SA 3.0 IGO`, `Apache-2.0`, `Government publication, reuse permitted with attribution`. |
| `language` | `sr` / `bs` / `me` / `hr` / `en` | `en` | Language of the document; stored on every chunk. |
| `published_on` | ISO date string | `""` | Date of the edition; shown in citations as `date`. |
| `sha256` | hex string | none | Expected SHA-256 of the file. A downloaded file whose hash differs is rejected; set it for every public document so a silently changed PDF cannot enter the index. |
| `reviewed_by` | string | `""` | Name or role of the clinician who signed the review. **Non-empty means `review_status = reviewed`**; empty means `public_unreviewed`. |
| `reviewed_on` | ISO date string | `""` | Date of the sign-off. |
| `allowed_topics` | list of `TOPIC_CLASSES` | `[]` | Topic classes the document may answer. Retrieval can restrict by topic. |
| `download` | boolean | `false` | Allow `scripts/ingest_kb.py --download` to fetch the file from `url` when it is missing. Downloads land in `kb/downloads/` (or at `file` when it already starts with `downloads/`). |
| `notes` | string | `""` | Free text for maintainers (attribution text, scope restrictions, permission reference). |
| `status` | `blocked` or unset | unset | Forces `review_status = blocked`, which overrides `reviewed_by`. Used to pull a source during an incident (see `safety.md`). |

`review_status` is derived, not declared: `blocked` when `status: blocked`, otherwise
`reviewed` if and only if `reviewed_by` is non-empty, otherwise `public_unreviewed`. Source
metadata (title, licence, review status, reviewer) is refreshed from the manifest on every
ingestion run, even when the file is unchanged, so a manifest edit alone changes the status
after the next run. A source can also be blocked at runtime through
`POST /api/admin/sources/{id}/review`. Documents removed from the manifest are left in the
database untouched: block them first, then remove the entry.

Example:

```yaml
version: 1
documents:
  - id: demo-contraception-methods
    title: "Contraception methods: an overview (demo paraphrase)"
    publisher: MILA project
    year: 2026
    file: demo/en/contraception-methods.md
    licence: Apache-2.0
    language: en
    allowed_topics: [contraception]
    published_on: "2026-10-01"
    notes: "Project-authored paraphrase of WHO guidance. Not clinically reviewed. Demo mode only."

  - id: who-fp-handbook-2022
    title: "Family Planning: A Global Handbook for Providers (2022 edition)"
    publisher: World Health Organization and Johns Hopkins Bloomberg School of Public Health
    year: 2022
    url: "https://fphandbook.org"
    file: downloads/who-fp-handbook-2022.pdf
    download: true
    # sha256: added after the first verified download, before the entry is merged
    licence: CC BY-NC-SA 3.0 IGO
    language: en
    allowed_topics: [contraception, adolescent]
    published_on: "2022-11-01"
    notes: "Attribution per WHO terms; see docs/knowledge-base.md section 2."
```

## 2. Licence rules

- **Only public, licensed documents.** A document enters the manifest only if it is publicly
  available and its licence or terms permit reuse for this purpose. Scans of books, paywalled
  guidelines and documents shared "informally" are refused, however authoritative.
- **Content keeps its own licence.** The repository is Apache-2.0, but that covers code and
  our own text only. Knowledge-base documents are never relicensed; the manifest `licence`
  field and the citation shown to the user carry the original licence.
- **WHO publications** are generally licensed under CC BY-NC-SA 3.0 IGO. Using them means:
  - attribution: the citation names the title, WHO as publisher and the year, and links to the
    original (the `url` field);
  - non-commercial use only: MILA is a non-commercial service; a commercial deployment must
    not use these sources without a separate licence from WHO;
  - share-alike for adaptations: any adapted text we publish from these sources is released
    under the same licence;
  - WHO's standard adaptation and translation disclaimers apply to our outputs: an answer
    composed or translated from a WHO source is not a WHO product, WHO is not responsible for
    its content or accuracy, and the original English edition is the binding and authentic
    edition. MILA reflects this with `translated_note` on translated answers and with the
    citation that always links to the original.
  - the WHO name and emblem are never used to suggest endorsement.
- **Demo paraphrases** in `kb/demo/<language>/` are written by the project, licensed
  Apache-2.0, and never carry a `reviewed_by`, so they stay `public_unreviewed` and are served
  only in demo mode with the `demo_unreviewed` banner. Each file starts with an HTML comment
  naming the guidance it paraphrases. They are illustrative text for the pipeline,
  not clinical content.
- **National protocols** supplied by a ministry or a clinic enter the manifest only with a
  written statement of the terms under which they may be reproduced, recorded in `notes`.

## 3. Review workflow

```
 manifest entry (reviewed_by empty)  ──ingest──►  Source.review_status = public_unreviewed
          │                                                   │
          │ demo mode only, banner shown                      │
          ▼                                                   ▼
 clinic reviews the document and the 20 sample answers (docs/safety.md, section 6)
          │
          ▼
 reviewed_by + reviewed_on set (manifest or POST /api/admin/sources/{id}/review)
          │
          ▼
 Source.review_status = reviewed  ──►  usable with MILA_DEMO_MODE=false
```

- The clinician reviews the document itself (is it current, is it applicable in BA/ME, which
  topics it may answer) and the sample answers generated from it.
- Sign-off is a named person or role and a date. `ingest.py` derives
  `review_status = reviewed` if and only if `reviewed_by` is non-empty.
- A review is tied to a document version, but the code derives the status from
  `reviewed_by` alone: it does **not** clear the sign-off when a new file hash is ingested.
  The process rule therefore is: whoever replaces a file (new SHA-256) clears `reviewed_by`
  and `reviewed_on` in the same commit, and the clinic re-signs the new version. A pull
  request that changes a file without clearing the sign-off is rejected in review.
- `blocked` is reserved for incidents and is set by a maintainer, either as
  `status: blocked` in the manifest (survives re-ingestion) or through the admin endpoint.
  A blocked source is never retrieved, in any mode.

## 4. Versioning

- `version_hash` is the SHA-256 of the file. Each ingestion creates a `SourceVersion`
  (`version_hash`, `file_name`, `published_on`, `n_chunks`, `is_current`).
- Re-ingesting a file with the same hash is a no-op.
- A new hash marks older versions `is_current = False` and removes their chunks, so retrieval
  only ever sees the current version. Older `SourceVersion` rows remain as an audit trail.
- Chunk ids are `f"{source_id}:{version_hash[:8]}:{n}"`; citations show the short hash as
  `version` and `published_on` as `date`, so a reviewer can identify exactly which edition a
  sentence came from.

## 5. Chunking parameters

`chunk_pages(pages, max_tokens=400, overlap_tokens=40)` in `backend/app/kb/chunker.py`:

| Parameter | Value | Why |
|---|---|---|
| `max_tokens` | 400 (estimate via `estimate_tokens`, a word-and-punctuation heuristic, no tokenizer download) | Long enough for a complete recommendation with its context, short enough that a `[Sn]` citation points at one idea |
| `overlap_tokens` | 40 | Sentences at a boundary are present in both neighbours, so a citation is not lost at a cut |
| heading detection | numbered headings, ALL-CAPS lines, short title-case lines | `heading_path` is `"H1 > H2 > H3"` and is shown as the citation `section` |
| page extraction | `.pdf` via pypdf, one `PageText` per page; `.md` and `.txt` one page per section | Page numbers in citations come from the PDF page index |
| embeddings | `HashEmbedder` (256-dim, deterministic) by default; `BGEM3Embedder` (`BAAI/bge-m3`) with `MILA_EMBEDDER=bge_m3` | Tests never download models; multilingual retrieval in production |
| lexical index | BM25 over `tokenize(text)` (Cyrillic to Latin, diacritics stripped) | The same normalisation as the red-flag router and the lexical judge |

Chunk text is stored verbatim; nothing is paraphrased at ingestion.

## 6. Translation policy

- Most authoritative sources are in English; most users ask in sr/bs/me/hr. The generator
  answers in the user's language and sets `RawAnswer.translated = True` whenever the answer
  language differs from the language of all cited chunks.
- Translated answers show `translated_note` ("this answer was composed from an English source
  and checked sentence by sentence") and the citation to the original.
- **Verifier requirement.** The support judge must be able to compare a BCMS sentence with
  English evidence. The default `LexicalJudge` cannot do this reliably, so for a pilot with
  translated answers `MILA_JUDGE_PROVIDER=llm` (or an NLI judge) is required, and its
  agreement with human raters is measured first (`evaluation.md`, spot-check protocol).
- **Clinic review of translated answers.** At least five of the 20 reviewed sample answers
  are translated ones (`safety.md`, section 6). A translated answer the clinic marks
  `incorrect` is treated as a verifier failure, not only a content failure.
- The user interface and the consent texts are maintained by hand in all five languages
  (`backend/app/core/i18n.py`; `catalogue_completeness()` must be empty).
- Documents already available in a BCMS language (national protocols) are preferred for the
  topics they cover; `Retriever.search(..., lang=)` lets the pipeline favour them.

## 7. Ingestion commands

```bash
# ingest every manifest entry whose file is present (no network)
.venv/bin/python scripts/ingest_kb.py

# fetch public documents listed with a url, then ingest
.venv/bin/python scripts/ingest_kb.py --download

# re-ingest one source only
.venv/bin/python scripts/ingest_kb.py --only who-fp-handbook-2022

# use a different manifest / database
MILA_MANIFEST_PATH=/path/to/manifest.yaml MILA_DATABASE_URL=postgresql+psycopg://... \
  .venv/bin/python scripts/ingest_kb.py
```

`scripts/ingest_kb.py --help` lists the options as implemented; the script wraps
`ingest_manifest(db, settings, embedder=None, *, only=None, download=False)` and prints the
`IngestReport`: `ingested` (new or changed versions), `skipped_unchanged` (same hash),
`missing_files`, `downloaded`, `errors` (per id, including `not in manifest` for an unknown
`--only` id), `chunks_by_doc`, `chunks_added` and `chunks_current`. One bad document never
stops the run; it appears under `errors`. Run the script after changing the manifest, a file,
`MILA_EMBEDDER` or `MILA_EMBEDDING_DIM` (embeddings are stored per chunk, so changing the
embedder requires re-ingesting with a changed hash, or dropping the database).

In Docker Compose the `api` service runs the ingestion at start-up against the demo manifest.

## 8. Adding a national protocol after clinic approval

1. **Obtain** the document and the written permission to reproduce it. Save it as
   `kb/national/<id>.pdf` (the `kb/**/*.pdf` pattern is git-ignored; the file is distributed
   through the pilot deployment, not through git, unless its licence allows publication).
2. **Add** a manifest entry with `id`, `title`, `publisher`, `year`, `url` (if public),
   `file: national/<id>.pdf`, `sha256` of the file, `licence`, `language` (`bs`, `sr`, `me`
   or `hr`), `allowed_topics`, `published_on`, and `notes` with the permission reference.
   Leave `reviewed_by` empty.
3. **Ingest** with `scripts/ingest_kb.py --only <id>` and check the `IngestReport`: the id
   must be under `ingested`, not `errors` or `missing_files`; `chunks_by_doc[<id>]` should be
   plausible for the page count; and `heading_path` values should match the document's
   structure (open a few chunks through `GET /api/admin/sources` with the admin token).
4. **Generate** the sample answers for the topics the protocol covers in demo mode and run
   the clinic review (`safety.md`, section 6).
5. **Sign**: set `reviewed_by` and `reviewed_on` in the manifest (or through
   `POST /api/admin/sources/<id>/review`) and re-run the ingestion; the status becomes
   `reviewed`.
6. **Verify** with `MILA_DEMO_MODE=false` that questions on those topics are now answered
   from the protocol and that citations show the protocol's title, version hash and date.
7. **Record** the addition in the next measurement report (source list with versions) and in
   the pilot runbook.

When the ministry publishes a new edition, repeat from step 1 and clear `reviewed_by` and
`reviewed_on` in the same change: the old version's chunks are removed automatically on
ingestion of the new hash, but the sign-off is not, so the new version must be re-signed.
