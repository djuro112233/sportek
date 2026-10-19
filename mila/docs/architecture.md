# MILA architecture and module contracts

MILA is an information + referral assistant. It never diagnoses, never recommends doses,
never interprets test results. Every answer sentence is tied to a chunk of an approved,
versioned source, or the answer is withheld and replaced with a referral.

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
def extract_pages(file_path: Path) -> list[PageText]        # .pdf via pypdf, .md/.txt one page per section
def ingest_document(db: Session, doc: ManifestDoc, file_path: Path, embedder: Embedder, *, max_tokens=400) -> SourceVersion
def ingest_manifest(db: Session, settings: Settings, embedder: Embedder | None = None, *, only: set[str] | None = None, download: bool = False) -> IngestReport
```
Rules: `version_hash` = sha256 of the file; re-ingesting the same hash is a no-op; a new hash
marks older versions `is_current=False` and removes their chunks. `review_status` is `reviewed`
iff `reviewed_by` is non-empty in the manifest, else `public_unreviewed`.

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
    def __init__(self, min_support_ratio: float = 0.6, min_confidence: float = 0.35)
    def decide(self, sentences: list[AnswerSentence], chunks: list[RetrievedChunk]) -> GateDecision
def record_decision(db: Session, decision: GateDecision, event_id: int | None = None) -> GateRecord
```
Withhold reasons (stable strings): `no_sentences`, `low_support_ratio`, `medication_or_dose`,
`low_confidence`, `no_citations`, `unreviewed_source_outside_demo`.

### `app/core/redflags.py`
```python
class RedFlagRouter:
    def __init__(self, classifier_threshold: float = 0.85)
    def check(self, text: str, *, lang: str | None = None, is_minor: bool | None = None) -> RedFlagResult
def get_router() -> RedFlagRouter    # module-level singleton
```
Rules (keyword/phrase lists for sr/bs/me/hr/en, Latin and Cyrillic, with typo tolerance)
win over the classifier. `child_protection=True` for `minor_sexual_adult`.

### `app/core/referral.py`
```python
class ReferralService:
    def __init__(self, db: Session)
    def for_context(self, *, region: str, lang: str, script: str = "latin", category: str | None = None,
                    is_minor: bool | None = None, emergency: bool = False) -> Referral
def seed_referral_points(db: Session) -> int    # idempotent; seeds BA/ME numbers, Alivija Clinic, helplines
```

### `app/core/privacy.py`
```python
def new_session_id() -> str                      # secrets.token_urlsafe(24)
class RedactionFilter(logging.Filter)            # masks api keys/bearer tokens, emails, phones, 13-digit JMBG
def redact(text: str) -> str
def k_anonymize(rows: list[dict], count_key: str, k: int) -> list[dict]   # drops rows with count < k
def secure_delete(path: Path) -> None
def delete_session_data(db: Session, session_id: str) -> dict[str, int]
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
def asks_for_dose(text: str) -> bool   # a question asking for a dose is withheld before generation
```
`ask` runs, in this order: language/script/region resolution (request over session) → red-flag
check (flag ⇒ `redflag` response, `redflag` event) → dose-question guard (⇒ `withheld`,
reason `medication_or_dose`) → retrieval (`settings.retrieval_top_k`) → generation → verifier →
gate → referral + disclaimer (+ TTS when `want_audio`, never for `withheld`) → `ask` event →
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
| Method | Path | Body / query | Returns |
|---|---|---|---|
| GET | `/health` | | `{status, demo_mode, version}` |
| GET | `/consent/text?lang=&script=&is_minor=` | | `{version, text, spoken_text, items[]}` |
| POST | `/consent` | `{lang, script?, region?, is_minor, accepted: true, save_questions: false, consent_version}` | `{session_id, consent_version}` (403 if not accepted) |
| DELETE | `/session/{session_id}` | | `{deleted: {...}}` |
| POST | `/ask` | `AskRequest` | `AskResponse` (403 without consent) |
| POST | `/transcribe` | multipart `file`, `session_id`, `lang?` | `Transcript` (audio deleted immediately) |
| POST | `/speak` | `{text, lang, low_bandwidth?}` | `audio/wav` |
| GET | `/referral?region=&category=&minor=&lang=` | | `Referral` |
| GET | `/metrics/public` | | aggregates, suppressed below k |
| GET | `/admin/sources`, POST `/admin/sources/{id}/review` | `X-Admin-Token` | |

Additive endpoints reported by the module authors (same prefix; the table above is unchanged):

| Method | Path | Body / query | Returns |
|---|---|---|---|
| GET | `/audio/{token}` | | `audio/wav` served once (404 afterwards or when expired); tokens come from `AskResponse.audio_url` |
| POST | `/transcribe` | as above | `Transcript` plus `confirm_required: true` (the UI shows the transcript and asks before `/ask`) |
| GET | `/session/{session_id}` | | `{exists, consent_given, lang, script, region, is_minor, save_questions}` (`exists: false` for unknown ids) |
| POST | `/session/{session_id}/preferences` | `{save_questions?, lang?, script?, region?, is_minor?}` | the same session info; turning `save_questions` off deletes saved questions |
| GET | `/ask/topics` | | `{topics: TOPIC_CLASSES, red_flag_categories: RED_FLAG_CATEGORIES}` |
| GET | `/referral?...&script=` | `script` added | `Referral` rendered in the requested script |
| GET | `/admin/gate/records?limit=` | `X-Admin-Token` | gate audit trail (reasons and counts, no text) |
| POST | `/admin/referral/seed` | `X-Admin-Token` | `{seeded}` (idempotent re-seed of the referral directory) |
| GET | `/metrics/internal?window_days=` | `X-Admin-Token` | public figures plus unsuppressed counts, red-flag categories, gate reasons |

`POST /ask` answers 429 with `Retry-After: 60` when the per-session rate limit
(`MILA_RATE_LIMIT_PER_MINUTE`) is exceeded; it never logs the request text.

## Data protection (summary; full text in docs/data-protection.md)
No question text, audio, IP or device id is stored. Events are aggregate-only. Audio is deleted
right after transcription. `SavedQuestion` rows exist only with explicit consent and die with the
session. Public metrics are suppressed below k=5.

## Deployment

`docker compose up --build` starts the stack below. `docker-compose.yml` is the source of
truth for service names and flags; this section explains what each piece is for.

| Service | Image / build | Purpose | Notes |
|---|---|---|---|
| `db` | Postgres 16 with the pgvector extension | Sources, chunks and embeddings, sessions, events, gate records | Data volume `pgdata`; not exposed outside the compose network |
| `api` | `backend/` (FastAPI, uvicorn, `app.main:create_app --factory`) | The MILA API on port 8000 | Runs `scripts/ingest_kb.py` against the demo manifest at start-up; health check `GET /api/health` |
| `web` | `web/` (Next.js 14) | Voice-first UI on port 3000 | Talks to `api` only; no external origins |
| `llm` (optional profile) | OpenAI-compatible server for an open-weight model (vLLM, llama.cpp or similar) on port 8001 | Real generation and the LLM judge | Enabled with `MILA_LLM_PROVIDER=openai_compatible`; requests carry `store=false` |

Hardening applied to `api` and `web`: non-root user, `cap_drop: [ALL]`,
`security_opt: [no-new-privileges:true]`, `read_only: true` root filesystem, `tmpfs` for
`MILA_AUDIO_TMP_DIR` so uploads never touch disk, and only the two published ports. Secrets
come from the environment or an untracked `.env`, never from the image.

Environment variables (all defined in `backend/app/config.py`, prefix `MILA_`; see the README
for the full table with defaults):

| Group | Variables |
|---|---|
| Runtime | `MILA_APP_ENV`, `MILA_DEMO_MODE`, `MILA_DATABASE_URL`, `MILA_CORS_ORIGINS`, `MILA_RATE_LIMIT_PER_MINUTE` |
| LLM | `MILA_LLM_PROVIDER`, `MILA_LLM_BASE_URL`, `MILA_LLM_API_KEY`, `MILA_LLM_MODEL`, `MILA_LLM_TIMEOUT_S` |
| Retrieval and judge | `MILA_EMBEDDER`, `MILA_EMBEDDING_DIM`, `MILA_JUDGE_PROVIDER`, `MILA_RETRIEVAL_TOP_K` |
| Voice | `MILA_STT_PROVIDER`, `MILA_STT_MODEL`, `MILA_TTS_PROVIDER`, `MILA_PIPER_VOICE_DIR` |
| Safety thresholds | `MILA_GATE_MIN_SUPPORT_RATIO`, `MILA_GATE_MIN_CONFIDENCE`, `MILA_VERIFIER_SUPPORT_THRESHOLD`, `MILA_REDFLAG_CLASSIFIER_THRESHOLD` |
| Privacy and admin | `MILA_K_ANONYMITY`, `MILA_AUDIO_TMP_DIR`, `MILA_ADMIN_TOKEN`, `MILA_CONSENT_VERSION`, `MILA_DEFAULT_REGION` |
| Knowledge base | `MILA_KB_DIR`, `MILA_MANIFEST_PATH` |

A pilot deployment sets `MILA_APP_ENV=prod`, `MILA_DEMO_MODE=false`, a Postgres
`MILA_DATABASE_URL`, a non-empty `MILA_ADMIN_TOKEN`, the real providers, and puts a
TLS-terminating reverse proxy in front of `web` and `api`.
