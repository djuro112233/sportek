# VRMAC-LH — TRL 4 baseline record

> Prototype built for the SMART ERA application, September–October 2026. Sample data.
> This record is held by the orchestrator and is available to reviewers. It describes a laboratory-validated
> prototype (TRL 4). It makes no claim of production status, real users, or any higher readiness level.

## Identity

| | |
|---|---|
| Repository | `djuro112233/sportek`, directory `vrmac-lh/` |
| Branch | `claude/vrmac-living-heritage-prototype-l3lxnl` |
| Commit | `7b9cdfa369e04e6ab6f75240127ac3815c60ac1f` |
| Tag | `vrmac-baseline-2026-09` — annotated, "TRL 4 baseline for SMART ERA application", on the commit above; **local only, see below** |
| Record date | 2026-09-14 (UTC) |
| Licence | AGPL-3.0-only |

The tag points at the revision that was tested. This record and its reports are committed immediately after
it, so the tagged code is exactly what the reports describe.

**The commit hash is the authoritative identity.** The tag object was created in the build session but could
not be pushed from it: that session's credential accepts only the working branch, and refused the tag ref
with HTTP 403. Anyone with push rights publishes it in one command, from a clone that has the branch:

```bash
git tag -a vrmac-baseline-2026-09 7b9cdfa369e04e6ab6f75240127ac3815c60ac1f \
  -m "TRL 4 baseline for SMART ERA application"
git push origin vrmac-baseline-2026-09
```

Until that is done, quote the commit hash rather than the tag.

## Environment in which the reports were produced

| Component | Version |
|---|---|
| OS | Ubuntu 24.04.4 LTS, Linux 6.18.44 x86_64 |
| Python | 3.12.3 (virtualenv `backend/.venv`) |
| Node.js / npm | v22.22.2 / 10.9.7 |
| Docker / Compose | 29.3.1 / v5.1.1 (compose file validated with `docker compose config`; no daemon was available in this environment, so the stack itself was not started here) |
| PostgreSQL | 16.13 with pgvector 0.6.0, local cluster |

## Exact commands to reproduce

```bash
git clone https://github.com/djuro112233/sportek && cd sportek
git checkout 7b9cdfa369e04e6ab6f75240127ac3815c60ac1f   # or the tag, once it is published
cd vrmac-lh

# The full stack (needs Docker; downloads the small local models on first start):
make env && docker compose up --build        # web http://localhost:3000, API docs http://localhost:8000/api/docs

# The tests, as run for this record (needs PostgreSQL 16 + pgvector; TEST_DATABASE_URL points at an empty database):
make venv
TEST_DATABASE_URL=postgresql+psycopg://vrmac:vrmac@127.0.0.1:5432/vrmac_baseline_tests make test-backend
make test-frontend                            # tsc --noEmit + next build

# The grounding test:
make grounding                                # inside the compose stack, or
cd backend && python -m app.cli grounding-test   # against a seeded database, as run for this record
```

`make test` runs `test-backend` and `test-frontend` together.

## Inputs

| Input | Path |
|---|---|
| Villages (territory reference data) | `backend/seed_data/villages.json` |
| Heritage entries (public facts, with source citations) | `backend/seed_data/heritage_entries.json` |
| Sample providers (fictional, marked "sample") | `backend/seed_data/listings.json` |
| Trail segments and condition reports | `backend/seed_data/trails.json`, `backend/seed_data/gpx/donja-gornja-lastva.gpx` |
| Sample accounts (fictional) | `backend/seed_data/users.json` |
| Speech-to-text fixtures (synthetic, tests only) | `backend/seed_data/stt_fixtures/`, `backend/seed_data/stt_eval_set.json` |
| Grounding question sets, one per launch language | `backend/seed_data/grounding_questions.cnr.json`, `backend/seed_data/grounding_questions.en.json` |
| KPI definitions (provisional placeholders, see limitations) | `backend/kpi_definitions/sip_section_11.json` |
| Vendored Smart Data Models schemas (offline validation) | `backend/schemas/sdm/` |

## Actual outputs

| Output | Path | Result |
|---|---|---|
| Full backend test suite, verbatim | `docs/baseline/test_report.txt` | **236 passed**, 0 failed |
| Grounding test, verbatim | `docs/baseline/grounding_report.txt` | see below |
| Validation console (validator signed in, queue visible) | `docs/baseline/screenshot_validation_console.png` | signed in as the sample validator account; 6 items waiting, three of them flagged "unverified facts", including the draft `Legend of the golden bell of Vrmac` |
| A withheld answer (question answerable only from a non-approved draft) | `docs/baseline/screenshot_withheld_answer.png` | question `en-u01`, "Where was the golden bell of Vrmac hidden in 1687?", withheld: no source attached, the reason stated, confidence 0.18, providers `none` / `hash` / `lexical` named in the footer |
| Frontend type-check and production build | (not stored) | clean; 13 routes build |

Both screenshots were taken in a headless Chromium (Playwright 1.56) against the API and the production
web build of this revision, seeded with the sample data and running the offline substitute providers. The
interface is shown in English; the Montenegrin one renders the same screens.

The two read together. The draft entry `SAMPLE (draft): Legend of the golden bell of Vrmac` is visible in
the validation queue, waiting for a decision and flagged "unverified facts". The visitor question whose
only possible source is that draft is refused, with no source attached and the reason stated. This is the
validation gate and the refusal path shown on the same data, from the two sides.

Grounding test, per launch language, with the offline substitute providers:

| | Montenegrin (`cnr`) | English (`en`) |
|---|---|---|
| answerable questions answered citing an approved entry (the brief's criterion) | 20 / 20 | 20 / 20 |
| the same, and carrying the decisive facts of the expected answer (strict criterion) | 20 / 20 | 19 / 20 |
| unanswerable questions withheld | 10 / 10 | 10 / 10 |

The one strict failure (`en-a17`, "Which churches does the village of Gornja Lastva have?") is answered
correctly but incompletely: the served answer names St Mary and not St Vitus. It is documented in
`docs/grounding.md` and left visible rather than tuned away. The brief's floor is 90 % answered and 100 %
withheld; both languages pass on both criteria.

## Components implemented end-to-end at this revision

1. **Validation gate in the data layer.** Every content item carries `status ∈ {draft, reviewed, approved,
   rejected}`, a version and a provenance trail. The visitor side reads the database as a separate role with
   `SELECT` only and row-level security limited to approved rows; services filter explicitly as well; `CHECK`
   constraints hold the status vocabulary. Content whose facts are marked unverified cannot be approved.
   Proof: `backend/tests/test_validation_gate.py`, `test_rbac.py`, `test_villages.py`.
2. **Retrieval with citation and refusal.** Questions are answered only from approved entries, with citations
   (entry id, version, source string). Two controls: human approval before publication, and a per-sentence
   support check that drops any sentence not attributable to a cited passage; an empty answer is withheld
   and logged as `answer_withheld`. Response cache invalidated on entry version change; monthly spend cap
   enforced in code on every paid call. Proof: `test_grounding.py`, `test_cache_and_cap.py`.
3. **Voice onboarding flow.** Browser recording with offline capture (IndexedDB queue, upload on
   reconnection), speech-to-text behind a provider interface, model-drafted title and description only,
   host-entered and host-confirmed price, season, capacity and accessibility, consent record, validation
   queue, publication in Montenegrin and English. Active authoring time and elapsed time logged separately.
   Proof: `test_onboarding.py`, `test_stt_eval.py`; exercised in a headless browser during verification.
4. **Event logging → KPI engine.** Every step emits a pseudonymised event (keyed HMAC; no identifier in the
   clear). A job computes K01–K23 from the definition file, applies primary, secondary and small-cell
   suppression, and publishes nothing until a human disclosure review. Proof: `test_kpi.py`,
   `test_disclosure.py`, `test_foundation.py`.
5. **Interactive map, directions, trails.** Every approved item has WGS84 coordinates on a MapLibre GL /
   OpenStreetMap map; Google Maps navigation deep links; GPX trails with the latest approved condition
   report; multi-village itineraries. Proof: `test_geo.py`, `test_itinerary.py`, `test_requests.py`.
6. **NGSI-LD export.** Approved points of interest as Smart Data Models `PointOfInterest`, validated offline
   against the vendored JSON schema, plus a DCAT-AP dataset description. Proof: `test_export.py`.

## Explicit limitations of this baseline

- **Substitute providers.** Every figure above was produced with the offline substitutes:
  `EMBEDDINGS_PROVIDER=hash` (hashed lexical features instead of a multilingual embedding model),
  `LLM_PROVIDER=none` (extractive answers instead of a generated one), `SUPPORT_CHECK_PROVIDER=lexical`
  (a deterministic check instead of the model judge), `STT_PROVIDER=fixture`. The EU inference provider,
  the self-hosted model path and faster-whisper are implemented but were **not** exercised in this
  environment, which has no network access to model services. Retrieval thresholds are calibrated for the
  hash provider and will need recalibration with a real embedding model.
- **Speech fixtures.** The five word-error-rate samples are synthetic 2-second tone files with fixture
  transcripts. The reported error rate measures the fixture, not speech recognition. No real voice sample
  exists yet.
- **Single-locality corpus.** Eleven approved heritage entries, all about Gornja Lastva and its
  surroundings on the Tivat side. The Kotor side (Gornji Stoliv) is seeded as an unverified draft because
  its public sources could not be checked from the build environment; it cannot be approved and is
  withheld by design. Multi-village itineraries therefore span villages within one municipality.
- **Question sets written by the same authors.** The 60 grounding questions and their expected answers were
  prepared by the same party that wrote the seed entries. The brief calls for independently prepared
  expected answers; that has not happened yet.
- **KPI definitions are provisional.** SIP Draft §11 was not available to this build. Twenty-two of the
  twenty-three definitions are placeholders flagged `provisional` in the definition file and on the
  dashboard; only K11's rule comes from the brief. No figure from the KPI table should be quoted until the
  file is replaced with the §11 wording.
- **Sample data throughout.** All accounts, providers and event history are fictional; the event history is
  synthetic and flagged as such.
- **Not started as a container stack here.** `docker compose config` validates, and the images were
  reviewed, but the stack was not run in this environment.

## Planned before the pitch

| Item | Purpose |
|---|---|
| Run the stack with real models (EU inference provider or the local profile) and repeat `make grounding` | replace the substitute-provider figures; recalibrate thresholds |
| Word error rate on 5 real, consented recordings of elderly Montenegrin speakers | replace the fixture-based figure |
| An independent 20 + 10 question set per language, written by someone who did not write the entries | satisfy the brief's independence requirement |
| Verify Gornji Stoliv against public sources and approve its entry | unlock cross-municipality content and itineraries |
| Transcribe SIP Draft §11 into `kpi_definitions/sip_section_11.json` | make the KPI table quotable |
| Record one real host voice sample in Montenegrin | the live host-flow demonstration |

None of these changes the architecture; each replaces a substitute or a placeholder with the real input.
