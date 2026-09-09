# VRMAC-LH — Vrmac Living Heritage (prototype)

> **Prototype built for the SMART ERA application, September–October 2026. Sample data.**
> Not a product: one real end-to-end path per user journey, no personal data, no payments, no bookings.
> Licence: AGPL-3.0 (`LICENSE`).

One validated source of truth for Gornja Lastva and the Vrmac hill (Tivat, Montenegro): hosts describe their offer
**by voice**, validators (Napredak) approve every item, visitors get **grounded answers with citations or a refusal**,
an **interactive map with directions and GPX trails**, and institutions read **KPIs computed from events only**
(sex-disaggregated, k≥5 suppression). Approved points of interest are exported as **NGSI-LD `PointOfInterest`** and a
**DCAT-AP** dataset description.

## Run in 3 commands

```bash
cp .env.example .env            # or: make env  (also generates a random SECRET_KEY)
docker compose up --build       # db, redis, ollama (+model pull), api, worker, scheduler, web
open http://localhost:3000      # API docs: http://localhost:8000/api/docs
```

First start downloads the small models (Ollama `qwen2.5:1.5b` + `paraphrase-multilingual`, faster-whisper `small`):
a few minutes on a 2 vCPU / 4 GB VPS. Everything runs on CPU. The seed data (public facts with sources, four
fictional providers, sample trails and condition reports, synthetic event history) loads automatically.

Sample accounts (password `prototype123`, see `SEED_PASSWORD`):

| Role | E-mail | App |
|---|---|---|
| host | `host1@example.org` … `host4@example.org` | `/host` |
| ambassador | `ambassador1@example.org` | `/host`, `/validate` |
| validator (Napredak) | `validator1@example.org` | `/validate` |
| institution (read-only) | `institution1@example.org` | `/dashboard` |
| visitor | anonymous | `/visitor` |

## The six innovation claims — where they are real

| # | Claim | Implementation | Proof |
|---|---|---|---|
| 1 | Validation gate: `draft → reviewed → approved \| rejected`, provenance (who, when, version, source); only approved items reach visitors — enforced in the data layer | `backend/app/services/validation.py`, CHECK constraints in `models.py`, **read-only DB role with row-level security** in `db.py` | `backend/tests/test_validation_gate.py`, `test_rbac.py` |
| 2 | Grounded answers or refusal: RAG over approved entries only, citations (entry id + source), `answer_withheld` event | `backend/app/services/rag.py`, `routers/ask.py`, pgvector index of approved entries only (`services/indexing.py`) | `backend/tests/test_grounding.py` — 30 questions (20 answerable, 10 not); results in `docs/test-results/grounding_results.md` |
| 3 | Voice-first onboarding: audio → faster-whisper → LLM extraction → confirm → consent → validation queue → publish (cnr + en); duration measured | `backend/app/services/onboarding.py`, `extraction.py`, `providers/stt.py`, `frontend/app/host` (PWA) | `backend/tests/test_onboarding.py`; `docs/test-results/onboarding_timing.log` |
| 4 | Events → KPIs: every step emits an event; nightly/on-demand job computes the KPI table (sex-disaggregated, k≥5 suppression); dashboard reads aggregates only | `backend/app/events.py`, `services/kpi.py`, `cli.py kpi-schedule`, `frontend/app/dashboard` | `backend/tests/test_kpi.py`; `docs/kpi-definitions.md`, `docs/events.md` |
| 5 | Interactive map and directions: MapLibre GL + OpenStreetMap (optional Google base layer), Google Maps navigation links, GPX trails with the latest condition report, geotagged reports, heat map (k≥5) | `backend/app/services/geo.py`, `routers/map.py`, `trails.py`, `itinerary.py`, `frontend/components/map` | `backend/tests/test_geo.py`, `test_requests.py` |
| 6 | Interoperability stub: NGSI-LD `PointOfInterest` (validated against the Smart Data Models JSON schema) + DCAT-AP | `backend/app/services/export.py`, vendored schemas in `backend/schemas/sdm` | `backend/tests/test_export.py`; `make export` |

Coordinates in the seed data are **approximate** and flagged as such until replaced by K4's surveyed GPX.

## Repository layout

```
vrmac-lh/
├── backend/            FastAPI app (app/), seed data, vendored Smart Data Models schemas, tests
├── frontend/           Next.js apps: /host (PWA), /visitor, /validate, /dashboard
├── docs/               architecture.md (diagram), api-contract.md, grounding.md, kpi-definitions.md,
│                       events.md, interoperability.md, security.md, decisions.md, openapi.json, test-results/
├── docker-compose.yml  full stack; Caddyfile (TLS) behind the `proxy` profile
├── Makefile            make help
├── demo.md             7-minute pitch script
└── .env.example        every setting, documented
```

## Configuration (all via environment, see `.env.example`)

| Variable | Options | Default |
|---|---|---|
| `LLM_PROVIDER` | `ollama` (local open model) · `openai` (any OpenAI-compatible API, e.g. vLLM) · `none` (extractive answers, rule-based extraction) | `ollama` |
| `EMBEDDINGS_PROVIDER` | `ollama` · `sentence-transformers` · `hash` (offline tests) | `ollama` |
| `STT_PROVIDER` | `faster-whisper` (local, CPU) · `api` (Whisper-compatible endpoint) · `fixture` (tests only) | `faster-whisper` |
| `MAPS_PROVIDER` | `osm` (MapLibre + OpenStreetMap) · `google` (needs `GOOGLE_MAPS_API_KEY`) | `osm` |
| `KPI_K_MIN` | k-anonymity threshold for published aggregates | `5` |
| `ONBOARDING_TARGET_MINUTES` | target for a complete listing | `30` |

## Tests

```bash
make venv            # python3.12 -m venv backend/.venv + requirements
make test-backend    # needs PostgreSQL 16 + pgvector; TEST_DATABASE_URL=postgresql+psycopg://vrmac:vrmac@127.0.0.1:5432/vrmac_test
make test-frontend   # tsc + next build
make audit           # pip-audit + npm audit
```

CI (`.github/workflows/vrmac-lh-ci.yml`) runs the backend suite against a `pgvector/pgvector:pg16` service, the
frontend type-check and build, dependency scanning, and `docker compose config`. Test results are published as a
workflow artifact and committed under `docs/test-results/`.

## Deploy on a small EU VPS (2 vCPU / 4 GB, no GPU)

```bash
git clone … && cd vrmac-lh
make env && sed -i 's/^DOMAIN=.*/DOMAIN=vrmac.example.org/; s/^APP_ENV=.*/APP_ENV=prod/' .env
make up-prod         # docker compose --profile proxy up --build -d  → https://vrmac.example.org (Caddy, automatic TLS)
```

Microphone access needs HTTPS (or `localhost`), which is why the Caddy profile exists.

## Useful commands

```bash
make seed            # reload seed data
make kpi             # compute the KPI aggregates now (the scheduler does it nightly at 02:00 UTC)
make export          # NGSI-LD + DCAT-AP files into ./exports (validated against the PointOfInterest schema)
make grounding       # run the 30-question grounding test inside the container
make openapi         # write docs/openapi.json
```

## Explicitly out of scope

Payments, real bookings, real personal data, Orion-LD deployment, languages beyond Montenegrin + English, native
mobile apps, any claim of production readiness. See `docs/decisions.md` for assumptions (reference documents,
citations, model sizes).
