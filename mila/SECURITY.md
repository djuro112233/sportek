# Security policy

MILA handles questions about reproductive and maternal health, sometimes from minors. A
security weakness here is also a privacy and safety weakness, so we treat reports with the
same priority as a clinical incident.

## Reporting a vulnerability

- **Do not open a public issue** for anything that could expose user data, bypass consent, or
  make MILA give unsafe content.
- Use GitHub's private vulnerability reporting on this repository ("Report a vulnerability"
  under the Security tab). If that is unavailable, contact a maintainer listed in the
  repository's commit history and ask for a private channel before sending details.
- Include: the affected endpoint or module, steps to reproduce, the impact you believe it has,
  and whether any real user data was involved. Please do not test against a pilot deployment
  with real users; use a local `docker compose up` stack.
- We acknowledge reports within 3 working days and aim to ship a fix or mitigation within 30
  days for anything that affects user data, consent or safety behaviour. We will credit you in
  the release notes unless you ask us not to.

## Scope

In scope:

- The backend API (`backend/app`), including consent enforcement, session deletion, rate
  limiting, admin endpoints, metrics suppression and the redaction filter.
- The web UI (`web/`), including anything that could leak a session id, transcript or audio.
- The answer pipeline: anything that lets content reach the user without a citation, bypasses
  the red-flag router or the validation gate, or injects instructions through a knowledge-base
  document (prompt injection via sources is explicitly in scope).
- The ingestion scripts and the manifest (for example, path traversal or unsafe file handling).
- The container configuration in this repository.

Out of scope:

- Vulnerabilities in third-party model servers, model weights or hosting platforms that are
  not configured by this repository.
- Denial of service by volume against a self-hosted instance beyond the per-session rate limit.
- Reports that require a compromised host or a malicious maintainer.
- Clinical correctness of source documents (report those through the process in
  `docs/safety.md`).

## Hardening summary

| Control | Where |
|---|---|
| Containers run as a non-root user, with `cap_drop: [ALL]`, `no-new-privileges:true` and a read-only root filesystem; writable paths are explicit volumes or `tmpfs` | `docker-compose.yml`, see `docs/architecture.md`, Deployment |
| No secrets in the repository: `.env` files are git-ignored; `MILA_LLM_API_KEY` and `MILA_ADMIN_TOKEN` come from the environment only | `.gitignore`, `backend/app/config.py` |
| Admin endpoints are disabled (404) unless `MILA_ADMIN_TOKEN` is set; they require `X-Admin-Token` | `backend/app/api/deps.py` |
| Log redaction filter masks API keys, bearer tokens, e-mails, phone numbers, 13-digit identifiers and IP addresses on every record | `backend/app/core/privacy.py` (`RedactionFilter`) |
| Unhandled errors return a generic body; internals and user text never reach the client | `backend/app/main.py` |
| Rate limiting per session id (sliding window, `MILA_RATE_LIMIT_PER_MINUTE`); IPs are not used as keys and are not stored | `backend/app/main.py` (`_RateLimiter`) |
| Security headers on every response: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Cache-Control: no-store`, `Permissions-Policy: camera=(), geolocation=()` | `backend/app/main.py` |
| CORS restricted to `MILA_CORS_ORIGINS`; only `GET`, `POST`, `DELETE` and the two needed headers | `backend/app/main.py` |
| Uploaded audio is written to `MILA_AUDIO_TMP_DIR` and overwritten and unlinked right after transcription | `backend/app/core/privacy.py` (`secure_delete`) |
| Consent required (403) before `/api/ask` and `/api/transcribe`; sessions are random 192-bit ids | `backend/app/api/deps.py`, `backend/app/core/privacy.py` |
| LLM requests to OpenAI-compatible endpoints carry `store=false`; no retries that could duplicate user text | `backend/app/services/llm.py` |
| Knowledge-base text is treated as data: the verifier and gate apply to every generated sentence regardless of what a source says, and adversarial tests cover injected instructions | `backend/app/core/verifier.py`, `backend/app/core/gate.py`, `backend/tests/adversarial/` |

## Supported versions

| Version | Supported |
|---|---|
| `main` branch | Yes: security fixes land here first |
| `v0.1.x` (including `v0.1.0-unicef`) | Yes, for the duration of the pilot |
| Anything older | No |

MILA is a prototype. Do not expose a deployment to the public internet without a reverse proxy
that terminates TLS, without `MILA_APP_ENV=prod`, and without having read
`docs/data-protection.md`.
