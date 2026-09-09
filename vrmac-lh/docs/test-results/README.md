# Test results

Artefacts in this directory are produced by the test suite and the CLI, not written by hand.

| File | Produced by | What it shows |
|---|---|---|
| `grounding_results.json` + `grounding_results.md` | `pytest tests/test_grounding.py` or `make grounding` | every question of the 20 + 10 set, per language, with the outcome, confidence, cited entries, supported and dropped sentences, and the similarity distributions behind the thresholds |
| `onboarding_timing.log` | `services/onboarding.py` on every confirmation | one line per confirmed listing: active authoring time, elapsed time, within-target flag, offline capture, providers |
| `junit.xml` | CI only (`pytest --junitxml`) | the full backend suite, uploaded as a workflow artifact; it is not produced by a local run |
| (no file) | `make stt-eval` | the word error rate is written to the `stt_evaluations` table and read back through `GET /api/kpi/quality`; the command prints the summary but writes no artefact |

The validation-gate proof is the test suite itself (`backend/tests/test_validation_gate.py`,
`test_rbac.py`, `test_villages.py`); it has no separate artefact because a passing run is the evidence.

Regenerate everything with `make test-backend` (or `make grounding` for the grounding set alone).
