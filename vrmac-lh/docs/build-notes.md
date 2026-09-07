# Build notes for contributors / build agents

Working tree: `/home/user/sportek/vrmac-lh`. Backend in `backend/` (FastAPI, SQLAlchemy 2, PostgreSQL 16 + pgvector),
frontend in `frontend/` (Next.js 15 app router, TypeScript strict, MapLibre GL).

## Local environment (sandbox)
- Python venv: `backend/.venv` → `. backend/.venv/bin/activate` (Python 3.12, all requirements installed).
- PostgreSQL 16 + pgvector runs locally: `postgresql+psycopg://vrmac:vrmac@127.0.0.1:5432/<db>`; the superuser `vrmac`
  may create databases. The visitor role `vrmac_public` already exists.
- Run backend tests from `backend/`: `TEST_DATABASE_URL=postgresql+psycopg://vrmac:vrmac@127.0.0.1:5432/vrmac_test_<name> pytest -q tests/<file>`
  `tests/conftest.py` creates the database if missing, drops/creates the schema, loads the seed, and sets the offline
  providers: `EMBEDDINGS_PROVIDER=hash`, `LLM_PROVIDER=none`, `STT_PROVIDER=fixture`, `QUEUE_MODE=sync`.
  Use a **dedicated database name per test run/agent** — the schema is dropped at session start.
- No network to HuggingFace / Ollama in the sandbox: never try to download models. Real providers are exercised in
  `docker compose` on the user's machine.
- Frontend: `cd frontend && npm run typecheck && npm run build` (node_modules installed).

## Conventions
- Visitor-facing reads: `db: Session = Depends(get_public_db)` **and** `services.validation.approved_only(stmt, Model)`.
- Writes: `Depends(require_role(...))`, then `services.validation.*` / `record_audit(...)`, `emit_event(...)`, `db.commit()`.
- Public endpoints: decorate with `@limiter.limit(settings.rate_limit_public)` (import `limiter` from `app.ratelimit`;
  the endpoint must take `request: Request`).
- Never log or store e-mails, names, IP addresses in events, audit details or logs.
- Both languages everywhere: `*_local` (cnr — Montenegrin, Latin script) and `*_en`.
- Every UI screen shows the prototype banner (already in the root layout) and marks sample data.
