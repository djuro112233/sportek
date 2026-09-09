# Security minimum for the demo

| Requirement | Implementation |
|---|---|
| TLS via reverse proxy | `Caddyfile` + compose profile `proxy` (automatic Let's Encrypt for `DOMAIN`, internal CA for localhost); HSTS, nosniff, referrer and permissions policies |
| Rate limiting on public endpoints | `slowapi` limiter (`RATE_LIMIT_PUBLIC`, `RATE_LIMIT_ASK`) on `/api/ask`, `/api/map/*`, `/api/trails/*`, `/api/requests`, `/api/events`, `/api/export/*`, `/api/auth/login` |
| Secrets from env only | `app/config.py` (pydantic-settings); `SECRET_KEY` has no default; `APP_ENV=prod` refuses the `.env.example` placeholder |
| Dependency scanning in CI | `pip-audit` (backend) and `npm audit --audit-level=high` (frontend) in `.github/workflows/vrmac-lh-ci.yml` |
| No PII in logs | `app/logging_conf.py` redacts e-mails and bearer tokens; uvicorn access log disabled; Caddy access log not configured; request log contains method, path, status, duration, request id only |
| Consent records | `consent_records` (host id, ambassador id, session id, consent text version, method, timestamp, withdrawal); a listing cannot be approved without one |
| Pseudonymised analytics | `events` holds no user, session or device id in the clear — only keyed HMAC pseudonyms (`EVENT_PSEUDONYM_KEY`, `app/pseudonym.py`). Rotating the key makes historical pseudonyms unlinkable to new data. No free text (question, message, transcript) is ever written to an event |
| Gender data | recorded only from a voluntary self-report (`POST /api/auth/me/gender`); `undisclosed` and `prefer_not_to_say` are excluded from gender cells and counted as `not_reported` |
| Answer review sample | `answer_records` deliberately carries **no** session, device or actor pseudonym, so the monthly human review sheet cannot be tied back to a person |
| Disclosure control | k≥5 primary suppression, secondary suppression against subtraction, small `date × activity × gender` cells suppressed outright, then a human review before a KPI run is published |
| Model provider | pilot: an EU inference provider under a no-data-retention contract; `APP_ENV=prod` refuses to start with `LLM_PROVIDER=eu_api` unless `LLM_NO_DATA_RETENTION_CONFIRMED=true` |
| Spend cap | every billable call priced into `llm_usage`; at `LLM_MONTHLY_CAP_EUR` generation stops and only cached, cited answers are served |
| Audio | deleted immediately after transcription unless `KEEP_AUDIO=true`; offline recordings live only in the host's own browser until uploaded |
| Passwords | bcrypt (cost 12); JWT HS256, 12 h expiry |
| RBAC on every write | `require_role(...)` dependencies; state-machine role rules in `services/validation.TRANSITIONS`; tests in `tests/test_rbac.py` |
| Audit log | `audit_log` table written on login and every content write |
| Visitor data | anonymous random `session_id` in the browser; no accounts, no IPs stored; audio deleted after transcription (`KEEP_AUDIO=false`) |
| Data-layer gate | read-only DB role with row-level security (see `docs/architecture.md`) |

Out of scope (by the brief): production hardening, WAF, backups, key rotation, multi-tenant isolation.
