# VRMAC-LH — evidence for the technology-readiness claim

> Prototype built for the SMART ERA application, September–October 2026. Sample data.
> Scale in use: the EU / Horizon Europe scale, where **TRL 4 means "technology validated in laboratory"**.
> Nothing here claims production status, real users, or any level above 4.

This document exists so an evaluator does not have to take the claim on trust. Every row names an artifact
and a command. The evidence was gathered and then adversarially re-checked: 163 candidate items were put to
independent verifiers instructed to refute them. 105 were confirmed as stated, 58 were confirmed but had to
be stated more narrowly, and **none was found to be fabricated**. The narrower statements are the ones used
below.

## 1. The claim, scoped

An unscoped "this prototype is at TRL 4" does not survive questioning. The scoped claim does:

| Component | Level the evidence supports | Why |
|---|---|---|
| Backend governance and data layer: validation gate, role separation and row-level security, pseudonymised events, KPI engine, disclosure control, NGSI-LD and DCAT-AP export | **TRL 4** | Validated by an executed test suite on a third-party runner against a real PostgreSQL 16 + pgvector database |
| Retrieval, citation and refusal behaviour | **TRL 4, with substitute providers** | The pipeline and both controls are executed and measured, but only on hashed lexical features, never on a real embedding model |
| The AI components the project is named for: speech recognition, generative answering, real-model retrieval, the model-judge support check | **TRL 3** | Implemented behind provider interfaces and never executed in any recorded run |
| Browser application: offline capture, the active-time clock, consent screen, map, validator console, dashboard | **Below TRL 4** | No executed test covers it. It is type-checked and built in CI, and demonstrated by screenshot, which is not validation |
| The K01–K23 figures | **No level** | 22 of 23 definitions are self-declared placeholders. No figure from that table should be quoted |

State it that way and every part of it is defensible. State it as a single number and the weakest part
drags the rest down.

## 2. The one artifact that settles the core claim

The suite was executed **off this machine, by GitHub, on the exact submitted commit**. This is not a
self-reported log file.

| | |
|---|---|
| Run | `https://github.com/djuro112233/sportek/actions/runs/34813557579` |
| Job | `Backend tests (PostgreSQL 16 + pgvector)`, id 103879483498 |
| Commit under test | `8ab48497d4b927c738cafa03492a04dffe23d16e` — the branch head itself |
| Conclusion | **success** |
| Finished | 2026-09-14T06:28:56Z |
| Database | `pgvector/pgvector:pg16` service container, started by the runner |
| Result | 236 test cases passed, 0 failed, 0 skipped |

Three other jobs in the same run also passed: `Frontend type-check + build`, `docker compose config`, and
the `pip-audit` step of the dependency scan.

The run's overall badge is red. The failure is one step, `npm audit (frontend)`, which reports a `postcss`
advisory reached through Next.js itself. The only offered fix is a major upgrade to Next.js 16. That is a
breaking change and it was not made before the submission. It touches no code under test, and the backend,
frontend and compose jobs of the same run are green.

### What the runner's own log shows

The CI log is the strongest single piece of evidence because it shows PostgreSQL refusing, in its own
words, on a machine nobody here controls:

```
ERROR:  permission denied for table users
ERROR:  permission denied for table visitor_requests
ERROR:  permission denied for table response_cache
ERROR:  new row for relation "heritage_entries" violates check constraint "ck_heritage_entries_status"
ERROR:  new row for relation "heritage_entries" violates check constraint "ck_heritage_entries_coords"
```

Those lines are the validation gate working. They are produced by tests that deliberately try to break it.

## 3. Evidence for each step of the scale

| Step | What it requires | Artifact |
|---|---|---|
| TRL 1 | Basic principles observed | `docs/architecture.md`, `docs/decisions.md` — the problem statement and the recorded design decisions with their alternatives |
| TRL 2 | Technology concept formulated | `docs/grounding.md`, `docs/events.md`, `docs/kpi-definitions.md`, `docs/interoperability.md` — each mechanism specified before it was built |
| TRL 3 | Experimental proof of concept | Every provider interface with a working implementation: `backend/app/providers/` for language, embeddings, speech and support checking |
| TRL 4 | Technology validated in laboratory | The CI run in section 2, plus the measured grounding protocol in section 4 |

## 4. Evidence per innovation claim

Each row names the test file that validates it. All of them ran inside the passing CI job above.

| Claim | Test file | Cases | What the test actually forces |
|---|---|---|---|
| Validation gate lives in the data layer | `backend/tests/test_validation_gate.py` | 20 | PostgreSQL itself refuses the visitor role, matched on "permission denied", for writes on every readable table and reads on every private one. The private-table list is derived from the model metadata, so a new table is covered without anyone remembering to add it |
| Grounded answers or refusal | `backend/tests/test_grounding.py` | 11 | 60 questions, 40 answerable and 20 unanswerable, across both launch languages |
| Voice onboarding, offline capture, two clocks | `backend/tests/test_onboarding.py` | 40 | Active authoring time and elapsed time are accounted separately; price, dates, capacity and accessibility can only be host-entered; consent is recorded |
| Events to KPIs with disclosure control | `backend/tests/test_kpi.py`, `test_disclosure.py` | 25 | Primary, secondary and small-cell suppression on constructed populations, then on a full run; nothing is published without a human step |
| Map, trails, multi-village itineraries | `backend/tests/test_geo.py`, `test_itinerary.py` | 24 | Coordinates, deep links, GPX, and the latest approved condition report |
| NGSI-LD and DCAT-AP export | `backend/tests/test_export.py` | 22 | Seven deliberately broken entities are each rejected by the vendored Smart Data Models schema, so the validator is proven to be doing work |

The six rows above account for 142 test functions. The remaining 87 cover the foundation: authentication,
role-based access, the territory model, visitor requests, the speech evaluation harness, and the response
cache with its monthly spend cap. Across 15 files there are 229 test functions, which expand to 236 executed
cases. None is skipped and none is marked expected-failure.

### The measured grounding result

Re-run on the current head, it reproduces the stored baseline exactly:

| | Montenegrin | English |
|---|---|---|
| Answered citing an approved entry, the brief's criterion, floor 90 % | 20 / 20 | 20 / 20 |
| The same, and carrying the decisive facts of the expected answer | 20 / 20 | 19 / 20 |
| Unanswerable questions withheld | 10 / 10 | 10 / 10 |

The one strict failure is question `en-a17`. The answer is correct but incomplete: it names one of the two
churches. It is published rather than tuned away.

## 5. What this evidence does not support

An evaluator will ask these. Better that the answers are already written down.

- **The AI is never run.** Every recorded run substitutes the configured providers: hashed lexical features
  instead of an embedding model, extraction instead of generation, fixture transcripts instead of speech, a
  deterministic support check instead of the model judge. The retrieval threshold used in the measurement,
  0.35, is the one calibrated for the hash provider; every real provider uses 0.60. The grounding numbers
  therefore do not transfer as they stand.
- **The speech figure measures a text file.** The five word-error-rate samples are two-second tone files
  with hand-written transcripts. No real voice has been recorded.
- **The stack has never been started.** CI parses the compose file; it does not build an image or run a
  container. The "fits a 2 vCPU / 4 GB machine" figure is arithmetic over declared limits, never measured.
- **The browser half is untested.** The frontend test script is a type-check. The offline queue, the active
  timer and the consent screen are validated by nothing executable.
- **The KPI definitions are placeholders.** SIP Draft §11 was not available. The dashboard says so on the
  screen and every stored aggregate carries the flag.
- **The corpus is a fixture.** Fifteen heritage entries, eleven approved, ten of them in one village. Four
  sample providers. The Kotor-side village is an unverified draft and cannot be approved, so cross-municipality
  itineraries are unexercised.
- **No independent party has touched any of it.** The corpus, the questions, the expected answers, the tests
  and this record were produced by one build process.
- **Assurance work a funder reads alongside a TRL claim is absent:** no data-protection impact assessment,
  no accessibility audit, no threat model, no penetration test, no software bill of materials, no dependency
  licence audit, and no named copyright holder in `LICENSE`.

## 6. What TRL 5 would require

TRL 5 is validation in a relevant environment. The gap is specific:

1. Re-run the 60-question protocol and the suite on the configured providers, and recalibrate the threshold.
2. Build and start the stack in CI, drive a smoke test over HTTP, and record its real memory and latency.
3. Obtain a question set written by someone who did not write the entries, and hold it out of calibration.
4. Measure the word error rate on consented recordings of elderly Montenegrin speakers.
5. Transcribe SIP Draft §11 into the definition file, recompute, and only then quote a KPI figure.
6. Add a frontend test runner covering offline capture, reload mid-upload, and the active-time clock.
7. Run a real validator workload at Expeditio and record time-to-decision and rejection rates.
8. Commission a data-protection assessment, an accessibility audit and an external security review.

None of these changes the architecture. Each replaces a substitute or a placeholder with the real input.

## 7. How to check all of this in five commands

```bash
git clone https://github.com/djuro112233/sportek && cd sportek/vrmac-lh
git checkout 8ab48497d4b927c738cafa03492a04dffe23d16e

make venv
TEST_DATABASE_URL=postgresql+psycopg://vrmac:vrmac@127.0.0.1:5432/vrmac_check make test-backend
cd backend && python -m app.cli grounding-test
```

The CI evidence needs no clone at all. Open the run URL in section 2.
