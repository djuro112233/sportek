# Test results

Artefacts in this directory are produced by the test suite and the CLI, not written by hand.

| File | Produced by | What it shows |
|---|---|---|
| `grounding_results.cnr.json` / `.en.json` + `.md` | `pytest tests/test_grounding.py` or `make grounding` | every question of the 20 + 10 set per language, the outcome, confidence, cited entries, supported and dropped sentences, and the similarity distribution behind the thresholds |
| `onboarding_timing.log` | `services/onboarding.py` on every confirmation | one line per confirmed listing: active authoring time, elapsed time, within-target flag, offline capture, providers |
| `junit.xml` | CI (`pytest --junitxml`) | the full backend suite, uploaded as a workflow artifact |
| `stt_wer.json` | `make stt-eval` | word error rate per sample and the mean, with the synthetic-sample warning |

The validation-gate proof is the test suite itself (`backend/tests/test_validation_gate.py`,
`test_rbac.py`, `test_villages.py`); it has no separate artefact because a passing run is the evidence.

Regenerate everything with `make test-backend` (or `make grounding` for the grounding set alone).
