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

## Local environment refresher (September 2026 rebuild)
- PostgreSQL may be stopped when a session starts: `pg_ctlcluster 16 main start` (superuser `vrmac`,
  password `vrmac`, on 127.0.0.1:5432). `init_db(drop=True)` now recreates the whole `public` schema.
- Model downloads are impossible in this sandbox (HuggingFace, Ollama and Wikipedia are blocked by the
  egress policy). Tests must run with `EMBEDDINGS_PROVIDER=hash`, `LLM_PROVIDER=none`,
  `SUPPORT_CHECK_PROVIDER=lexical`, `STT_PROVIDER=fixture`, `QUEUE_MODE=sync`.

## What changed with the expanded brief (read before writing code)
1. **Territory**: `Village` (slug, names, municipality Tivat|Kotor, ridge_side, approximate coordinates,
   `facts_verified`). `village_id` is mandatory on heritage entries, listings and trail segments; trail
   segments also carry `village_slugs` for the villages they connect. Events carry `village_id` and
   `municipality`.
2. **Gender**: `User.gender` + `gender_self_reported`. Only a voluntary self-report is disaggregated;
   `undisclosed` and `prefer_not_to_say` are excluded from gender cells.
3. **Events are pseudonymised**: no user id, session id or device id in the clear — `actor_pseudonym`,
   `session_pseudonym`, `device_pseudonym` via `app/pseudonym.py`. Never add a free-text field.
4. **Support check**: `app/providers/support.py` decides whether an answer sentence is attributable to a
   cited passage. `lexical` is deterministic (numbers gate + stem coverage) and is what CI runs.
5. **Spend cap**: `app/services/budget.py` (`guard`, `record`, `status`). Paid calls must be guarded;
   when the cap is reached, serve cache or pause — never unsourced text.
6. **Response cache**: `response_cache` table (exact hash + semantic vector + `entry_versions`).
7. **KPIs**: `backend/kpi_definitions/sip_section_11.json` holds K01–K23 with machine-readable `spec`s,
   all flagged `provisional` because SIP Draft §11 was not available. The engine must read the file and
   never hard-code a definition. Runs need a disclosure review before they are published.
8. **Onboarding**: the model drafts title and description only; price, season, capacity and accessibility
   are host-entered and confirmed. Active authoring time and elapsed time are logged separately, and
   recordings can be captured offline (IndexedDB) and uploaded later.
