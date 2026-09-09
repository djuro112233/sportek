# Architecture

> Prototype built for the SMART ERA application, September–October 2026. Sample data.
> `SIP_Draft_Vrmac_Living_Heritage.pdf` §2.2/§2.3 was not available to this build, so the diagrams below
> follow the brief. Align them with the SIP Draft before the pitch (see `docs/decisions.md`).

## Territory

The prototype covers the rural plateau of Vrmac **on both sides of the ridge**. Every point of interest,
provider, trail segment and event belongs to a village, and every village carries its municipality.

| Village | Municipality | Side | Content |
|---|---|---|---|
| Gornja Lastva | Tivat | Tivat | approved: village, both churches' entries, festival, landscape days, culture house, olive mills, census |
| Donja Lastva | Tivat | Tivat | approved: settlement, sample providers, trailhead |
| St Vitus area | Tivat | ridge | approved: 9th-century church at 440 m |
| Tivat | Tivat | Tivat | approved: municipality seat |
| Gornji Stoliv | **Kotor** | Kotor | **unverified**: draft entry only, cannot be approved |
| Pasiglav | Tivat | Tivat | **unverified**: reference row only |

## Components

```mermaid
flowchart LR
  subgraph Clients["Next.js (one codebase, /api proxied)"]
    HOST["Host PWA<br/>offline recording (IndexedDB),<br/>host-confirmed fields, consent"]
    VIS["Visitor app<br/>MapLibre + OSM, GPX trails,<br/>ask, multi-village itinerary"]
    VAL["Validator queue<br/>draft → reviewed → approved | rejected"]
    DASH["Institution dashboard<br/>K01–K23 after disclosure review,<br/>heat map, quality metrics"]
  end

  CADDY["Caddy — TLS, security headers, no access log"]
  HOST --> CADDY
  VIS --> CADDY
  VAL --> CADDY
  DASH --> CADDY

  subgraph API["FastAPI (Python 3.12) — OpenAPI at /api/docs"]
    AUTH["auth + RBAC + audit log"]
    GATE["validation gate<br/>services/validation.py"]
    RAG["grounded answers<br/>services/rag.py + response cache"]
    SUP["support check<br/>providers/support.py"]
    ONB["voice onboarding<br/>services/onboarding.py"]
    GEO["map / trails / itinerary / requests"]
    KPI["events → K01–K23<br/>services/kpi.py + disclosure.py"]
    EXP["NGSI-LD + DCAT-AP"]
    BUD["spend cap<br/>services/budget.py"]
  end
  CADDY --> API
  RAG --> SUP
  RAG --> BUD
  ONB --> BUD

  subgraph Providers["Pluggable providers (env flags)"]
    LLM["LLM: EU inference provider (pay-per-use,<br/>no data retention) | ollama/vllm | none"]
    EMB["Embeddings: multilingual open model"]
    STT["STT: EU Whisper | faster-whisper | fixture"]
  end
  RAG --> LLM
  RAG --> EMB
  SUP --> LLM
  ONB --> LLM
  ONB --> STT

  subgraph Data["PostgreSQL 16 + pgvector"]
    APPROLE["app role (owner)"]
    PUBROLE["visitor role — SELECT only,<br/>RLS: status = 'approved'"]
    T["villages, content + status/version,<br/>provenance, consent, pseudonymised events,<br/>kpi_runs/aggregates, answer_records,<br/>response_cache, llm_usage, audit_log,<br/>entry_chunks (vectors)"]
  end
  AUTH --> APPROLE
  GATE --> APPROLE
  ONB --> APPROLE
  KPI --> APPROLE
  BUD --> APPROLE
  RAG --> PUBROLE
  GEO --> PUBROLE
  EXP --> PUBROLE
  APPROLE --> T
  PUBROLE --> T

  REDIS["Redis + RQ worker — transcription"]
  ONB --> REDIS
  SCHED["scheduler — nightly KPIs 02:00 UTC,<br/>request expiry"] --> KPI
  EXP --> NGSI["NGSI-LD PointOfInterest + DCAT-AP"]
```

## Workflows

```mermaid
sequenceDiagram
  participant H as Host (PWA)
  participant IDB as IndexedDB
  participant A as API
  participant S as Speech-to-text
  participant L as LLM
  participant V as Validator
  participant P as Visitor
  H->>A: POST /onboarding/sessions (onboarding_started)
  H->>IDB: record audio (works offline)
  IDB-->>A: POST …/audio when online (offline_captured, captured_at)
  A->>S: transcribe
  A-->>H: transcript (transcript_ready)
  H->>A: POST …/draft
  A->>L: rephrase into TITLE + DESCRIPTION only
  A-->>H: draft + fields_required (draft_generated)
  H->>A: POST …/confirm — host-entered price, season, capacity, accessibility + consent
  Note over A: listing [draft], consent record, active vs elapsed time logged (listing_confirmed)
  V->>A: transition → approved (entry_approved, provenance, audit)
  P->>A: GET /map/features, /listings — visitor role, RLS → approved only
  P->>A: POST /ask
  A->>A: retrieve approved chunks → confidence gate → generate → SUPPORT CHECK per sentence
  A-->>P: answer + citations (answer_served) or refusal (answer_withheld)
```

## How each guarantee is enforced

| Guarantee | Mechanism |
|---|---|
| Only approved content reaches visitors | `CHECK` constraint on status; read-only DB role with row-level security `USING (status='approved')`; explicit `approved_only` filters; `tests/test_validation_gate.py` |
| Unverified facts cannot be published | `facts_verified` flag; the gate refuses to approve; the assistant therefore withholds |
| Answers are attributable | retrieval over approved chunks + per-sentence support check; unsupported sentences dropped; empty answer → withheld |
| Never unsourced text when the budget runs out | `services/budget.guard` → cached answer or "assistant paused"; generation is the only thing that stops |
| No personal data in analytics | keyed HMAC pseudonyms for actor, session and device; no free text in events; answers stored unlinked for review |
| Nothing published below k | primary (k≥5), secondary and small-cell suppression, then a human disclosure review per run |

## Deployment (2 vCPU / 4 GB, no GPU)

| Service | Image | Memory cap | Role |
|---|---|---|---|
| db | pgvector/pgvector:pg16 | 512 MB | content, vectors, events, aggregates |
| redis | redis:7-alpine | 64 MB | job queue |
| ollama (+ pull) | ollama/ollama | 2.2 GB | demo-laptop models (skip when using the EU provider) |
| api | backend/Dockerfile | 1.2 GB | FastAPI + faster-whisper small (int8) |
| worker | backend/Dockerfile | 1.2 GB | transcription jobs |
| scheduler | backend/Dockerfile | 256 MB | nightly KPI run, request expiry |
| web | frontend/Dockerfile | 384 MB | Next.js (standalone) |
| caddy (profile `proxy`) | caddy:2-alpine | – | TLS termination |

With `LLM_PROVIDER=eu_api` and `COMPOSE_PROFILES=` the Ollama service disappears and the stack fits
comfortably in 4 GB.
