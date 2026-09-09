# Decisions, assumptions and open items

Everything on this page is a judgement call made while building the prototype. Each one is reversible,
and the ones that need a human before the pitch are marked **ACTION**.

## 1. Where the prototype lives
The `sportek` repository already contains an unrelated project at its root, so VRMAC-LH lives in
`vrmac-lh/` with its own README, compose stack and CI workflow (`.github/workflows/vrmac-lh-ci.yml`,
path-filtered).

## 2. Reference documents were not available — **ACTION**
`SIP_Draft_Vrmac_Living_Heritage.pdf` (architecture §2.2, workflows §2.3, KPIs §11) and
`VRMAC_LH_Prototype.html` (screens and copy) are not in the repository and could not be fetched from the
build environment. Consequences:

* The architecture diagram in `docs/architecture.md` follows the brief, not §2.2. Align it before the pitch.
* **K01–K23 are provisional.** The brief says "compute them exactly as defined in §11; do not invent
  definitions". The engine therefore executes a definition *file*
  (`backend/kpi_definitions/sip_section_11.json`) instead of hard-coded logic: each KPI carries a
  machine-readable `spec`, a `provisional: true` flag and a warning. Replace the wording and the specs
  from §11, set `provisional: false`, run `make kpi` — no code changes. Every aggregate row and the
  dashboard header show the provisional flag until then. Only K11 is not provisional: its definition
  (distinct pseudonymous device ids, single 180-day deduplication) is given in the brief itself.
* Screens follow the brief's wording rather than the HTML mock-up.

## 3. Gornji Stoliv could not be verified — **ACTION**
The brief asks for at least two villages seeded with real public facts and says to mark unverified ones.
Wikipedia and the other public sources are blocked by the build environment's egress policy, so **no fact
about Gornji Stoliv was verified**. What was done instead:

* The village exists as reference data with `facts_verified=false` and a `verification_note` naming exactly
  what must be checked (spelling, municipality, coordinates, altitude).
* Its heritage entry states only that it lies on the Kotor side of Vrmac and says, in both languages, that
  it is unverified and unpublished. It sits in the validation queue as a `draft`.
* The data layer refuses to approve any item with `facts_verified=false`, so nothing unverified can reach a
  visitor or the assistant. Two grounding-test questions about Gornji Stoliv are expected to be *withheld*.
* The same treatment is applied to Pasiglav and to the ridge crossing St Vitus → Gornji Stoliv.

Verify the facts, complete the entry, then approve it — the demo then shows a cross-municipality itinerary.

## 4. Territory model
`Village` is reference data (names, municipality Tivat/Kotor, ridge side, approximate coordinates, source,
verification flag). Every claim *about* a village lives in a heritage entry that passes the gate, so a
village row can never carry an unvalidated statement. Heritage entries, listings and trail segments have a
mandatory `village_id`; trail segments also list every village they connect; events carry `village_id` and
`municipality`.

## 5. Language codes
Montenegrin is `cnr` (ISO 639-3); the UI ships `cnr` and `en`. Whisper has no Montenegrin code, so
`STT_LANGUAGE=hr` is used for Latin-script output (configurable). A third language may only be added once
its own 20 + 10 grounding test passes.

## 6. Models and the EU inference provider
The pilot's primary is an open-weight model consumed pay-per-use from an EU inference provider under a
no-data-retention contract (`LLM_PROVIDER=eu_api`, any OpenAI-compatible endpoint; `APP_ENV=prod` refuses to
start unless `LLM_NO_DATA_RETENTION_CONFIRMED=true`). `.env.example` ships the self-hosted alternative
(`ollama`, profile `local-llm`) active, so `docker compose up` works in three commands with no API key and
no account — that is the demo-laptop configuration. **ACTION**: choose the provider, set the price list in
`.env`, and confirm the contract.

## 7. Spend cap
`LLM_MONTHLY_CAP_EUR` (default 50) is enforced in code: every billable call is priced into `llm_usage`, and
`services/budget.guard` refuses further paid calls once the month's spend reaches the cap. The assistant
then serves valid cached answers and otherwise says it is paused. It never falls back to unsourced text.

## 8. Offline test mode
CI and this sandbox cannot download models, so the tests run with `EMBEDDINGS_PROVIDER=hash` (deterministic
lexical hashing), `LLM_PROVIDER=none` (extractive answers), `SUPPORT_CHECK_PROVIDER=lexical` and
`STT_PROVIDER=fixture`. The gate, the support check, the cache, the cap and the KPI paths are identical in
both modes; only the language quality differs. The `llm_judge` support check runs on top of the lexical one
and can only lower a verdict, so the offline mode is the conservative one.

## 9. Validation gate in the data layer
A second PostgreSQL role (`vrmac_public`) has `SELECT` only, restricted by row-level security to
`status='approved'` (and, for chunks, to chunks of approved entries). Services additionally filter
explicitly, and `CHECK` constraints keep the status vocabulary honest. Villages are readable in full
because they carry no claims.

## 10. Pseudonymised events
Events carry no user id, session id or device id in the clear — only keyed HMAC pseudonyms
(`EVENT_PSEUDONYM_KEY`). Gender appears only when a person volunteered it. Answers are stored separately in
`answer_records` *without* any pseudonym so the monthly human review sheet cannot be tied back to a person.

## 11. Synthetic event history
The dashboard needs enough events to show suppression at work, so the seed loads a deterministic synthetic
history flagged `synthetic: true`. Every KPI value is computed from those rows; none is typed in. Delete the
events and the table empties.

## 12. Speech-to-text quality metric — **ACTION**
The word-error-rate set consists of five synthetic stand-in recordings, clearly flagged. Replace them with
consented recordings of elderly Montenegrin speakers before quoting the number (`docs/samples/README.md`).

## 13. Extra event types
`item_rejected`, `visit_recorded` and `assistant_paused` complement the fifteen event types named in the
brief; the heat map and the spend-cap KPI need them.
