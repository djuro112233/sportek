# MILA architecture and module contracts

MILA is an information + referral assistant. It never diagnoses, never recommends doses,
never interprets test results. Every answer sentence is tied to a chunk of an approved,
versioned source, or the answer is withheld and replaced with a referral.

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

## Repository layout

See README. Backend is FastAPI (Python 3.11+), web is Next.js 14 (TypeScript).
All backend imports are rooted at `backend/` (`from app.core.gate import ValidationGate`).

## Provider abstraction

Every external capability has a `Protocol` and a deterministic local implementation that
is used by default and in tests. Real providers are opt-in via settings (`backend/app/config.py`).

| Capability | Protocol (module)                  | Default (tests) | Optional real provider              |
|------------|------------------------------------|-----------------|-------------------------------------|
| LLM        | `LLMClient` (`services/llm.py`)    | `MockLLM`       | `OpenAICompatibleLLM` (`store=false`)|
| Embeddings | `Embedder` (`kb/embed.py`)         | `HashEmbedder`  | `BGEM3Embedder`                      |
| Support judge | `SupportJudge` (`core/verifier.py`) | `LexicalJudge` | `LLMJudge`                        |
| STT        | `STT` (`services/stt.py`)          | `MockSTT`       | `FasterWhisperSTT`                   |
| TTS        | `TTS` (`services/tts.py`)          | `MockTTS`       | `PiperTTS`                           |

## Module contracts (the API between modules; tests depend on these)

Shared types live in `app/core/types.py` (pydantic). Shared normalisation lives in
`app/core/i18n.py` (`normalize_text`, `tokenize`, `cyrillic_to_latin`, `latin_to_cyrillic`,
`render`, `t(key, lang, script)`, `register_messages`). DB models live in `app/models`.
Settings: `app.config.Settings` / `get_settings()`.

### `app/kb/embed.py`
```python
class Embedder(Protocol):
    dim: int
    def embed(self, texts: list[str]) -> list[list[float]]: ...   # L2-normalised vectors
class HashEmbedder(Embedder): def __init__(self, dim: int = 256)
class BGEM3Embedder(Embedder): lazy import of sentence_transformers ("BAAI/bge-m3")
def get_embedder(settings: Settings) -> Embedder
def cosine(a: list[float], b: list[float]) -> float
```

### `app/kb/chunker.py`
```python
@dataclass
class PageText: page: int; text: str
@dataclass
class ChunkDraft: text: str; page: int | None; heading_path: str; token_count: int
def chunk_pages(pages: list[PageText], max_tokens: int = 400, overlap_tokens: int = 40) -> list[ChunkDraft]
def estimate_tokens(text: str) -> int
```
Headings are detected heuristically (numbered headings, ALL CAPS lines, short title-case
lines); `heading_path` is "H1 > H2 > H3".

### `app/kb/ingest.py`
```python
def load_manifest(path: str | Path) -> list[ManifestDoc]   # pydantic model of kb/manifest.yaml entries
def extract_pages(file_path: Path) -> list[PageText]        # .pdf via pypdf (physical pages); .md/.txt/.html one page per section
def ingest_document(db: Session, doc: ManifestDoc, file_path: Path, embedder: Embedder, *, max_tokens=400) -> SourceVersion
def ingest_manifest(db: Session, settings: Settings, embedder: Embedder | None = None, *, only: set[str] | None = None, download: bool = False) -> IngestReport
def download_document(doc: ManifestDoc, target: Path) -> Path   # streams doc.url, checks sha256 when set, rejects HTML for a .pdf target
```
Rules: `version_hash` = sha256 of the file; re-ingesting the same hash is a no-op; a new hash
marks older versions `is_current=False` and removes their chunks. `review_status` is `blocked`
when the manifest entry sets `status: blocked`, else `reviewed` iff `reviewed_by` is non-empty,
else `public_unreviewed`. Source metadata is refreshed from the manifest on every run.

### `app/core/retrieval.py`
```python
class Retriever:
    def __init__(self, db: Session, embedder: Embedder, settings: Settings)
    def search(self, query: str, *, lang: str | None = None, top_k: int | None = None,
               allowed_statuses: tuple[str, ...] | None = None, topic: str | None = None) -> list[RetrievedChunk]
```
Hybrid: cosine over embeddings + BM25 over `tokenize(text)`, fused with reciprocal rank fusion.
`allowed_statuses` defaults to `("reviewed",)` or `("reviewed", "public_unreviewed")` when
`settings.demo_mode`. Chunks from `blocked` sources are never returned.

### `app/services/llm.py`
```python
class LLMClient(Protocol):
    name: str
    def complete(self, system: str, user: str, *, temperature: float = 0.0, max_tokens: int = 600) -> str: ...
class MockLLM(LLMClient)        # extractive, deterministic: sentences copied from chunks with correct [Sn] markers
class ScriptedLLM(LLMClient)    # returns given text(s) in order; for tests
class OpenAICompatibleLLM(LLMClient)  # httpx; sends store=false; no retries that duplicate data
def get_llm(settings: Settings) -> LLMClient
```

### `app/core/generation.py`
```python
SYSTEM_PROMPT: str   # forbids diagnosis/dosing/test interpretation; requires [Sn] markers on every sentence
class Generator:
    def __init__(self, llm: LLMClient)
    def build_prompt(self, question: str, chunks: list[RetrievedChunk], lang: str, *, is_minor: bool = False) -> tuple[str, str]
    def generate(self, question: str, chunks: list[RetrievedChunk], lang: str, *, is_minor: bool = False) -> RawAnswer
```
`translated=True` when `lang` differs from the language of all cited chunks.

### `app/core/verifier.py`
```python
MEDICATION_PATTERNS: list[re.Pattern]        # mg, mcg, ml, tableta, doza, drug names ...
def split_sentences(text: str) -> list[str]
def parse_markers(sentence: str) -> tuple[str, list[str]]   # ("clean sentence", ["S1","S3"])
def mentions_medication_dose(sentence: str) -> bool
class SupportJudge(Protocol):
    def support(self, sentence: str, evidence: str) -> float: ...   # 0..1
class LexicalJudge(SupportJudge)
class LLMJudge(SupportJudge)
class Verifier:
    def __init__(self, judge: SupportJudge, threshold: float = 0.5)
    def verify(self, answer_text: str, chunks: list[RetrievedChunk]) -> list[AnswerSentence]
def get_judge(settings: Settings, llm: LLMClient | None = None) -> SupportJudge
```
A sentence with no marker, or a marker that does not map to a retrieved chunk, is unsupported.

### `app/core/gate.py`
```python
GATE_VERSION = "1.0.0"
class ValidationGate:
    def __init__(self, min_support_ratio: float = 0.6, min_confidence: float = 0.35,
                 demo_mode: bool = True, min_relevance: float = 0.35)
    @classmethod
    def from_settings(cls, settings: Settings) -> ValidationGate
    def decide(self, sentences: list[AnswerSentence], chunks: list[RetrievedChunk], *,
               relevance: float | None = None) -> GateDecision
def record_decision(db: Session, decision: GateDecision, event_id: int | None = None) -> GateRecord
```
`confidence = 0.7 * support_ratio + 0.3 * mean(support_score of kept sentences)`. Withhold
reasons (stable strings; several may apply): `no_sentences`, `no_citations`,
`medication_or_dose`, `low_support_ratio`, `low_confidence`, `unreviewed_source_outside_demo`,
`low_relevance` (question coverage of the cited evidence below `gate_min_relevance`; skipped
when `relevance` is `None`; see `app/core/relevance.py`). The pipeline adds
`diagnosis_request`, `test_interpretation`, `manipulation` (scope guard, `app/core/scope.py`;
a dose request uses `medication_or_dose`) and `pipeline_error` (fail-closed).

### `app/core/redflags.py`
```python
class RedFlagRouter:
    def __init__(self, classifier_threshold: float = 0.85, *, classifier_margin: float = 0.5,
                 classifier: CharNgramNaiveBayes | None = None)
    def check(self, text: str, *, lang: str | None = None, is_minor: bool | None = None) -> RedFlagResult
def get_router() -> RedFlagRouter    # module-level singleton, threshold from settings
```
Rules (keyword/phrase lists for sr/bs/me/hr/en, Latin and Cyrillic, with typo tolerance)
win over the classifier (a pure-Python character n-gram Naive Bayes trained at import time
from the seeds in `app/core/redflag_rules.py`). `lang` is accepted for the contract; the rules
cover every language at once. `child_protection=True` for `minor_sexual_adult`.

### `app/core/referral.py`
```python
class ReferralService:
    def __init__(self, db: Session)
    def for_context(self, *, region: str, lang: str, script: str = "latin", category: str | None = None,
                    is_minor: bool | None = None, emergency: bool = False) -> Referral
def seed_referral_points(db: Session) -> int    # idempotent (keyed by name + region); returns rows added
def ensure_referral_points(db: Session) -> int  # seeds only when the table is empty; called by the API
```
The seed fills in only the standard emergency numbers (124 ambulance, 122 police) for `BA` and
`ME`. Every other point (SOS lines, children's helplines, the Banja Luka clinic, generic
"Dom zdravlja" entries) has an empty `phone` and `verified_on` and a `to verify: <number>` /
"fill before pilot" note; the clinic fills `phone`, `verified_on`, `verified_by` before launch.

### `app/core/privacy.py`
```python
def new_session_id() -> str                      # secrets.token_urlsafe(24)
class RedactionFilter(logging.Filter)            # masks api keys/bearer tokens, emails, phones, 13-digit JMBG, IPv4
def redact(text: str) -> str
def k_anonymize(rows: list[dict], count_key: str, k: int) -> list[dict]   # drops rows with count < k
def suppress_small(value: int, k: int) -> int | None                     # None below k
def secure_delete(path: Path) -> None
def delete_session_data(db: Session, session_id: str) -> dict[str, int]  # saved_questions, gate_records, events, sessions
```

### `app/core/events.py`
```python
def log_event(db: Session, *, type: str, session_id: str | None, lang: str = "", topic_class: str = "",
              outcome: str = "", latency_ms: int | None = None, support_ratio: float | None = None,
              redflag_category: str = "", input_mode: str = "text", payload: dict | None = None) -> Event
def classify_topic(text: str) -> str   # one of TOPIC_CLASSES
```

### `app/core/pipeline.py`
```python
class AskPipeline:
    def __init__(self, settings, db, *, llm, embedder, judge, redflags, tts=None)
    def ask(self, req: AskRequest, session: Session) -> AskResponse
```
Additions from integration (the signature above still works; `scripts/measure.py` uses it):
```python
class AskPipeline:
    def __init__(self, settings, db, providers: Providers | None = None, *, llm=None, embedder=None,
                 judge=None, redflags=None, tts=None)   # missing providers are built from settings
def public_gate(decision: GateDecision | None) -> GateDecision | None   # strips removed/withheld sentence text
def asks_for_dose(text: str) -> bool   # kept for compatibility; see app.core.scope.classify_scope
```
```python
# app/core/scope.py and app/core/relevance.py (docs/safety.md C9)
def classify_scope(text: str) -> ScopeResult   # kind in dose|diagnosis|test_interpretation|manipulation|None
def question_relevance(question, lang, sentences, chunks, idf=None, *, unknown_term_penalty=0.75) -> float | None
Retriever.stem_idf()   # cached inverse document frequency over current chunks, fed to question_relevance
ValidationGate.decide(sentences, chunks, *, relevance=None)   # adds reason low_relevance below gate_min_relevance
```
`ask` runs, in this order: language/script/region resolution (request over session) → red-flag
check (flag ⇒ `redflag` response, `redflag` event) → scope guard (`classify_scope`; a dose,
diagnosis, test-interpretation or manipulation request ⇒ `withheld` with its own reason and
message, no retrieval) → retrieval (`settings.retrieval_top_k`) → generation → verifier →
question relevance (`question_relevance`, logged as `relevance` in the gate decision and event
payload) → gate (`relevance=` kwarg) → referral + disclaimer (+ TTS when `want_audio`, never for `withheld`) → `ask` event →
`GateRecord` linked to it → `SavedQuestion` when the session opted in. Any exception in a
stage fails closed: `withheld`, gate reason `pipeline_error`, `ask` event with outcome `error`
and payload `{"error": "<exception class>", "stage": "<stage>"}`; no traceback reaches the client.
The gate decision returned in-process is complete; the API applies `public_gate` first.

### `app/core/container.py`
```python
@dataclass
class Providers: llm: LLMClient; embedder: Embedder; judge: SupportJudge; redflags: RedFlagRouter; stt: STT | None; tts: TTS | None
def build_providers(settings: Settings, *, stt=None, tts=None) -> Providers
def get_providers(app: FastAPI) -> Providers   # built on first use, cached on app.state.providers;
                                               # publishes app.state.stt / app.state.tts for the voice routers
```

### `app/services/stt.py` / `app/services/tts.py`
```python
class STT(Protocol): def transcribe(self, path: Path, *, lang_hint: str | None = None) -> Transcript
class TTS(Protocol): def synthesize(self, text: str, lang: str, *, low_bandwidth: bool = False) -> bytes  # WAV bytes
def get_stt(settings) -> STT ; def get_tts(settings) -> TTS
```

### API (prefix `/api`)

Every route the application registers (`backend/app/api/*.py` and `main.py`). Interactive
docs are served at `/api/docs` unless `MILA_APP_ENV=prod`.

| Method | Path | Body / query | Returns | Errors |
|---|---|---|---|---|
| GET | `/health` | | `{status, demo_mode, version}` | |
| GET | `/consent/text?lang=&script=&is_minor=` | defaults `sr`, `latin`, `false` | `{version, text, spoken_text, items[{key, text}], lang, script}` | |
| POST | `/consent` | `{lang, script?, region?, is_minor, accepted, save_questions?, consent_version}`; unknown fields rejected | `{session_id, consent_version, lang, script, region, is_minor, save_questions}` | 403 `consent_required` when `accepted` is false; 409 `consent_version_outdated` (+ `current`) when the version differs; 422 on extra or invalid fields |
| GET | `/session/{session_id}` | | `{exists, consent_given, lang, script, region, is_minor, save_questions}`; `exists: false` (all else `null`) for an unknown id | |
| POST | `/session/{session_id}/preferences` | `{save_questions?, lang?, script?, region?, is_minor?}`; unknown fields ignored | the same session info; turning `save_questions` off deletes the saved questions | 403 unknown or unconsented session |
| DELETE | `/session/{session_id}` | | `{deleted: {saved_questions, gate_records, events, sessions}}`; idempotent | |
| POST | `/ask` | `AskRequest` `{session_id, text (1..2000), lang?, script?, region?, input_mode?, want_audio?, low_bandwidth?}` | `AskResponse` (gate decision passed through `public_gate`, so removed or withheld sentence text is blank) | 403 without consent; 429 with `Retry-After: 60` past `MILA_RATE_LIMIT_PER_MINUTE` per session |
| GET | `/ask/topics` | | `{topics: TOPIC_CLASSES, red_flag_categories: RED_FLAG_CATEGORIES}` | |
| POST | `/transcribe` | multipart `file` (WAV, WebM, Ogg, MP3, MP4/M4A, at most 10 MB), `session_id`, `lang?` | `Transcript` `{text, lang, confidence, duration_s}` plus `confirm_required: true`; the audio is deleted before the response | 403 without consent; 413 over 10 MB; 415 other content types; 422 empty file |
| POST | `/speak?session_id=` | `{text (1..1500), lang, script?, low_bandwidth?}`; no session needed (the consent text is spoken before one exists) | `audio/wav` (16 kHz mono, 8 kHz when `low_bandwidth`) | 422 when nothing is left after removing markers; 429 per session id (anonymous callers share one bucket) |
| GET | `/audio/{token}` | | `audio/wav`, served once; tokens come from `AskResponse.audio_url` (5-minute expiry, at most 200 in memory) | 404 unknown, expired or already fetched |
| GET | `/referral?region=&category=&minor=&lang=&script=` | region defaults to `MILA_DEFAULT_REGION`, lang to `sr` | `Referral` `{emergency, message, points[]}` in the requested script; seeds the table on first use | 422 unknown category |
| GET | `/metrics/public?window_days=` | 1..365, default 30 | `PublicMetrics`: counts and ratios, `null` below k | |
| GET | `/metrics/internal?window_days=` | `X-Admin-Token` | `InternalMetrics`: the public figures plus unsuppressed counts, red-flag categories, gate reasons and decisions, events by type | 404 while no admin token is configured; 403 wrong token |
| GET | `/admin/sources` | `X-Admin-Token` | every source with review state, version summary and chunk count | 404 / 403 as above |
| POST | `/admin/sources/{id}/review` | `X-Admin-Token`; `{reviewed_by, status: reviewed\|public_unreviewed\|blocked, note?}` | `{source, note}`; sets `reviewed_on` to now; the note is only logged | 404 unknown source |
| GET | `/admin/gate/records?limit=` | `X-Admin-Token`; 1..500, default 50 | most recent gate decisions (reasons and counts, no text) | |
| POST | `/admin/referral/seed` | `X-Admin-Token` | `{seeded}` (idempotent re-seed of the referral directory) | |

Every response carries `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
`Referrer-Policy: no-referrer`, `Cache-Control: no-store` and
`Permissions-Policy: camera=(), geolocation=()`; unhandled errors answer
`500 {"detail": "internal error"}` and log only the path. CORS allows `MILA_CORS_ORIGINS`
with `GET`, `POST`, `DELETE` and the headers `Content-Type`, `X-Admin-Token`. The rate limiter
is an in-process sliding window keyed by session id, never by IP.

## Data protection (summary; full text in docs/data-protection.md)
No question text, audio, IP or device id is stored. Events are aggregate-only. Audio is deleted
right after transcription. `SavedQuestion` rows exist only with explicit consent and die with the
session. Public metrics are suppressed below k=5.

## Deployment

`docker compose up --build` starts the stack below. `docker-compose.yml` is the source of
truth for service names and flags; this section explains what each piece is for.

| Service | Image / build | Purpose | Notes |
|---|---|---|---|
| `db` | `pgvector/pgvector:pg16` (Postgres 16 with pgvector) | Sources, chunks and embeddings, sessions, events, gate records | Data volume `pgdata`; not exposed outside the compose network; password `MILA_DB_PASSWORD` (default `mila`) |
| `redis` | `redis:7-alpine`, persistence off | Reserved for a shared rate limiter | The API currently uses an in-process sliding window (`backend/app/main.py`); nothing is written to Redis yet |
| `api` | `backend/Dockerfile` (python:3.11-slim, extras `MILA_API_EXTRAS`, default `postgres`) | The MILA API on `127.0.0.1:8000` | Runs `scripts/ingest_kb.py` against the demo manifest (no downloads) before `uvicorn app.main:create_app --factory`; health check `GET /api/health` |
| `web` | `web/Dockerfile` (Next.js 14 standalone, node:20-alpine) | Voice-first UI on `127.0.0.1:3000` | The browser calls same-origin `/api/*`; a runtime route handler (`web/app/api/[...path]/route.ts`) proxies it to `MILA_API_URL` (`http://api:8000` in compose), so the image is not tied to one host; `NEXT_PUBLIC_API_BASE` remains an optional build-time override for static deployments; no external origins |
| `llm` (profile `local-llm`) | `vllm/vllm-openai` serving `MILA_LLM_MODEL` on port 8001, NVIDIA GPU required | Real generation and the LLM judge | Set `MILA_LLM_PROVIDER=openai_compatible` and `MILA_LLM_BASE_URL=http://llm:8001/v1` in `.env`; requests carry `store=false`; not published on the host |
| `ingest` (profile `ingest`) | same image as `api` | One-shot `scripts/ingest_kb.py --download` into the shared `kbdownloads` volume | `docker compose --profile ingest run --rm ingest`; needs network access and direct PDF links in the manifest |

Hardening applied to `api`, `web` and `redis`: non-root user, `cap_drop: [ALL]`,
`security_opt: [no-new-privileges:true]`, `read_only: true` root filesystem, memory limits,
`tmpfs` on `/tmp` (the API sets `MILA_AUDIO_TMP_DIR=/tmp/mila-audio`) so uploads never touch
disk, and only the two published ports, both bound to `127.0.0.1`. Secrets come from the
environment or an untracked `.env` (copy `.env.example`), never from the image.

Environment variables (all defined in `backend/app/config.py`, prefix `MILA_`; see the README
for the full table with defaults):

| Group | Variables |
|---|---|
| Runtime | `MILA_APP_ENV`, `MILA_DEMO_MODE`, `MILA_DATABASE_URL`, `MILA_CORS_ORIGINS`, `MILA_RATE_LIMIT_PER_MINUTE` |
| LLM | `MILA_LLM_PROVIDER`, `MILA_LLM_BASE_URL`, `MILA_LLM_API_KEY`, `MILA_LLM_MODEL`, `MILA_LLM_TIMEOUT_S` |
| Retrieval and judge | `MILA_EMBEDDER`, `MILA_EMBEDDING_DIM`, `MILA_JUDGE_PROVIDER`, `MILA_RETRIEVAL_TOP_K` |
| Voice | `MILA_STT_PROVIDER`, `MILA_STT_MODEL`, `MILA_TTS_PROVIDER`, `MILA_PIPER_VOICE_DIR` |
| Safety thresholds | `MILA_GATE_MIN_SUPPORT_RATIO`, `MILA_GATE_MIN_CONFIDENCE`, `MILA_GATE_MIN_RELEVANCE`, `MILA_RELEVANCE_UNKNOWN_TERM_PENALTY`, `MILA_VERIFIER_SUPPORT_THRESHOLD`, `MILA_REDFLAG_CLASSIFIER_THRESHOLD` |
| Privacy and admin | `MILA_K_ANONYMITY`, `MILA_AUDIO_TMP_DIR`, `MILA_ADMIN_TOKEN`, `MILA_CONSENT_VERSION`, `MILA_DEFAULT_REGION` |
| Knowledge base | `MILA_KB_DIR`, `MILA_MANIFEST_PATH` |

A pilot deployment sets `MILA_APP_ENV=prod`, `MILA_DEMO_MODE=false`, a Postgres
`MILA_DATABASE_URL`, a non-empty `MILA_ADMIN_TOKEN`, the real providers, and puts a
TLS-terminating reverse proxy in front of `web` and `api`.
