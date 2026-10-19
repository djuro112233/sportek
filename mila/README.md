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
docker compose up --build
```

- Web UI: <http://localhost:3000>
- API health: <http://localhost:8000/api/health> (returns `{"status": "ok", "demo_mode": true, "version": "0.1.0"}`)
- API docs (non-production only): <http://localhost:8000/api/docs>

The default stack uses deterministic local providers (mock LLM, hash embedder, lexical judge,
mock STT/TTS) so it needs no GPU, no model download and no network. Real providers are opt-in
through `MILA_*` environment variables (see [Provider configuration](#provider-configuration)).
The compose services and their hardening are described in
[docs/architecture.md, Deployment](docs/architecture.md#deployment).

### Path B: local development

Requires Python 3.11+ and Node 18+.

```bash
# backend
uv venv --seed .venv                 # or: python3.11 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python scripts/ingest_kb.py          # loads kb/manifest.yaml into the local SQLite DB
.venv/bin/uvicorn --app-dir backend 'app.main:create_app' --factory --port 8000

# web (second terminal)
cd web && npm install && npm run dev
```

`uv venv` without `--seed` creates an environment without `pip`; in that case use
`uv pip install -e '.[dev]'` instead of the `pip` line. Optional extras: `.[voice]`
(faster-whisper, Piper), `.[embed]` (BGE-M3 via sentence-transformers), `.[postgres]`,
`.[redis]`.

## Architecture

```
 audio ──► STT ──► text ──► red-flag router ──► (flag) ──► referral response
                           │
                           ▼ (no flag)
                    hybrid retrieval (vector + BM25, reviewed/demo filter)
                           │
                           ▼
                    generation (open-weight LLM, [S1] markers)
                           │
                           ▼
                    verifier (sentence ↔ cited chunk support)
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
that is used by default and in tests.

## Repository layout

```
mila/
├── backend/
│   ├── app/
│   │   ├── api/          # FastAPI routers: consent, ask, transcribe, speak, referral, metrics, admin
│   │   ├── core/         # i18n, redflags, retrieval, generation, verifier, gate, referral,
│   │   │                 # consent, privacy, events, pipeline
│   │   ├── kb/           # embed, chunker, ingest
│   │   ├── models/       # SQLAlchemy models (sources, chunks, sessions, events, gate records, ...)
│   │   ├── services/     # llm, stt, tts providers (mock + optional real)
│   │   ├── config.py     # Settings (MILA_* environment variables)
│   │   ├── db.py         # engine / session factory
│   │   └── main.py       # application factory `create_app`
│   └── tests/            # unit/, integration/, adversarial/
├── web/                  # Next.js 14 (TypeScript) voice-first UI
├── kb/                   # manifest.yaml, demo/ paraphrases, downloads/ (git-ignored)
├── eval/                 # evaluation datasets (JSONL/CSV, see docs/evaluation.md)
├── scripts/              # ingest_kb.py, measure.py, helpers
├── reports/              # committed measurement reports (the only source of numbers)
├── docs/                 # architecture, safety, data protection, knowledge base, evaluation
├── pyproject.toml        # package, pytest and ruff configuration
└── LICENSE               # Apache-2.0
```

All backend imports are rooted at `backend/` (`from app.core.gate import ValidationGate`).

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

`kb/demo/` holds short paraphrases written for this prototype (Apache-2.0) so that the full
pipeline can be demonstrated and tested without downloading anything. **They are not clinically
reviewed** and are only ever served in demo mode. Details, licence rules and the clinic review
workflow: [docs/knowledge-base.md](docs/knowledge-base.md).

## Safety design

1. **Red flags first.** Before retrieval, a rules-first router (keyword and phrase lists for
   sr/bs/me/hr/en in both scripts, typo-tolerant) checks for bleeding in pregnancy, severe
   abdominal pain, fever in pregnancy, pre-eclampsia signs, reduced fetal movement, suicidal
   ideation, violence or coercion, and sexual contact between a minor and an adult. A flag
   short-circuits to an emergency or support referral; the pipeline never generates text for it.
2. **Approved sources only.** Retrieval is filtered by review status; `blocked` chunks are never
   returned and `public_unreviewed` ones only in demo mode.
3. **Constrained generation.** The system prompt forbids diagnosis, dosing and test
   interpretation and requires a `[Sn]` citation marker on every sentence.
4. **Sentence-level verification.** Each sentence is checked against the chunk it cites; a
   sentence without a marker, with a marker that maps to nothing, or with low support is removed.
5. **Validation gate.** A versioned gate approves or withholds the whole answer with stable
   reasons (`no_sentences`, `low_support_ratio`, `medication_or_dose`, `low_confidence`,
   `no_citations`, `unreviewed_source_outside_demo`). Any medication quantity, dosing imperative
   or regimen withholds the entire answer, not just the sentence.
6. **Referral and disclaimer always.** Every response, answered or not, ends with a localised
   disclaimer and a referral block; minors receive adapted wording and protection services.

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

`scripts/measure.py` runs the evaluation datasets under `eval/` and writes
`reports/YYYY-MM-DD_measurement.md`. It computes support rate, refusal correctness on off-KB
questions, red-flag recall on crafted inputs, latency (median and p90, text and voice), word
error rate on consented utterances and the usability summary. **No number enters the UNICEF
application form unless it appears in a committed report under `reports/`.** Exact metric
definitions and dataset formats: [docs/evaluation.md](docs/evaluation.md).

## Test suite

```bash
.venv/bin/python -m pytest backend/tests -q      # unit + integration + adversarial
.venv/bin/ruff check backend scripts
```

- `backend/tests/unit/`: module tests (i18n, chunker, retrieval, verifier, gate, red flags,
  privacy, events, consent, referral).
- `backend/tests/integration/`: the API through `TestClient` with mock providers.
- `backend/tests/adversarial/`: inputs designed to make MILA misbehave (prompt injection in
  sources, dosing requests, typo-ridden red flags in both scripts, minors disclosing abuse,
  attempts to extract diagnosis). These must stay green before any release.

Tests never need network, GPU or model downloads.

## Limitations (v0.1, honest)

- The demo knowledge base consists of **paraphrases that are not clinically reviewed**; they
  exist to exercise the pipeline, not to inform patients.
- The default **lexical judge is a weak verifier**: it measures token overlap between a sentence
  and its cited chunk. It catches fabricated sentences and missing citations, not subtle
  distortions. Until an LLM or NLI judge is configured and spot-checked against human raters,
  support rates must be read as upper bounds.
- **Referral numbers must be verified** by the pilot clinic before launch; the seed data marks
  each point with `verified_on` and anything unverified is shown as such.
- No accounts, no history, no WhatsApp or phone-line channel: the web UI is the only channel.
- Voice quality depends on the open-weight STT/TTS models and has not yet been measured on the
  consented utterance set.
- No automatic retention timer: sessions persist until the user deletes them or the maintainers
  purge at the end of the pilot.
- Montenegrin-specific letters (ś, ź) are transliterated on input only.

## Roadmap to `v0.1.0-unicef`

1. Clinic review of the 20 sample answers and the sources behind them; `reviewed_by` set.
2. Referral points for BA and ME verified by the clinic (`verified_on`, `verified_by`).
3. LLM or NLI support judge configured; 50-sentence human spot-check with two raters.
4. First committed measurement report under `reports/`.
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
- Do not add dependencies without a reason (stdlib and numpy are preferred for v0.1).
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
