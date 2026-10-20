# Data protection

MILA is designed so that there is very little to protect: no accounts, no question text, no
audio after transcription, no IP addresses. This document is the data map that the code in
`backend/app/core/privacy.py`, `backend/app/core/events.py` and `backend/app/models/entities.py`
enforces, the consent model, the legal alignment and the DPIA skeleton for the pilot.

## 1. Data map

| Data item | Where | When written | Content | Retention | Legal basis | Deletion |
|---|---|---|---|---|---|---|
| Session | `sessions` table | `POST /api/consent` with `accepted: true` | random 192-bit id, created time, `lang`, `script`, `region` (`BA`/`ME`), `is_minor` (yes/no only), consent flags, consent version and time | Until the user deletes it or the maintainers purge at the end of the pilot; no automatic timer in v0.1 | Consent (GDPR Art. 6(1)(a)); the record is the proof of consent | `DELETE /api/session/{id}` ("Delete my data" button), `delete_session_data` |
| Event | `events` table | Every `ask`, `redflag`, `consent`, `transcribe`, `speak`, `referral_view`, `delete` | type, time, `lang`, `topic_class`, `outcome`, `latency_ms`, `support_ratio`, `redflag_category`, `input_mode`, small non-identifying `payload` | Same as the session; events without a session id are kept as aggregates | Explicit consent for health-related categories (Art. 9(2)(a)); pseudonymised | Deleted with the session; aggregate rows without session id cannot be linked to anyone |
| Gate record | `gate_records` table | Every generated answer | decision, reasons, ratios, counts, gate version; linked to an event id | Same as events | Legitimate interest in auditing safety behaviour; contains no personal data by itself | Deleted with the session's events |
| Saved question | `saved_questions` table | Only when the session has `consent_save_questions=true`, on each answer | question text, language, outcome | With the session | Explicit, separate consent (Art. 9(2)(a)); off by default | Deleted with the session (cascade) |
| Audio upload | File in `MILA_AUDIO_TMP_DIR` (tmpfs in compose) | `POST /api/transcribe` | the recording | Seconds: overwritten and unlinked by `secure_delete` right after transcription, also on error | Consent | Automatic |
| Transcript | Memory only; returned in the HTTP response | `POST /api/transcribe` | recognised text, language, confidence | Not stored | Consent | n/a |
| Synthesised audio | Memory only; returned by `POST /api/speak`, or held in process memory behind a one-time `GET /api/audio/{token}` URL when an answer was requested with audio | On request | WAV bytes of an answer | Served once, then dropped; unused tokens expire after 300 s; at most 200 entries | Consent | Automatic |
| Server logs | Host log driver | Continuously | timestamps, paths, levels, redacted messages; never user text | Host log retention (pilot: 14 days recommended) | Legitimate interest (operations, security) | Log rotation |
| Public metrics | Computed on request from events | `GET /api/metrics/public` | counts per language, topic class, outcome, red-flag category; rows below k=5 suppressed | Not stored separately | n/a (anonymous aggregates) | n/a |
| Measurement reports | `reports/` in git | By the team | metrics from evaluation datasets and team-written questions; usability sessions as participant ids, not names | Permanent (open source) | Consent of usability participants recorded in `usability_sessions.csv` | Rewrite history only on a verified request |

## 2. What is not collected

- IP addresses: the rate limiter is keyed by session id; no middleware reads or stores the
  client address; there is no IP column anywhere.
- Device identifiers, browser fingerprints, advertising ids, third-party analytics.
- Names, e-mail addresses, phone numbers, date of birth, age (only "under 18: yes/no").
- Location beyond the pilot region code chosen by the user (`BA` or `ME`).
- Question text or transcripts, unless the user separately opts in to "save my questions".
- Audio after transcription; audio is never written anywhere but the temporary directory.
- Conversation history across sessions; there is no account to attach it to.
- Content of answers: only the gate decision and aggregate ratios are recorded.

The `log_event` function raises if a payload contains any of the keys `text`, `question`,
`transcript`, `audio`, `ip`, `email`, `phone`, `name`; this is tested.

## 3. Consent model

- **Version string.** `MILA_CONSENT_VERSION` (default `2026-10-01`) is returned by
  `GET /api/consent/text` and stored on the session when consent is given. Changing the
  text requires changing the version: `POST /api/consent` with any other version is refused
  with `409 consent_version_outdated` and the current version. A session that consented to an
  older version is refused by `/api/ask`, `/api/transcribe` and the preferences endpoint with
  `403 consent_version_outdated` (`require_consented_session`), `GET /api/session/{id}` reports
  the stored `consent_version`, and the web client then clears the session and shows the
  consent screen again; nothing stored under the old consent is used after the change.
- **Plain language, written and spoken.** `GET /api/consent/text?lang=&script=&is_minor=`
  returns `text` (shown), `spoken_text` (shorter, read aloud by TTS for voice-first use) and
  `items[]` (one line per thing MILA does and does not do). The texts exist in sr, bs, me, hr
  and en, in Latin and Cyrillic.
- **Act of consent.** `POST /api/consent` with `accepted: true` and the `consent_version`
  creates the session; anything else is a 403 and nothing is stored. The optional
  `save_questions` flag is a second, separate choice, default `false`.
- **Minors.** The consent screen asks `under_18_question`. If yes, the consent items and the
  spoken text switch to the minors' version and the session records `is_minor=true`, which
  adds child-protection services to every referral block (`docs/safety.md`, C7). MILA does
  not verify age and does not ask for one; the flag only makes the service more careful. Where national law requires a parent's or guardian's
  consent for a minor's health data, the pilot clinic decides how the service is offered to
  minors (for example, in the clinic with a counsellor present), and that decision is recorded
  in the DPIA.
- **Withdrawal.** "Delete my data" removes the session and everything linked to it; it is as
  easy as giving consent.

## 4. Pseudonymous sessions

`new_session_id()` returns `secrets.token_urlsafe(24)`: 192 random bits, never derived from a
device, an IP or the time. The web client keeps the id in the browser's `sessionStorage`
(per tab; gone when the tab or browser closes, so a shared clinic device does not hand one
person's session to the next) together with region and the minor flag; only language, script
and the low-bandwidth preference live in `localStorage`. "Delete my data" clears both. On load
the client checks the id with `GET /api/session/{id}` and drops it when the
server answers 403. Nothing in the server can link a session to a person; conversely, a person
who loses the id cannot be linked to their session either (see section 10).

## 5. Audio handling

1. The browser uploads a recording to `POST /api/transcribe` with the session id.
2. The file is written to `MILA_AUDIO_TMP_DIR` (a `tmpfs` mount in compose, so it never touches
   disk) with a random name.
3. STT runs locally (`faster_whisper`) or in the mock; no audio leaves the host.
4. `secure_delete` overwrites the file with zeros and unlinks it in a `finally` block, so it
   is deleted on success and on failure. A failed transcription is counted as an aggregate
   event (`type=transcribe`, `outcome=error`) that carries no audio and no text.
   Uploads larger than 1 MB are spooled by the web framework into `TMPDIR` before the handler
   runs; in compose `/tmp` is a tmpfs mount, so that spool never touches disk either.
5. The transcript is returned to the client; the client shows it and asks for confirmation
   before sending it as a question.

## 6. Logs and redaction

`RedactionFilter` is attached to every root logging handler at application start. It rewrites
the message of each record with `redact()`, which masks bearer tokens, API keys, e-mail
addresses, 13-digit identifiers (the shape of a JMBG), phone numbers and IPv4 addresses.
Application code never logs user text; the unhandled-error handler logs only the path. Log
level is DEBUG in `dev` and INFO otherwise.

## 7. Metrics and k-anonymity

`GET /api/metrics/public` aggregates events by topic class, outcome, input mode and day. Every
count below `MILA_K_ANONYMITY` (default 5) is suppressed, not noised, and suppression is
**complementary** (`app/api/metrics.py::_public_fields`): a total is published only when it
cannot be combined with its published parts to recover a suppressed part (the smallest
published day or topic rows are dropped until the remainder is 0 or at least k); ratios and
rates are published only when every outcome count is at least k (a ratio times a public total
would reveal a suppressed count); input modes only together with a public question total.
The public endpoint accepts only the fixed windows 7, 30, 90 and 365 days, so two windows
cannot be differenced to isolate a short period. The endpoint never returns per-session data.
Measurement reports use the same rule.

## 8. Hosting

- The pilot runs on infrastructure in the EU or on premises at the clinic. Inference uses
  open-weight models served locally (vLLM, llama.cpp or similar) through the OpenAI-compatible
  client, which sends `store=false`. No hosted LLM, STT or TTS API is used.
- No third party receives or retains user data: no CDN analytics, no error-reporting SaaS,
  no e-mail. The web UI loads nothing from external origins.
- Backups of the database, if made, inherit the same retention and deletion obligations;
  the pilot operator records where backups live and when they are destroyed.
- Transport is TLS-terminated by a reverse proxy in front of the containers.

## 9. Legal alignment

MILA is built to the GDPR standard even though Bosnia and Herzegovina and Montenegro are not
EU member states, and it aligns with the national data-protection laws of BiH and Montenegro,
which follow the same principles (lawfulness, purpose limitation, data minimisation, security,
data-subject rights, special protection of health data and of children). Where the two
frameworks differ, the stricter reading applies. The operator of a pilot is the controller and
must register or notify the processing where national law requires it; the pilot clinic's
data-protection contact handles that step.

| GDPR provision | How MILA aligns |
|---|---|
| Art. 5 (principles) | Purpose limitation (information + referral only), data minimisation (section 2), storage limitation (deletion on request, purge at pilot end), integrity and confidentiality (hardening in `SECURITY.md`) |
| Art. 6(1)(a) (consent as lawful basis) | Versioned, plain-language consent before any processing; 403 otherwise |
| Art. 9(2)(a) (explicit consent for health data) | Topic class and red-flag category are health-related; they are processed only under explicit consent, pseudonymised, and question text only under a separate opt-in |
| Art. 12 to 14 (transparency, information) | The consent text says what is processed, why, for how long, and how to delete; this document is public |
| Art. 15 (access) | Everything held for a session is visible in the UI for that session (section 10) |
| Art. 16 (rectification) | Session settings (language, region, minor flag) can be changed by the user; events hold no correctable personal data |
| Art. 17 (erasure) | `DELETE /api/session/{id}` erases immediately |
| Art. 25 (data protection by design and by default) | No identifiers in the schema, aggregate-only events enforced in code, save-questions off by default, audio deletion in `finally` |
| Art. 35 (DPIA) | Required because health data of a vulnerable group is processed with a new technology; skeleton in section 11 |

## 10. Data-subject requests

Because sessions are pseudonymous, MILA can act on a request only for a session whose id the
requester holds (it is shown in the UI under "Delete my data"). Without the id there is no way
to find "a person's data", which also means no one else can.

| Request | How it is served | Time |
|---|---|---|
| Access | `GET /api/session/{id}` returns everything the client can read back: consent given, language, script, region, minor flag, save-questions flag. There is no endpoint that returns the consent timestamp, the events or the saved questions in v0.1; a request for those is served by the data-protection contact from the database, by session id | Immediate for the settings; 30 days for the rest |
| Erasure | "Delete my data" or `DELETE /api/session/{id}`; the response lists the deleted row counts | Immediate |
| Rectification | Language and script can be changed in the UI (language switch); region and the minor flag through `POST /api/session/{id}/preferences`, or by deleting the session and consenting again | Immediate |
| Withdrawal of consent | Same as erasure | Immediate |
| Objection / restriction | Erasure, since no processing continues after deletion | Immediate |
| Requests by other means (e-mail to the data-protection contact) | Verified by asking for the session id; answered within 30 days; logged without personal data | 30 days |
| Usability participants | Identified by `participant_id`; the clinic keeps the key separately and can delete a participant's row from `usability_sessions.csv` on request | 30 days |

Suspected breach: the technical maintainer isolates the deployment, the data-protection
contact assesses which data items (section 1) could be affected, and, where national law or
the GDPR requires it, notifies the supervisory authority within 72 hours and the users through
the UI banner, since there is no other channel to reach them.

## 11. DPIA skeleton for the pilot

To be completed and signed before the first real user.

**Purpose.** Provide cited reproductive and maternal health information and referral, by voice
and text, in sr/bs/me/hr/en, to women and girls in BA and ME, including minors, without
accounts.

**Necessity and proportionality.** The service needs: a consent record (to prove consent), a
language and region (to answer and refer), a minor yes/no (to adapt wording and referrals),
aggregate events (to measure safety and usage) and, optionally, saved questions. Each item is
listed in section 1 with its justification; everything else was designed out (section 2).

**Risks.**

| Risk | Likelihood | Severity | Notes |
|---|---|---|---|
| Re-identification from events | Low | High | Pseudonymous id, no IP, k=5 suppression, small payloads |
| Exposure of saved questions | Low | High | Opt-in only, deleted with session, DB on hardened host |
| Audio retained by mistake | Low | High | `finally` deletion, tmpfs, tests |
| Minor's disclosure handled wrongly | Medium | High | `minor_sexual_adult` rule, child-protection referral, clinic review |
| Unsafe content (clinical) | Medium | High | See `safety.md`; demo mode off in pilot; clinic review of 20 answers |
| Breach of host | Low | High | Hardening in `SECURITY.md`, no secrets in repo, TLS |
| Loss of trust through unclear consent | Medium | Medium | Plain-language, spoken consent; tested with users |

**Measures.** Sections 2 to 8 of this document and `SECURITY.md`; adversarial tests; clinic
review; incident process in `safety.md`.

**Residual risk.** After measures: re-identification and audio retention are low; clinical
risk is reduced to the quality of the reviewed sources and the judge, which is why the pilot
runs with `MILA_DEMO_MODE=false` and reviewed sources only, and why usage by minors is offered
in the setting the clinic decides.

**Sign-off.**

| Role | Name | Date | Signature |
|---|---|---|---|
| Controller (pilot operator) | | | |
| Data-protection contact | | | |
| Clinical lead | | | |
| Technical maintainer | | | |
