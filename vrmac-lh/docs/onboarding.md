# Voice-first onboarding

> Innovation claim #3. A host describes their offer **out loud**, on a phone, on the plateau, with or
> without connectivity. The model rephrases their own words into a **title and a description — nothing
> else**. Price, season, capacity, accessibility and location are typed by the host and confirmed by
> the host, and the API refuses the listing if they were not. Two clocks are kept apart on purpose.

## The steps

The API sequence (`app/routers/onboarding.py`, `app/services/onboarding.py`) and the wizard's seven
screens (`frontend/components/host/Wizard.tsx`) line up like this:

| Wizard step | Call | What happens | Event |
|---|---|---|---|
| 1 · Start | `POST /api/onboarding/sessions` | language (`cnr`/`en`) and village; an **ambassador** may pass `host_user_id` to onboard on behalf of a host, a host may not | `onboarding_started` |
| 2 · Record | *(background)* `POST …/heartbeat` | the active-authoring clock, roughly every 30 counted seconds | — |
| 2 · Record | `POST …/sessions/{id}/audio` | multipart `file` + `offline_captured` + `captured_at`; queued to the worker, transcribed, audio deleted | `transcript_ready` |
| 3 · Transcript | `POST …/sessions/{id}/transcript` | a typed description, or the host's correction of the machine transcript | `transcript_ready` |
| 4 · Draft | `POST …/sessions/{id}/draft` | title and description in both languages, plus `fields_required` | `draft_generated` |
| 5 · Details | *(client-side)* | the host fills in and ticks price, season, capacity, accessibility, location, category | — |
| 6 · Consent | `POST …/sessions/{id}/confirm` | consent record → listing in `draft` → validation queue | `listing_confirmed` |
| 7 · Done | — | both clocks, the target, and "draft — in validation queue" | — |
| *later, by a validator* | `POST /api/validation/items/listing/{id}/transition` | approval closes the *elapsed* clock (`mark_published`) | `entry_approved` |

Session status walks `started → captured_offline? → transcribed → drafted → confirmed → published`
(`ONBOARDING_STATUS_VALUES` also allows `abandoned`). Only the host of the session and the ambassador
who opened it may write to it; any ambassador or validator may read it, because they staff the queue
and the timing log.

There is no microphone requirement: if `MediaRecorder` is missing or the host refuses the microphone,
the wizard offers an audio-file upload or a typed description, and the typed path emits the same
`transcript_ready` event with `stt_provider = "typed"`.

## What the model may and may not produce

`services/extraction.py` produces exactly four keys and no others:

```
title_local, title_en, description_local, description_en
```

`FIELD_NAMES` is that tuple, and `clean_draft_fields` keeps those four keys and **discards everything
else the model returned**, logging how many keys it dropped. The system prompt forbids inventing a
fact, forbids emitting a price, an amount, a date, a month, a season, availability, a capacity, a
number of guests or beds, or an accessibility statement as a value, and forbids any fifth key, a name,
a phone number or an e-mail address. `FORBIDDEN_OUTPUT_KEYS` names the keys that must never appear;
the module has no price, season, capacity, accessibility, coordinate or category detection code at
all — an earlier prototype had it and it was removed on purpose.

Sentences the host actually spoke stay inside the description as their own words. What never happens
is the model turning "negdje oko pedeset eura" into `price_min = 50`.

Two paths, one output shape:

* **LLM** (`LLM_PROVIDER = eu_api | ollama | vllm`) — one JSON object, four string keys,
  `extraction_method = "llm"`.
* **Rules** (`LLM_PROVIDER=none`, an unreachable model, invalid JSON, or the monthly spend cap
  reached) — deterministic: the title is a short clause of the host's own words matched by an
  offer-verb pattern, or a **category-neutral** label plus the village name ("Ponuda — Gornja
  Lastva", never "Apartman"); the description is the tidied transcript cut at a sentence boundary near
  600 characters. The rules path cannot translate, so it copies the local text into the `*_en` fields
  and sets `translation_pending`, which the UI and the validator card show. `extraction_method =
  "rules"`.

Both paths strip a greeting and a self-introduction ("ja sam …", "my name is …") from the start of the
transcript, so a personal name does not travel into a public description, and drop the sample
transcripts' prototype disclaimer sentence.

The draft response returns `fields_required`, the list the UI uses to ask for what the model did not
produce: `price_min, price_max, currency, season, capacity, accessibility, coordinates, category,
village`.

### `confirm` enforces it

`POST …/confirm` takes `{listing, consent}`. Before anything is written it checks
`listing.confirmed_fields` against five groups (`CONFIRMATION_GROUPS`):

| Group | Accepted aliases in `confirmed_fields` |
|---|---|
| `price` | `price`, `price_range`, `price_min`, `price_max` |
| `season` | `season`, `season_from`, `season_to`, `season_all_year`, `dates` |
| `capacity` | `capacity` |
| `accessibility` | `accessibility`, `accessibility_step_free`, `accessibility_note`, `accessibility_note_local`, `accessibility_note_en` |
| `coordinates` | `coordinates`, `lat`, `lng`, `location` |

Any group with no alias present is a **422**: *"the host must confirm every structured field the model
never fills; not confirmed: …"*. Both the compact form the wizard sends
(`["category","price_range","season","capacity","accessibility","coordinates"]`) and the per-column
form are accepted. `confirm` also rejects a missing consent (422), an unknown category (422), a
missing village (422), a missing title (422) and a session that already produced a listing (409).

Confirmation is not the same as completeness. A host may confirm "no fixed price" and leave
`price_min`/`price_max` empty; `missing_structured_fields` then records `missing_fields` on the
listing, which the validator sees on the queue card. Confirmed-and-empty is allowed;
unconfirmed is not.

The listing is created in `draft` through the ordinary validation gate, with the provenance source
`voice onboarding session <id>` and the note *"host-confirmed structured fields; title and description
drafted from the host's own words"*. `PUT /api/listings/{id}` later bumps the version and drops an
approved listing back to `draft` for re-validation.

## Two clocks

### Active authoring time — what the 30-minute target measures

`OnboardingSession.active_seconds` is accumulated from client heartbeats and nothing else.

In the browser (`frontend/components/host/useActiveTimer.ts`) a second is counted only when **all
three** hold:

* the wizard is open (`enabled` and a session id exists),
* the tab is visible — the Page Visibility API, so a backgrounded tab counts nothing,
* the host interacted within the last **60 s** (`pointerdown`, `keydown`, `input`, `change`, `wheel`,
  `touchstart`, `focusin`; becoming visible again also counts as an interaction).

The timer reports `paused_hidden` or `paused_idle` instead of counting otherwise. Every **30** counted
seconds the accumulated delta is sent to `POST …/heartbeat`; a failed request keeps its delta and
retries with the next one, so an offline stretch is not lost. The wizard flushes what is pending on
unmount and immediately before `confirm`.

On the server, `add_heartbeat` clamps a single delta to `MAX_HEARTBEAT_DELTA = 120` seconds, and the
request body additionally requires `1 ≤ active_seconds_delta ≤ 120`. A tab left open, a stuck client
or a hand-written request cannot add more than two minutes per call.

### Elapsed time — reported, never compared with the target

* `elapsed_to_confirm_seconds` — wall clock from `started_at` to `confirm`.
* `elapsed_to_publish_seconds` — wall clock from `started_at` to the moment a validator approved the
  listing. `services/validation.transition` calls `onboarding.mark_published`, which closes the clock,
  appends a timing-log line and hands the value back so it rides along in the `entry_approved` event.
  Calling it twice for the same listing is a no-op.

The target (`ONBOARDING_TARGET_MINUTES`, default 30 → `target_seconds() = 1800`) is applied to the
**active** number only: `within_active_target(active_seconds) = active_seconds <= 1800`. The reason is
plain — elapsed time to publication includes waiting for a human validator, which is the whole point
of the validation gate and which the platform does not control. Reporting a "30-minute onboarding"
that silently included three days in a queue would be a false claim. So K06/K07 read
`listing_confirmed.active_seconds` / `within_active_target`, and K08 reads
`entry_approved.elapsed_to_publish_seconds` as a separate, uncompared figure.

Both numbers are visible in three places: the wizard's final screen, the append-only file
`docs/test-results/onboarding_timing.log` (session ids and durations only — no user id, no name, no
transcript), and `GET /api/onboarding/timing-log` for validators and institutions.

## Offline capture

The contract between the browser and the API, in the order it happens:

1. **Record first, upload never before storing.** `offlineQueue.tsx: enqueue` writes the blob to
   IndexedDB (`vrmac-lh-host`, object store `recordings`, keyed by id, indexed by session and state)
   with its session id, language, `captured_at`, duration, MIME type, size, `state: "queued"`,
   `attempts: 0` and `captured_offline = !navigator.onLine`. A reload, a closed tab or a flat battery
   does not lose the recording.
2. **Upload when possible.** The queue flushes on mount, on every `enqueue`, whenever the `online`
   event fires, and on a 20-second timer — and returns immediately, doing nothing, while
   `navigator.onLine` is false. Each attempt posts multipart `file`, `captured_at` (the moment of
   *recording*) and `offline_captured`.
3. **`offline_captured` is set for any deferred upload**, not only for a recording made in flight
   mode: `row.captured_offline || row.attempts > 0`. A first attempt that failed marks the recording
   as an offline capture, because as far as the timing log is concerned that is what it was.
4. **The API stores the deferral.** `record_upload` sets `offline_captured`,
   `captured_at` and `upload_deferred_seconds = uploaded_at − captured_at` (never negative, rounded to
   milliseconds), and moves the session to `captured_offline` when the flag is set. `captured_at` must
   be ISO 8601 (`Z` or an offset; a naive value is read as UTC) or the call is a 422. When
   `offline_captured` is true but no `captured_at` was sent, `upload_deferred_seconds` stays `NULL`
   rather than being guessed.
5. **Transcription and deletion.** The upload is streamed to disk (≤ 25 MB, `413` above that, `422`
   for an empty file, `415` for a container that is not one of webm/ogg/oga/wav/m4a/mp3/mp4 by
   extension or content type; the filename is sanitised, so `../../etc/passwd` becomes `etc-passwd`).
   The job is module-level and opens its own database session, so `QUEUE_MODE=rq` and
   `QUEUE_MODE=sync` run identical code — in sync mode the transcript comes back with the response,
   in RQ mode the client polls `GET …/sessions/{id}` every 2 s until `transcript_ready_at` is set.
   The audio file is deleted as soon as it has been transcribed, and its now-empty session folder with
   it, unless `KEEP_AUDIO=true` (which logs a warning every time).
6. **On failure** the row goes back to `state: "failed"` with the error text and is retried; the host
   can also delete it. Uploaded rows are pruned from IndexedDB after 24 hours.

The queue is shared by every host screen through `OfflineQueueProvider`, and the wizard watches it, so
a recording that finishes uploading while the host is on another page still advances the session (with
a transcript, or by polling for one). `transcript_ready` carries `offline_captured` and `upload_deferred_seconds` into the
event stream, which is what K09 reads.

Audio blobs never leave the device until they are uploaded to this prototype's own API.

## Consent

`confirm` refuses to proceed unless `consent.given` is true, and writes one `consent_records` row
**before** the listing exists: `host_user_id`, `ambassador_user_id` (when an ambassador ran the
wizard), `onboarding_session_id`, `consent_text_version` (default `v1`), `consent_given`, `method`
(default `checkbox`), `given_at`, and `listing_id` filled in as soon as the listing is created. The
row also has `withdrawn_at` for a later withdrawal.

The wizard sends `{given: true, method: "checkbox", text_version: "v1"}` and shows the v1 text
verbatim in **both languages at once** (`ConsentText.tsx`), whichever interface language is selected,
because that is the text published on the prototype site. Changing a word there means a new version
string, published in both languages.

The gate enforces the record downstream: `services/validation.transition` returns 409 —
*"listing cannot be approved without a consent record"* — for any listing whose `consent_record_id` is
empty. A listing created outside the wizard therefore cannot be published either.

## Speech-to-text quality

`STT_PROVIDER` selects the recogniser: `eu_api` (Whisper at the EU inference provider, billable per
audio minute, priced into `llm_usage`), `faster-whisper` (local CTranslate2, CPU, int8 — the shipped
default), `api` (any other OpenAI-compatible `/audio/transcriptions`), or `fixture`
(**tests only** — it reads a sidecar text file and does not listen to the audio at all). Whisper has
no Montenegrin code, so `STT_LANGUAGE` (default `hr`) is used for Latin-script output and `en` for an
English session.

`services/stt_eval.py` measures the word error rate on the elderly-speaker set:
`python -m app.cli stt-eval` transcribes every sample in `seed_data/stt_eval_set.json`, computes
`word_error_rate` (Levenshtein over words, lower-cased and stripped of punctuation, so the metric
measures words rather than formatting), stores one `stt_evaluations` row per sample and returns the
mean and median. `GET /api/kpi/quality` serves the latest run to the dashboard.

**The five samples are synthetic stand-ins, and the number must be labelled as such.** The audio is a
2-second 220 Hz tone; with `STT_PROVIDER=fixture` the "recognised" text is read from a sidecar file
that differs from the reference by a word or two. Every row carries `is_synthetic_sample = true` and
the summary carries `is_synthetic`, so the figure cannot quietly lose its warning. A local run with
the fixture provider gave a mean WER of 0.075 over 5 samples — that is a real measurement **of a fake
recogniser**, and it is not a claim about how well Whisper understands an elderly speaker from Vrmac.

Replacing the samples needs no code change: only the audio files, their reference texts and the flag.
`docs/samples/README.md` says how, and `docs/decisions.md` §12 carries it as an **ACTION** before the
number is quoted anywhere.

## Checking it

```bash
cd backend && . .venv/bin/activate
TEST_DATABASE_URL=postgresql+psycopg://vrmac:vrmac@127.0.0.1:5432/vrmac_test pytest -q tests/test_onboarding.py tests/test_stt_eval.py
```

`tests/test_onboarding.py` covers the step sequence, the heartbeat cap, the offline-capture fields,
the four-key extraction contract and the `confirm` rejection; `tests/test_stt_eval.py` covers the word
error rate and the synthetic flag. The frontend is type-checked and built by `make test-frontend`.
