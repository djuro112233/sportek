# Security minimum for the demo

| Requirement | Implementation |
|---|---|
| TLS via reverse proxy | `Caddyfile` + compose profile `proxy` (automatic Let's Encrypt for `DOMAIN`, internal CA for localhost); HSTS, nosniff, referrer and permissions policies |
| Rate limiting on public endpoints | `slowapi` limiter (`RATE_LIMIT_PUBLIC`, `RATE_LIMIT_ASK`) on `/api/ask`, `/api/map/*`, `/api/trails/*`, `/api/requests`, `/api/events`, `/api/export/*`, `/api/auth/login` |
| Secrets from env only | `app/config.py` (pydantic-settings); `SECRET_KEY` has no default; `APP_ENV=prod` refuses the `.env.example` placeholder |
| Dependency scanning in CI | `pip-audit` (backend) and `npm audit --audit-level=high` (frontend) in `.github/workflows/vrmac-lh-ci.yml` |
| No PII in logs | `app/logging_conf.py` redacts e-mails and bearer tokens; uvicorn access log disabled; Caddy access log not configured; request log contains method, path, status, duration, request id only |
| Consent records | `consent_records` (host id, ambassador id, session id, consent text version, method, timestamp); a listing cannot be approved without one |
| Passwords | bcrypt (cost 12); JWT HS256, 12 h expiry |
| RBAC on every write | `require_role(...)` dependencies; state-machine role rules in `services/validation.TRANSITIONS`; tests in `tests/test_rbac.py` |
| Audit log | `audit_log` table written on login and every content write |
| Visitor data | anonymous random `session_id` in the browser; no accounts, no IPs stored; audio deleted after transcription (`KEEP_AUDIO=false`) |
| Data-layer gate | read-only DB role with row-level security (see `docs/architecture.md`) |

Out of scope (by the brief): production hardening, WAF, backups, key rotation, multi-tenant isolation.
