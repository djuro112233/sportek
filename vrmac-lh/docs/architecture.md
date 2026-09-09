# Architecture

> Prototype built for the SMART ERA application, September–October 2026. Sample data.
> The reference documents named in the brief (`SIP_Draft_Vrmac_Living_Heritage.pdf` §2.2/§2.3/§11 and
> `VRMAC_LH_Prototype.html`) were not available in the repository when this prototype was built; the diagram
> below follows the brief's architecture description and should be aligned with §2.2 of the SIP Draft.

## Component diagram

```mermaid
flowchart LR
  subgraph Clients["Next.js apps (one codebase, /api proxied)"]
    HOST["Host PWA<br/>voice recording, draft review, consent"]
    VIS["Visitor app<br/>MapLibre + OSM map, GPX trails, ask, itinerary, requests"]
    VAL["Validator queue<br/>draft → reviewed → approved | rejected, provenance"]
    DASH["Institution dashboard<br/>KPI table (k≥5, by sex), heat map, timing log"]
  end

  CADDY["Caddy<br/>TLS, security headers, no access log"]
  HOST --> CADDY
  VIS --> CADDY
  VAL --> CADDY
  DASH --> CADDY

  subgraph API["FastAPI (Python 3.12) — OpenAPI at /api/docs"]
    AUTH["auth + RBAC<br/>bcrypt, JWT, audit log"]
    GATE["validation gate<br/>services/validation.py"]
    RAG["grounded answers<br/>services/rag.py"]
    ONB["voice onboarding<br/>services/onboarding.py"]
    GEO["map / trails / itinerary<br/>services/geo.py"]
    KPI["events → KPIs<br/>services/kpi.py"]
    EXP["NGSI-LD + DCAT-AP<br/>services/export.py"]
  end
  CADDY --> API

  subgraph Providers["Pluggable providers (env flags)"]
    LLM["LLM<br/>Ollama (qwen2.5:1.5b) | OpenAI-compatible | none"]
    EMB["Embeddings<br/>Ollama paraphrase-multilingual | sentence-transformers | hash"]
    STT["Speech-to-text<br/>faster-whisper small int8 | API | fixture"]
  end
  RAG --> LLM
  RAG --> EMB
  ONB --> LLM
  ONB --> STT

  subgraph Data["PostgreSQL 16 + pgvector"]
    APPROLE["app role (owner)"]
    PUBROLE["visitor role<br/>SELECT only, RLS: status = 'approved'"]
    T["content tables + status/version<br/>provenance, consent_records,<br/>events, kpi_aggregates, audit_log,<br/>entry_chunks (vectors)"]
  end
  AUTH --> APPROLE
  GATE --> APPROLE
  ONB --> APPROLE
  KPI --> APPROLE
  RAG --> PUBROLE
  GEO --> PUBROLE
  EXP --> PUBROLE
  APPROLE --> T
  PUBROLE --> T

  REDIS["Redis + RQ worker<br/>transcription jobs"]
  ONB --> REDIS
  SCHED["scheduler<br/>nightly KPI job 02:00 UTC"] --> KPI
  EXP --> NGSI["NGSI-LD PointOfInterest<br/>+ DCAT-AP (files / endpoints)"]
```

## Workflows (one real path each)

```mermaid
sequenceDiagram
  participant H as Host (PWA)
  participant A as API
  participant S as STT
  participant L as LLM
  participant V as Validator
  participant P as Visitor
  H->>A: POST /onboarding/sessions (onboarding_started)
  H->>A: POST …/audio (webm)
  A->>S: transcribe (faster-whisper)
  A-->>H: transcript (transcript_ready)
  H->>A: POST …/draft
  A->>L: extract structured listing (json) / rules fallback
  A-->>H: draft + missing_fields (draft_generated)
  H->>A: POST …/confirm (listing + consent) → consent_record, listing[draft] (listing_confirmed, duration logged)
  V->>A: POST /validation/items/listing/{id}/transition approved (entry_approved, provenance, audit)
  P->>A: GET /listings, /map/features (visitor role, RLS → approved only)
  P->>A: POST /ask → answer with citations (answer_served) or refusal (answer_withheld)
```

## Data-layer enforcement of the validation gate

1. `status` CHECK constraint on every content table (`draft|reviewed|approved|rejected`), `version >= 1`.
2. Every transition writes a `provenance` row (who, when, version, source, note) and an `audit_log` row.
3. Visitor endpoints open the database as `vrmac_public`, a role with `SELECT` only and **row-level-security
   policies** `USING (status = 'approved')` on `heritage_entries`, `listings`, `trail_segments`, `trail_reports`,
   and `EXISTS(... approved)` on `entry_chunks`. A buggy query cannot leak a draft.
4. The services additionally apply an explicit `status == 'approved'` filter (belt and braces).
5. Tests in `backend/tests/test_validation_gate.py` prove all of the above against a real PostgreSQL.

## Deployment (2 vCPU / 4 GB, no GPU)

| Service | Image | Memory cap | Role |
|---|---|---|---|
| db | pgvector/pgvector:pg16 | 512 MB | content, vectors, events, aggregates |
| redis | redis:7-alpine | 64 MB | job queue |
| ollama (+ ollama-pull) | ollama/ollama | 2.2 GB | qwen2.5:1.5b + paraphrase-multilingual (CPU) |
| api | backend/Dockerfile | 1.2 GB | FastAPI + faster-whisper small (int8) |
| worker | backend/Dockerfile | 1.2 GB | RQ worker (transcription) |
| scheduler | backend/Dockerfile | 256 MB | nightly KPI computation |
| web | frontend/Dockerfile | 384 MB | Next.js (standalone) |
| caddy (profile `proxy`) | caddy:2-alpine | – | TLS termination |

Memory caps are soft guidance for a 4 GB VPS; the LLM and STT models are the small variants on purpose.
`LLM_PROVIDER=openai` with a hosted API removes the Ollama service entirely (`COMPOSE_PROFILES=` empty).
