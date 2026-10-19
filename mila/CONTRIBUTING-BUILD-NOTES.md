# Build notes for contributors / agents (temporary; merged into README at the end)

- Python venv: `.venv/bin/python` (3.11). Run tests: `.venv/bin/python -m pytest backend/tests -q`.
- Lint: `.venv/bin/ruff check backend scripts`.
- Imports are rooted at `backend/` (pytest `pythonpath = backend`).
- Do not add dependencies without a reason; stdlib + numpy are preferred for v0.1.
- Tests never need network, GPU, or model downloads. Real providers are lazy-imported.
- Never store question text in `Event`. Never log raw user text.
