# VRMAC-LH — Vrmac Living Heritage (prototype)

> **Prototype built for the SMART ERA application, September–October 2026. Sample data.**
> One real end-to-end path per user journey. No personal data, no payments, no bookings.
> No claim of production status, users or technology-readiness level is made anywhere in this repository.
> Licence: AGPL-3.0 (`LICENSE`).

The territory is the **rural plateau of Vrmac on both sides of the ridge** — Gornja Lastva, Donja Lastva,
the St Vitus area and Tivat on the Tivat side, Gornji Stoliv and Pasiglav on the Kotor side — not a single
village. Hosts describe their offer **by voice** (offline-capable), validators (Napredak) approve every
item, visitors get **grounded answers with citations or an honest refusal**, an **interactive map with
directions and GPX trails**, and institutions read **KPIs computed from pseudonymised events**, published
only after a disclosure review.

## Run in 3 commands

```bash
make env                        # .env from .env.example with random SECRET_KEY and EVENT_PSEUDONYM_KEY
docker compose up --build       # db, redis, ollama (+ model pull), api, worker, scheduler, web
open http://localhost:3000      # API docs: http://localhost:8000/api/docs
```

The shipped configuration runs entirely on your machine (Ollama `qwen2.5:1.5b` + `paraphrase-multilingual`,
faster-whisper `small`, all CPU) so the demo needs no API key. First start downloads those small models.
For the pilot, switch to the EU inference provider — see **Model providers** below.

Sample accounts (password `prototype123`, see `SEED_PASSWORD`):

| Role | E-mail | App |
|---|---|---|
| host | `host1@example.org` … `host4@example.org` | `/host` |
| ambassador | `ambassador1@example.org` | `/host`, `/validate` |
| validator (Napredak) | `validator1@example.org` | `/validate` |
| institution (read-only) | `institution1@example.org` | `/dashboard` |
| visitor | anonymous | `/visitor` |

## The six innovation claims — where each one is real

| # | Claim | Implementation | Proof |
|---|---|---|---|
| 1 | **Validation gate**: `draft → reviewed → approved \| rejected`, provenance (who, when, version, source); only approved items reach visitors, enforced in the data layer | `backend/app/services/validation.py`; `CHECK` constraints in `models.py`; a read-only PostgreSQL role with **row-level security** (`db.py`) | `tests/test_validation_gate.py`, `test_rbac.py`, `test_villages.py` |
| 2 | **Grounded answers or refusal**, with two real controls: human approval, and a per-answer **support check** that drops any sentence not attributable to a cited approved passage | `services/rag.py`, `providers/support.py`, `routers/ask.py`; pgvector index of approved entries only | `tests/test_grounding.py` — 20 answerable + 10 unanswerable **per language**: 10/10 withheld in both, and answered 20/20 (cited) or 20/20 and 19/20 (strict, see `docs/grounding.md`) |
| 3 | **Voice-first onboarding**, offline-capable; the model drafts **title and description only** — price, season, capacity and accessibility are host-entered and host-confirmed; active authoring time and elapsed time logged separately | `services/onboarding.py`, `services/extraction.py`, `frontend/app/host` (PWA + IndexedDB queue) | `tests/test_onboarding.py`; `docs/test-results/onboarding_timing.log` |
| 4 | **Events → KPIs**: every step emits a *pseudonymised* event; K01–K23 are computed from the definition file and published only after a **disclosure review** (k≥5 plus small-cell suppression); gender only from voluntary self-report | `app/events.py`, `app/pseudonym.py`, `services/kpi.py`, `services/disclosure.py`, `frontend/app/dashboard` | `tests/test_kpi.py`, `tests/test_disclosure.py`; `docs/kpi-definitions.md` |
| 5 | **Map and directions**: MapLibre GL + OpenStreetMap (optional Google layer), Google Maps navigation links, GPX trails with the latest geotagged condition report, heat map (k≥5), multi-village itineraries | `services/geo.py`, `routers/map.py`, `trails.py`, `itinerary.py`, `frontend/components/map` | `tests/test_geo.py`, `test_itinerary.py`, `test_requests.py` |
| 6 | **Interoperability**: NGSI-LD `PointOfInterest` (Smart Data Models, schema-validated offline) + DCAT-AP | `services/export.py`, vendored schemas in `backend/schemas/sdm` | `tests/test_export.py`; `make export` |

Seed coordinates are **approximate** and flagged as such until replaced by K4's surveyed GPX.

## Honest limitations (read `docs/decisions.md`)

* **K01–K23 are provisional.** SIP Draft §11 was not available to this build, so the definition file
  `backend/kpi_definitions/sip_section_11.json` carries placeholder definitions, each flagged
  `provisional`, and the dashboard shows a warning banner. The engine executes that file: replace the
  definitions and every figure changes with no code change. Only K11 follows a definition given in the brief.
* **Gornji Stoliv is unverified.** Public sources were unreachable from the build environment, so its
  village row and its heritage entry are marked unverified and stay in the validation queue. Nothing
  unverified can be approved, and the assistant withholds answers about it — by design.
* The speech-to-text word-error-rate set is five **synthetic** stand-ins until consented recordings of
  elderly Montenegrin speakers replace them.
* Sample providers are fictional; all photos are SVG placeholders.

## Model providers

| Variable | Options | Shipped default |
|---|---|---|
| `LLM_PROVIDER` | `eu_api` (pilot: open-weight model, pay-per-use from an EU provider with a no-data-retention contract) · `ollama` / `vllm` (self-hosted) · `none` (extractive answers only) | `ollama` |
| `EMBEDDINGS_PROVIDER` | `eu_api` · `ollama` · `sentence-transformers` · `hash` (offline tests) | `ollama` |
| `STT_PROVIDER` | `eu_api` · `faster-whisper` (local CPU) · `fixture` (tests) | `faster-whisper` |
| `SUPPORT_CHECK_PROVIDER` | `llm_judge` (on top of the lexical gate) · `lexical` (deterministic) | `llm_judge` |
| `LLM_MONTHLY_CAP_EUR` | monthly spend cap enforced in code | `50` |
| `MAPS_PROVIDER` | `osm` (MapLibre + OpenStreetMap) · `google` (needs a key) | `osm` |
| `KPI_K_MIN` / `K11_DEDUP_DAYS` | disclosure threshold / device deduplication window | `5` / `180` |

`APP_ENV=prod` refuses to start with a placeholder secret, without `EVENT_PSEUDONYM_KEY`, or with
`LLM_PROVIDER=eu_api` unless the no-data-retention contract is confirmed.

## Repository layout

```
vrmac-lh/
├── backend/            FastAPI app, seed data, KPI definition file, vendored Smart Data Models schemas, tests
├── frontend/           Next.js: /host (PWA), /visitor, /validate, /dashboard
├── docs/               architecture, api-contract, grounding, onboarding, kpi-definitions, events,
│                       interoperability, map-and-directions, security, decisions, openapi.json, test-results/
├── docker-compose.yml  full stack; Caddyfile (TLS) behind the `proxy` profile
├── Makefile            make help
├── demo.md             7-minute pitch script
└── .env.example        every setting, documented
```

## Tests

```bash
make venv            # python3.12 venv + requirements
make test-backend    # needs PostgreSQL 16 + pgvector (TEST_DATABASE_URL)
make test-frontend   # tsc + next build
make audit           # pip-audit + npm audit
```

CI (`.github/workflows/vrmac-lh-ci.yml`) runs the backend suite against `pgvector/pgvector:pg16`, the
frontend type-check and build, dependency scanning and `docker compose config`, and publishes the test
results as an artifact.

## Useful commands

```bash
make seed            # reload seed data
make kpi             # compute KPI aggregates (the scheduler runs nightly at 02:00 UTC)
make grounding       # grounding test, per language
make review-sample   # monthly human review sheet: 30 random answers as CSV
make stt-eval        # speech-to-text word error rate
make budget          # this month's model spend against the cap
make export          # NGSI-LD + DCAT-AP into ./exports
make openapi         # docs/openapi.json
```

## Deploy on a small EU VPS (2 vCPU / 4 GB, no GPU)

```bash
make env && sed -i 's/^DOMAIN=.*/DOMAIN=vrmac.example.org/; s/^APP_ENV=.*/APP_ENV=prod/' .env
make up-prod         # docker compose --profile proxy up -d  → https://vrmac.example.org (automatic TLS)
```

Microphone access needs HTTPS (or `localhost`), which is what the Caddy profile provides.

## Out of scope

Payments, real bookings, real personal data, an Orion-LD deployment, languages beyond Montenegrin and
English, native mobile apps, and any claim of production readiness.
