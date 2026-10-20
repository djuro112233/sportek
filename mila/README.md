# MILA

**Open-source, voice-first information and referral assistant for reproductive and maternal
health** in Serbian, Bosnian, Montenegrin, Croatian and English (`sr`, `bs`, `me`, `hr`, `en`),
with Latin and Cyrillic output. Built as a prototype for a UNICEF Femtech Ventures application.

> **NOT MEDICAL ADVICE**
>
> MILA gives **general information** from approved, cited sources and **points you to a person
> who can help**. It never diagnoses, never recommends medicines or doses, and never interprets
> test results. If you think you are having an emergency, call your local emergency number now
> (ambulance: 124 in Bosnia and Herzegovina and in Montenegro). Every answer MILA gives carries
> this disclaimer and a referral.

Version: **0.1.0** (work in progress toward the `v0.1.0-unicef` tag). Licence: Apache-2.0.

---

## What MILA is, and what it is not

| MILA **is**                                                                          | MILA **is not**                                                     |
|--------------------------------------------------------------------------------------|---------------------------------------------------------------------|
| An information desk: short answers composed only from sentences supported by an approved, versioned source, each sentence cited | A doctor, a nurse, a midwife or a triage tool                       |
| A referral desk: every answer, refusal or red-flag response ends with a place or a number to contact | A chatbot that "does its best" when it has no reliable source        |
| Voice-first: ask by speaking, hear the answer read back, confirm what was heard      | A diagnosis, dosing or test-interpretation service                   |
| Safe by default for minors: no age stored, adapted wording, protection services shown | A service that keeps your questions, voice or identity               |
| Open source, self-hostable, no third-party data retention                            | A replacement for emergency services                                 |

The whole product reduces to one rule: **either every sentence is tied to a chunk of an
approved source, or the answer is withheld and replaced with a referral.** Everything in this
repository exists to make that rule enforceable and measurable.

## Who it is for

- Women and girls in Bosnia and Herzegovina and Montenegro (first pilot regions, `BA` and `ME`)
  who want plain-language answers about contraception, pregnancy, antenatal and postnatal care,
  menstruation, sexually transmitted infections and mental health in their own language, by
  voice, without creating an account.
- Users who may be under 18: MILA asks only "are you under 18?" (never an age), adapts its
  wording, and shows child-protection and helpline numbers where relevant.
- Clinics and NGOs that want to publish reviewed, cited information and a verified list of
  referral points without running a call centre.
- Public-health teams that need a measurable, auditable assistant: every decision to answer or
  withhold is recorded with its reasons and gate version.

## 2-minute setup

Both paths start with a clone:

```bash
git clone <this repository> && cd mila
```

### Path A: Docker Compose

```bash
docker compose up --build            # starts db (Postgres + pgvector), redis, api, web
```

- Web UI: <http://localhost:3000>
- API health: <http://localhost:8000/api/health> (returns `{"status": "ok", "demo_mode": true, "version": "0.1.0"}`)
- API docs (non-production only): <http://localhost:8000/api/docs>

Both ports are published on `127.0.0.1` only. The `api` service ingests the demo manifest
before it starts serving. The default stack uses deterministic local providers (mock LLM, hash
embedder, lexical judge, mock STT/TTS) so it needs no GPU, no model download and no network.
Real providers are opt-in through `MILA_*` environment variables (see
[Provider configuration](#provider-configuration)); copy `.env.example` to `.env` to set them.
Optional profiles: `--profile local-llm` (vLLM on an NVIDIA GPU) and
`--profile ingest` (one-shot download of the WHO documents, see
[Knowledge base](#knowledge-base-review-status-and-demo-mode)). The services and their hardening
are described in [docs/architecture.md, Deployment](docs/architecture.md#deployment).

### Path B: local development

Requires Python 3.11+ and Node 20+ (`npm test` needs Node 22.18+).

```bash
# backend
uv venv --seed .venv                 # or: python3.11 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python scripts/ingest_kb.py          # loads kb/manifest.yaml into ./mila.db (SQLite)
.venv/bin/uvicorn --app-dir backend 'app.main:create_app' --factory --port 8000

# web (second terminal)
cd web && npm install && npm run dev
```

`uv venv` without `--seed` creates an environment without `pip`; in that case use
`uv pip install -e '.[dev]'` instead of the `pip` line (`make venv install` does the same with
`python3.11`). The ingest step prints an `IngestReport`: the 22 demo documents land under
`ingested` and the five WHO entries under `missing_files` until you download them (they are not
in the repository, see [Knowledge base](#knowledge-base-review-status-and-demo-mode)). Then
`curl http://localhost:8000/api/health` should answer as in Path A. Optional extras:
`.[voice]` (faster-whisper, Piper), `.[embed]` (BGE-M3 via sentence-transformers),
`.[postgres]`, `.[redis]`.

## Architecture

```
 audio ──► STT ──► text ──► red-flag router ──► (flag) ──► referral response
                           │
                           ▼ (no flag)
                    scope guard (dose / diagnosis / test-result / manipulation request)
                           │                               ──► (hit) ──► refusal + referral
                           ▼ (in scope)
                    hybrid retrieval (vector + BM25, reviewed/demo filter)
                           │
                           ▼
                    generation (open-weight LLM, [S1] markers)
                           │
                           ▼
                    verifier (sentence ↔ cited chunk support)
                           │
                           ▼
                    question relevance (does the cited evidence cover the question?)
                           │
                           ▼
                    validation gate (approve / withhold + reasons, versioned)
                           │
                           ▼
                    answer + citations + referral + disclaimer (+ TTS)
                           │
                           ▼
                    event (aggregate only, pseudonymous)
```

The binding module contracts (types, function signatures, API table) are in
[docs/architecture.md](docs/architecture.md). Every external capability (LLM, embeddings,
support judge, STT, TTS) sits behind a `Protocol` with a deterministic local implementation
that is used by default and in tests. Any exception in a stage fails closed: the answer is
withheld with gate reason `pipeline_error` and only the exception class name is recorded.

## Repository layout

```
mila/
├── backend/
│   ├── app/
│   │   ├── api/          # FastAPI routers: consent (+ session), ask, transcribe, speak (+ audio),
│   │   │                 # referral, metrics, admin; deps.py (consent and admin checks)
│   │   ├── core/         # i18n, consent_texts, redflags (+ redflag_rules), scope, retrieval,
│   │   │                 # generation, verifier, relevance, gate, referral, privacy, events,
│   │   │                 # container (provider wiring), pipeline, types
│   │   ├── kb/           # embed, chunker, ingest
│   │   ├── models/       # SQLAlchemy models (sources, chunks, sessions, events, gate records, ...)
│   │   ├── services/     # llm, stt, tts providers (mock + optional real)
│   │   ├── config.py     # Settings (MILA_* environment variables)
│   │   ├── db.py         # engine / session factory
│   │   └── main.py       # application factory `create_app`
│   ├── tests/            # unit/, integration/, adversarial/ (+ conftest.py)
│   └── Dockerfile        # API image (python:3.11-slim, non-root)
├── web/                  # Next.js 14 (TypeScript) voice-first UI, own README and Dockerfile
├── kb/                   # manifest.yaml, demo/{en,sr}/ paraphrases, downloads/ (git-ignored)
├── eval/                 # evaluation datasets (JSONL/CSV, see docs/evaluation.md)
├── scripts/              # ingest_kb.py, measure.py, make_demo_data.py, export_metrics.py
├── reports/              # committed measurement reports (the only source of numbers)
├── docs/                 # architecture, safety, data protection, knowledge base, evaluation
├── .github/workflows/    # ci.yml: lint, tests on 3.11/3.12, test-count floor, web build, compose check
├── docker-compose.yml    # db, redis, api, web (+ local-llm and ingest profiles)
├── .env.example          # every MILA_* variable with its default
├── Makefile              # venv, install, test, lint, ingest, demo-data, measure, up, down
├── pyproject.toml        # package, pytest and ruff configuration
└── LICENSE               # Apache-2.0
```

All backend imports are rooted at `backend/` (`from app.core.gate import ValidationGate`;
pytest sets `pythonpath = backend`, the scripts add it to `sys.path` themselves).

## Provider configuration

Settings are read from environment variables prefixed `MILA_` (or a `.env` file in the working
directory). Defaults are safe for local use and tests; **nothing in the defaults sends data to a
third party.** Source of truth: `backend/app/config.py`.

| Variable | Default | Meaning |
|---|---|---|
| `MILA_APP_ENV` | `dev` | `dev`, `test` or `prod`. In `prod` the API docs are disabled and logging is INFO. |
| `MILA_DEMO_MODE` | `true` | Allow `public_unreviewed` sources in answers (flagged in the UI). Set `false` for a clinical pilot. |
| `MILA_DATABASE_URL` | `sqlite:///./mila.db` | SQLAlchemy URL. Postgres with pgvector in compose. |
| `MILA_LLM_PROVIDER` | `mock` | `mock` (extractive, deterministic) or `openai_compatible` (vLLM, llama.cpp, TGI and similar). |
| `MILA_LLM_BASE_URL` | `http://localhost:8001/v1` | OpenAI-compatible endpoint. Requests are sent with `store=false`. |
| `MILA_LLM_API_KEY` | empty | Bearer token for the endpoint, if any. Never committed. |
| `MILA_LLM_MODEL` | `mistralai/Mistral-7B-Instruct-v0.3` | Open-weight model name passed to the endpoint. |
| `MILA_LLM_TIMEOUT_S` | `60.0` | Request timeout. |
| `MILA_EMBEDDER` | `hash` | `hash` (deterministic) or `bge_m3` (`BAAI/bge-m3`, multilingual). |
| `MILA_EMBEDDING_DIM` | `256` | Dimension of the hash embedder. |
| `MILA_JUDGE_PROVIDER` | `lexical` | Sentence-support judge: `lexical` (token overlap) or `llm` (uses the configured LLM). |
| `MILA_STT_PROVIDER` | `mock` | `mock` or `faster_whisper`. |
| `MILA_STT_MODEL` | `large-v3` | Whisper model size for faster-whisper. |
| `MILA_TTS_PROVIDER` | `mock` | `mock` or `piper`. |
| `MILA_PIPER_VOICE_DIR` | `<repo>/models/piper` | Directory with Piper voice files. |
| `MILA_RETRIEVAL_TOP_K` | `8` | Chunks passed to generation. |
| `MILA_GATE_MIN_SUPPORT_RATIO` | `0.6` | Gate withholds below this share of supported sentences. |
| `MILA_GATE_MIN_CONFIDENCE` | `0.35` | Gate withholds below this confidence. |
| `MILA_GATE_MIN_RELEVANCE` | `0.3` | Gate withholds when the cited evidence covers less of the question than this (`low_relevance`). |
| `MILA_GATE_MIN_SENTENCE_RELEVANCE` | `0.1` | A supported sentence covering less of the question than this is dropped as `off_topic`. |
| `MILA_RELEVANCE_UNKNOWN_TERM_PENALTY` | `0.85` | Relevance multiplier when the question contains a term the knowledge base never uses. |
| `MILA_VERIFIER_SUPPORT_THRESHOLD` | `0.5` | Judge score at or above which a sentence counts as supported. |
| `MILA_REDFLAG_CLASSIFIER_THRESHOLD` | `0.85` | Score above which the (secondary) classifier flags; rules always win. |
| `MILA_K_ANONYMITY` | `5` | Public metrics rows with a count below this are suppressed. |
| `MILA_AUDIO_TMP_DIR` | `<repo>/.audio_tmp` | Where uploads live for the seconds between upload and transcription. |
| `MILA_ADMIN_TOKEN` | empty | `X-Admin-Token` for `/api/admin/*`. Empty disables the admin endpoints (404). |
| `MILA_CONSENT_VERSION` | `2026-10-01` | Version string recorded with every consent; change it to force re-consent. |
| `MILA_DEFAULT_REGION` | `BA` | Referral region when the session has none (`BA`, `ME`). |
| `MILA_RATE_LIMIT_PER_MINUTE` | `60` | Sliding-window limit per session id (never per IP). |
| `MILA_KB_DIR` | `<repo>/kb` | Knowledge-base directory. |
| `MILA_MANIFEST_PATH` | `<repo>/kb/manifest.yaml` | Source manifest. |
| `MILA_CORS_ORIGINS` | `["http://localhost:3000"]` | JSON list of allowed browser origins. |

## Knowledge base, review status and demo mode

Sources are declared in `kb/manifest.yaml`, ingested by `scripts/ingest_kb.py`, chunked
(about 400 tokens, 40 overlap, with a heading path), embedded and versioned by the SHA-256 of
the file. Each source carries a review status:

| Status | Meaning | Used for answers? |
|---|---|---|
| `reviewed` | A named clinician signed off (`reviewed_by` set) | Yes |
| `public_unreviewed` | Public, licensed document not yet reviewed | Only when `MILA_DEMO_MODE=true`; the answer is flagged "demo: unreviewed sources" |
| `blocked` | Pulled by the maintainers or the clinic | Never |

The manifest currently lists 27 documents: 22 demo paraphrases under `kb/demo/` (11 topics, in
English and in Serbian/Bosnian/Montenegrin Latin script) and 5 WHO publications (`who-*`,
`download: true`) that are **not in the repository**. The demo paraphrases were written for this
prototype (Apache-2.0) so that the full pipeline can be demonstrated and tested without
downloading anything. **They are not clinically reviewed** and are only ever served in demo
mode. The WHO documents are fetched with `scripts/ingest_kb.py --download` on your own
machine; the manifest URLs are WHO landing pages, so set each `url` to the direct PDF link
first, and expect the download to fail behind restrictive proxies. Details, licence rules and
the clinic review workflow: [docs/knowledge-base.md](docs/knowledge-base.md).

## Safety design

1. **Red flags first.** Before retrieval, a rules-first router (keyword and phrase lists for
   sr/bs/me/hr/en in both scripts, typo-tolerant, with a small character n-gram classifier as a
   second opinion that rules always override) checks for bleeding in pregnancy, severe
   abdominal pain, fever in pregnancy, pre-eclampsia signs, reduced fetal movement, suicidal
   ideation, violence or coercion, and sexual contact between a minor and an adult. A flag
   short-circuits to an emergency or support referral; the pipeline never generates text for it.
2. **Scope guard.** A question that *asks* for a dose or a medicine, a diagnosis, a test-result
   interpretation, or that tries to change the rules ("ignore your instructions", "you are my
   doctor") is refused before retrieval with a specific message and a referral (gate reasons
   `medication_or_dose`, `diagnosis_request`, `test_interpretation`, `manipulation`).
3. **Approved sources only.** Retrieval is filtered by review status; `blocked` chunks are never
   returned and `public_unreviewed` ones only in demo mode.
4. **Constrained generation.** The system prompt forbids diagnosis, dosing and test
   interpretation and requires a `[Sn]` citation marker on every sentence.
5. **Sentence-level verification.** Each sentence is checked against the chunk it cites; a
   sentence without a marker, with a marker that maps to nothing, or with low support is removed.
6. **Validation gate.** A versioned gate approves or withholds the whole answer with stable
   reasons (`no_sentences`, `no_citations`, `medication_or_dose`, `low_support_ratio`,
   `low_confidence`, `unreviewed_source_outside_demo`, `low_relevance`; the pipeline adds the
   scope reasons above and `pipeline_error` when a stage raised). Any medication quantity, dosing
   imperative or regimen withholds the entire answer, not just the sentence; `low_relevance`
   withholds well-cited sentences that do not cover the question (knee pain answered with
   pregnancy pain).
7. **Referral and disclaimer always.** Every response, answered or not, ends with a localised
   disclaimer and a referral block; minors get the minors' consent text, child-protection
   services in the referral block and a note in the generation prompt (see docs/safety.md, C7).

Full threat model, control mapping and incident process: [docs/safety.md](docs/safety.md).

## Privacy

1. **Nothing before consent.** `/api/ask` and `/api/transcribe` return 403 until a session has
   accepted a versioned, plain-language consent text (shown and spoken).
2. **Pseudonymous sessions.** The session id is a random 192-bit token. There are no accounts,
   no cookies for tracking, no IP addresses and no device identifiers anywhere in the data model.
3. **Aggregate-only events.** An event stores language, topic class, outcome, latency, support
   ratio and red-flag category, never the question; `log_event` raises if a payload key could
   carry user content.
4. **Audio is deleted right after transcription** (overwrite then unlink). Transcripts are
   returned to the client and not stored.
5. **Redacted logs.** A logging filter masks API keys, bearer tokens, e-mails, phone numbers,
   13-digit identifiers and IPs; error bodies never include user text.
6. **k-anonymity and deletion.** Public metrics suppress any row below k=5. "Delete my data"
   (`DELETE /api/session/{id}`) erases the session, its events, gate records and any saved
   questions, which exist only after a separate opt-in.

Data map, consent model, GDPR and national-law alignment, DPIA skeleton:
[docs/data-protection.md](docs/data-protection.md).

## Measurement

`scripts/measure.py` (`make measure`) runs the evaluation datasets under `eval/` and writes
`reports/YYYY-MM-DD_measurement.md`, the same numbers as `.json`, and a 50-sentence
`YYYY-MM-DD_spotcheck.csv` for two human raters. It computes support rate, refusal correctness
on off-KB questions, red-flag recall on crafted inputs and the false-positive rate on near
misses, latency (median and p90, text and voice), word error rate on consented utterances and
the usability summary. **No number enters the UNICEF application form unless it appears in a
committed report under `reports/`.** Exact metric definitions and dataset formats:
[docs/evaluation.md](docs/evaluation.md).

### Measured so far

One report is committed: [`reports/2026-10-20_measurement.md`](reports/2026-10-20_measurement.md).
Its header says **DRY RUN (mock providers)**: it was produced with the mock LLM, the lexical
judge, the hash embedder and mock STT/TTS on the demo knowledge base, so it proves that the
pipeline and the datasets work and describes the behaviour of the deterministic mocks, not of
any model. Read with that caveat, it records: support rate 1.000 (115/115 sentences, an upper
bound from the lexical judge), 29 of 30 in-KB questions answered, refusal correctness 0.970
(97/100 off-KB questions withheld; the three misses are listed by id), red-flag recall 1.000
(100/100) with a false-positive rate of 0.000 on 60 near misses, and text latency median
52.0 ms / p90 88.9 ms (pipeline overhead only, including the relevance check). WER and usability are "not measured": there are
no consented recordings and no usability sessions yet. None of these numbers is quotable as a
result; the first report with real providers is roadmap item 4.

## Test suite

```bash
.venv/bin/python -m pytest backend/tests -q      # unit + integration + adversarial (make test)
.venv/bin/ruff check backend scripts             # make lint
cd web && npm run lint && npm run typecheck && npm test
```

- `backend/tests/unit/`: module tests (i18n, chunker, embed, ingest, retrieval, generation, llm,
  verifier, relevance, scope, gate, red flags, privacy, events, consent texts, referral, stt,
  tts, and the pure functions of `scripts/measure.py` and `scripts/make_demo_data.py`).
- `backend/tests/integration/`: the API through `TestClient` with mock providers, the pipeline
  end to end, and dataset-level regression tests over `eval/` (every off-KB question withheld,
  every red-flag input flagged).
- `backend/tests/adversarial/`: inputs designed to make MILA misbehave (prompt injection in
  sources, dosing requests, typo-ridden red flags in both scripts, minors disclosing abuse,
  attempts to extract a diagnosis, consent skips). These must stay green before any release.

At the time of writing `--collect-only` finds 1,282 tests (878 unit, 188 integration,
216 adversarial); CI fails when fewer than 150 tests or fewer than 40 adversarial tests are
collected, runs the suite on Python 3.11 and 3.12, compiles the scripts, builds the web client
and validates the compose file. The web client has 19 `node:test` cases. Tests never need
network, GPU or model downloads; real providers are imported lazily.

## Limitations (v0.1, honest)

- **Mock providers by default.** The LLM, STT and TTS are deterministic mocks and the embedder
  is a hash; nothing in the repository has been run against a real model yet. The mock LLM is
  extractive (it copies sentences from the retrieved chunks), so the quality of real answers,
  translations and voice is unknown until a real provider is configured and measured.
- The demo knowledge base consists of **paraphrases that are not clinically reviewed**; they
  exist to exercise the pipeline, not to inform patients. The WHO sources are not in the
  repository, the manifest `url`s are landing pages that must be replaced by direct PDF links,
  and `--download` needs network access from the machine that runs it (it fails behind
  restrictive proxies).
- The default **lexical judge is a weak verifier**: it measures token overlap between a sentence
  and its cited chunk, caps the score when a number or a negation differs, and that is all. It
  catches fabricated sentences and missing citations, not a swapped word or a paraphrase that
  inverts meaning, and it scores cross-lingual pairs near zero. Until an LLM or NLI judge is
  configured and spot-checked against human raters, support rates must be read as upper bounds.
- **Referral numbers are unverified.** The seed data fills in only the standard emergency numbers
  (124 ambulance, 122 police). Every other point (SOS lines, the children's helplines, the Banja
  Luka clinic, the generic "Dom zdravlja" entries) has an empty `phone`, an empty `verified_on`
  and a `to verify: <number>` or "fill before pilot" note; the pilot clinic must fill and verify
  them before launch.
- **Minors.** The minor flag selects the minors' consent text, adds child-protection services to
  every referral plan, tells the red-flag router and adds the `minor_note` line ("you can also
  talk to a trusted adult") to every response; in generation it only appends a note to the
  system prompt, so "adapted wording" depends on the real model.
- No accounts, no history, no WhatsApp or phone-line channel: the web UI is the only channel.
- Voice quality depends on the open-weight STT/TTS models and has not yet been measured on the
  consented utterance set (no recordings exist yet). The UI shows the transcript and asks for
  confirmation but does not yet react to a low STT confidence.
- No automatic retention timer: sessions persist until the user deletes them or the maintainers
  purge at the end of the pilot. The browser keeps the session id in `sessionStorage` (gone
  when the tab or browser closes) and only language and display preferences in `localStorage`;
  a session whose consent version is older than the server's is refused with 403 and the client
  asks for consent again.
- One-time answer audio (`audio_url`) lives in process memory: run a single uvicorn worker or
  put a shared store behind it.
- Montenegrin-specific letters (ś, ź) are transliterated on input only.

## Roadmap to `v0.1.0-unicef`

1. Clinic review of the 20 sample answers and the sources behind them; `reviewed_by` set.
2. Referral points for BA and ME verified by the clinic (`verified_on`, `verified_by`).
3. LLM or NLI support judge configured; 50-sentence human spot-check with two raters.
4. First measurement report with real providers under `reports/` (the only report so far is a
   dry run with mock providers).
5. Usability session with 5 to 10 women (three voice questions each), consent recorded.
6. DPIA completed and signed (skeleton in `docs/data-protection.md`).
7. faster-whisper and Piper tested on the WER set; low-bandwidth audio profile checked.
8. Container hardening verified on the pilot host (see `SECURITY.md`).

## Licence

Code and documentation: [Apache-2.0](LICENSE). Knowledge-base documents keep their own
licences (for example WHO publications under CC BY-NC-SA 3.0 IGO) and are never relicensed; see
[docs/knowledge-base.md](docs/knowledge-base.md).

## How to contribute

- Read [docs/architecture.md](docs/architecture.md) first; the module contracts are binding and
  tests depend on them.
- Keep the scope: information + referral. Pull requests that add diagnosis, dosing or test
  interpretation will not be merged, however well cited.
- Never store question text in `Event`, never log raw user text, never add an IP or device
  identifier to the data model.
- Add tests next to the module you touch; adversarial cases go in `backend/tests/adversarial/`.
  Run `make test lint` (what CI runs) before opening a pull request.
- Do not add dependencies without a reason (stdlib and numpy are preferred for v0.1); real
  providers stay lazy-imported so tests and the default stack never load a model.
- Follow the [Code of Conduct](CODE_OF_CONDUCT.md); report vulnerabilities as described in
  [SECURITY.md](SECURITY.md).

Documentation index: [architecture](docs/architecture.md), [safety](docs/safety.md),
[data protection](docs/data-protection.md), [knowledge base](docs/knowledge-base.md),
[evaluation](docs/evaluation.md).

---

## Ukratko na srpskom

MILA je asistent otvorenog koda za informacije i upućivanje u vezi sa reproduktivnim i
materinskim zdravljem, na srpskom, bosanskom, crnogorskom, hrvatskom i engleskom jeziku,
latinicom ili ćirilicom, prvenstveno glasom. **MILA ne daje medicinske savjete**: ne postavlja
dijagnozu, ne preporučuje lijekove ni doze i ne tumači nalaze. Svaka rečenica u odgovoru
oslanja se na odobren, verzionisan izvor i ima citat; ako takvog izvora nema, odgovor se
uskraćuje i umjesto njega se prikazuje gdje potražiti pomoć. Hitna stanja (krvarenje u
trudnoći, jak bol, povišena temperatura u trudnoći, slabiji pokreti bebe, misli o
samopovrjeđivanju, nasilje, prinuda) prepoznaju se prije svega ostalog i vode direktno na
brojeve hitne pomoći i podrške.

Ništa se ne čuva bez pristanka: nema naloga, nema IP adresa, pitanja se ne pamte (osim ako to
sama izričito dozvoliš), snimak glasa se briše odmah nakon prepoznavanja, a javne statistike se
prikazuju samo za grupe od najmanje pet osoba. Podatke možeš obrisati jednim klikom.

Ovo je verzija 0.1: demo izvori nisu klinički pregledani, a brojevi telefona za upućivanje moraju
biti provjereni prije pilota. Kod je pod licencom Apache-2.0.
