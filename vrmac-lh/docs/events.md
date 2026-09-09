# The pseudonymised event stream

> Innovation claim #4, first half. Every workflow step appends one row to `events`; the KPI engine
> reads that table and nothing else. No row carries a user id, a session id, a device id or a line of
> free text — only keyed HMAC pseudonyms and a small, checked set of properties.

## Where a row comes from

Only one event type may be posted by a browser: `visit_recorded`, through `POST /api/events`
(`app/routers/events.py`). Everything else is emitted **server-side by the workflow that performs the
step**, so nobody can inflate a KPI from outside. The endpoint rejects any other `event_type` with 422,
and `emit_event` rejects an event type that is not in `EVENT_TYPES` with `ValueError`, which the
`ck_events_type` CHECK constraint repeats in the database.

`app/events.py: emit_event(...)` is the single writer. It is the only place that:

* replaces the actor's user id, the visitor's `session_id` and the `device_id` with keyed HMAC
  pseudonyms;
* copies `actor_gender` **only** when the person voluntarily self-reported it;
* refuses a `properties` key from the deny-list;
* derives `village_id` and `municipality` from the `village` it was handed.

## Every event type

Eighteen types are defined in `app/models.py: EVENT_TYPES` — the fifteen named in the brief plus
`item_rejected`, `visit_recorded` and `assistant_paused`, which the heat map, the validation-quality
KPI and the spend-cap KPI need (`docs/decisions.md` §13).

Columns every row carries: `event_type`, `occurred_at`, `actor_pseudonym`, `actor_role`,
`actor_gender`, `gender_self_reported`, `session_pseudonym`, `device_pseudonym`, `item_type`,
`item_id`, `village_id`, `municipality`, `lat`, `lng`, `properties`. The table below lists what is
*additionally* put into `properties` at each call site.

| Event | Emitted by | Who the row is about | `properties` | Read by |
|---|---|---|---|---|
| `onboarding_started` | `services/onboarding.py: start_session` | the **host** (even when an ambassador operates the wizard) | `language`, `via_ambassador` | K01 |
| `transcript_ready` | `services/onboarding.py: transcribe` and `set_transcript` | host | `stt_provider`, `stt_model`, `audio_duration_s`, `transcript_chars`, `offline_captured`, `upload_deferred_seconds`, `seconds_since_start` | K09 |
| `draft_generated` | `services/onboarding.py: generate_draft` | host | `llm_provider`, `extraction_method`, `translation_pending`, `seconds_since_start`, `active_seconds` | *no KPI in the current definition file* |
| `listing_confirmed` | `services/onboarding.py: confirm` | host | `onboarding_session_id`, `active_seconds`, `elapsed_to_confirm_seconds`, `within_active_target`, `category`, `extraction_method`, `offline_captured` | K02, K06, K07 |
| `entry_approved` | `services/validation.py: transition` | the validator who approved | `version`, `from_status`, `elapsed_to_publish_seconds` | K03, K04, K05, K08 |
| `item_rejected` | `services/validation.py: transition` | the validator who rejected | `version`, `from_status` | K22 |
| `answer_served` | `services/rag.py: answer` (`serve`) | anonymous visitor | `lang`, `question_len`, `question_sha256`, `confidence`, `n_citations`, `entry_ids`, `served_from_cache`, `dropped_sentences`, `support_provider`, `village_slugs` | K10, K11, K13 |
| `answer_withheld` | `services/rag.py: answer` (`withhold`) | anonymous visitor | `lang`, `question_len`, `question_sha256`, `confidence`, `reason` | K11, K12, K13 |
| `assistant_paused` | `services/rag.py: answer` (`withhold(paused=True)`) | anonymous visitor | `lang`, `question_len`, `question_sha256`, `reason`, `cap_eur`, `spent_eur` | K23 |
| `itinerary_generated` | `routers/itinerary.py: create_itinerary` | anonymous visitor | `n_stops`, `hours`, `total_km`, `est_hours`, `interests`, `multi_village`, `multi_municipality`, `n_villages`, `lang` | K11, K14, K15 |
| `request_sent` | `services/requests_lifecycle.py: create_request` | anonymous visitor | `category`, `party_size`, `has_requested_date` | K11, K16 |
| `request_confirmed` | `services/requests_lifecycle.py: set_status` | the host who replied | `from_status`, `closed_by`, `category` | K17 |
| `request_completed` | `services/requests_lifecycle.py: set_status` | the host who closed it | `from_status`, `closed_by`, `category` | K18, K19 |
| `request_refused` | `services/requests_lifecycle.py: set_status` | the host who refused | `from_status`, `closed_by`, `category` | K19 |
| `request_cancelled` | `services/requests_lifecycle.py: set_status` | host **or** visitor (`closed_by`) | `from_status`, `closed_by`, `category` | K19 |
| `request_expired` | `services/requests_lifecycle.py: set_status`, from `expire_stale_requests` | nobody — `actor_role = "system"` | `from_status`, `closed_by`, `category` | K19 |
| `trail_report` | `routers/trails.py: submit_report` | anonymous visitor, or a signed-in reporter | `condition`, `report_id`, `segment_slug` | K11, K20, heat map |
| `visit_recorded` | `routers/events.py: record_visit` | anonymous visitor | *(none)* | K11, K21, heat map |

`draft_generated` is emitted and stored but no KPI in `kpi_definitions/sip_section_11.json` currently
reads it. That is a gap in the provisional definitions, not in the stream: when §11 names a
draft-related indicator, the spec can point at this event without touching any code.

Rows written by the seed's synthetic demo history additionally carry `synthetic: true`
(`app/seed/synthetic_events.py`); nothing in that history is real usage. See `docs/decisions.md` §11.

The synthetic rows carry every property the current KPI specs read (`active_seconds`,
`within_active_target`, `offline_captured`, `elapsed_to_publish_seconds`, `multi_village`), but their
property sets are a variant of the live emitters', not a copy: they omit `question_len` /
`question_sha256`, they name the refusal reason `refusal_reason` where `services/rag.py` writes
`reason`, and the request events carry a `request_id` instead of `from_status` / `closed_by` /
`category`. A §11 spec that reads a property outside that list will therefore see it on live events
and not on the demo history. The column that decides which spec matches is `event_type`, which is
identical in both.

### Coordinates and item references

`lat`/`lng` are set on `visit_recorded` and `trail_report` only — they are what the heat map is built
from. They are stored as given and are never served row by row: the only geographic output is
`kpi_heat_cells`, a ~0.001° (≈100 m) grid, and a cell is stored only when at least `KPI_K_MIN`
distinct device pseudonyms fall inside it (`services/kpi.py: build_heat_cells`).

`item_type` / `item_id` point at a *content* item (a listing, a heritage entry, a trail report, an
onboarding session) — never at a person. The events table has **no foreign key to `users`**.

## Pseudonymisation

`app/pseudonym.py` computes

```
pseudonym = HMAC-SHA256(EVENT_PSEUDONYM_KEY, "<kind>:<value>")[:32]
```

with `kind ∈ {actor, session, device}`, and returns `None` for a missing or blank value. Three
consequences the KPI engine depends on:

* **Stable** for the same input and key, so distinct persons and distinct devices can be counted
  (K11) without storing an identifier.
* **Not reversible** without the key, and not linkable across deployments — the same visitor on
  another instance of this software gets a different pseudonym.
* **Revocable**: rotating `EVENT_PSEUDONYM_KEY` makes every historical pseudonym unlinkable to
  anything written afterwards. Old rows keep their old digests, new rows get new ones, and the two
  cannot be joined. Rotation is therefore a real unlinking lever — the rows survive, the ability to
  connect them to anything newer does not — and it is equally a break in every distinct-person and
  distinct-device count that spans it.

Because the `kind` is part of the message, the same string hashed as a session and as a device yields
two different pseudonyms, so a session pseudonym can never be matched against a device pseudonym.

In development an empty key falls back to a fixed development key and logs a warning; `APP_ENV=prod`
refuses to start without a real one (`app/main.py`).

**One honest detail.** `emit_event` computes `device_pseudonym = pseudonymise(DEVICE, device_id or
session_id)`. A client that sends only a `session_id` still produces a device pseudonym, derived from
that session id. Such a visitor counts as one device in K11 per session rather than per browser. The
visitor app does send a separate, persistent `device_id` (`frontend/components/visitor/device.ts`), so
this fallback affects other clients only.

## The property deny-list

`emit_event` raises `ValueError` — before anything is written — when a `properties` key matches, case
insensitively, any of:

```
address, answer, device_id, e-mail, email, first_name, ip, ip_address, last_name, mail,
message, name, phone, question, session_id, surname, transcript, user_id
```

The list is a guard rail, not the rule. The rule is: **no free text ever goes into an event.** A
question, a visitor's message to a host, a trail-report note and a transcript are all content a person
wrote, and any of them can carry a name, a phone number or an address that no deny-list can predict.
What the stream keeps instead is the *shape* of the text: `question_len`, `question_sha256`,
`transcript_chars`. A hash lets two identical questions be recognised as identical; it does not let
the question be read back.

## Gender

`actor_gender` is a snapshot, copied only when `User.gender_self_reported` is true and the value is
one of `female | male | other` (`GENDER_REPORTED`). The default `undisclosed` and the explicit
`prefer_not_to_say` never reach the column; those events land in the `not_reported` cell of a
gender-disaggregated KPI, so the gender rows still reconcile with the total. The self-report is made
through `POST /api/auth/me/gender` and nowhere else.

## Why `answer_records` carries no pseudonym at all

The monthly human review of the assistant (`services/review.py`) needs the question and the answer in
full — a reviewer cannot judge grounding from a hash. That text lives in `answer_records`, which is
written by `services/rag.py: _record_answer` alongside the event.

`answer_records` deliberately has **no** `session_pseudonym`, no `device_pseudonym`, no
`actor_pseudonym` and no foreign key to anything about the person who asked. It stores
`occurred_at`, `lang`, `question`, `answer`, `answered`, `refusal_reason`, `confidence`, `citations`,
`support_results`, `dropped_sentences`, the provider names and `served_from_cache`.

The event and the answer record are written in the same transaction, moments apart, and share no key
— only an approximate timestamp. That is on purpose and it is the trade-off: a reviewer can read every question and judge every citation,
but cannot tie a question back to a person — not by joining tables, because there is no column to join
on. The `question_sha256` in the event is a hash of the question, not a key into `answer_records`;
matching would require already knowing the question text.

The consequence is that the review sheet cannot be filtered "by visitor", and a request to erase one
person's questions cannot be served against `answer_records` either. Both were accepted so that the
review sample can never become a re-identification tool.

## What a reader can and cannot get out of the stream

| | |
|---|---|
| Can | counts, medians and shares per KPI, per village, per municipality, per self-reported gender and per day — after disclosure control (`docs/kpi-definitions.md`) |
| Can | "how many distinct devices did we reach", because a device pseudonym is stable (K11) |
| Cannot | any question, message, note or transcript — none is stored in an event |
| Cannot | a name, an e-mail address, a phone number or an IP address — none is stored anywhere in the analytics path (`docs/security.md`) |
| Cannot | which person a pseudonym belongs to, without `EVENT_PSEUDONYM_KEY` |
| Cannot | which person asked a given question, even *with* the key — `answer_records` has no pseudonym |

## Checking it

```bash
cd backend && . .venv/bin/activate
TEST_DATABASE_URL=postgresql+psycopg://vrmac:vrmac@127.0.0.1:5432/vrmac_test pytest -q
```

`tests/test_kpi.py` and `tests/test_disclosure.py` cover the stream-to-KPI path; `tests/test_geo.py`,
`tests/test_itinerary.py`, `tests/test_requests.py` and `tests/test_onboarding.py` cover the emitting
call sites. `GET /api/events/types` returns the live list of event types.
