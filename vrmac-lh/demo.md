# VRMAC-LH — 7-minute pitch script (SMART ERA)

> Prototype built for the SMART ERA application, September–October 2026. Sample data.
> Nothing in this script claims production status, real users or a TRL.

## Before the demo (15 minutes earlier)

1. `docker compose up -d`, then open `/api/health`: providers must read `llm`, `embeddings`, `stt` and
   `support_check`. Run `make kpi` and publish the run (`make kpi` prints the run id; publish it in the
   dashboard's review panel) so the dashboard has data.
2. Open four tabs: `/host` (signed in as `host1@example.org`), `/validate` (`validator1@example.org`),
   `/visitor`, `/dashboard` (`institution1@example.org`). Language toggle on *Crnogorski* for host and visitor.
3. Test the microphone once and discard the recording. Have a backup recording ready in `docs/samples/`.
4. Fallbacks: with `LLM_PROVIDER=none` the answers become extractive quotes with citations and the draft
   becomes rule-based — both are labelled in the UI, and nothing else changes.

## Script

**0:00 – 0:45 · The problem and the promise**
"Gornja Lastva had no permanent residents in the 2011 census, yet its festival has been held every first
Saturday of August since 1974. The heritage of the Vrmac plateau — on both sides of the ridge, in two
municipalities — lives in people and documents that never reach a visitor. VRMAC-LH is one validated source
of truth: hosts speak, validators approve, visitors get answers only from approved facts, or an honest
refusal." Point at the banner: prototype, sample data.

**0:45 – 3:00 · Host flow, live (voice-first, offline-capable)**
Host tab → *New listing*. Pick the village (Donja Lastva, municipality of Tivat) — the active-time timer
starts and the screen says that waiting for the validator does not count. Record ~30 seconds in
Montenegrin, for example: "Imam apartman u Donjoj Lastvi, dvije sobe, prizemlje bez stepenica, tristo
metara od mora, pogled na zaliv." Stop and upload. Show the transcript and the provider label.
*Generate title and description* → the model returns **only** a title and a description in both languages.
Then the details form: "the assistant never guesses a price, a season, a capacity or accessibility — the
host types them and confirms them." Fill 45–70 € per night, May–October, four guests, step-free, tick the
confirmations, then the consent text, then *Confirm*. The final screen shows the **active authoring time**
against the 30-minute target, the elapsed time separately, and "draft — in validation queue".
*If there is time*: switch the browser to offline before uploading to show the recording being queued on the
device and uploading by itself when connectivity returns — that is the reality on the plateau.

**3:00 – 4:00 · Validation gate**
Validator tab → the new listing is in the queue with its village, its provenance (voice onboarding session,
version 1, consent v1) and the host-confirmed fields. Approve it with a note. "Only now does it exist for
visitors: the database role the visitor app uses physically cannot read a draft — row-level security, proven
in CI." Show the two rows flagged *unverified facts* (Gornji Stoliv) and say plainly: nothing unverified can
be approved, so the assistant will refuse questions about it until a person checks the sources.
Reload the visitor map: the new provider appears in both languages.

**4:00 – 5:30 · Visitor: map, directions, trail, grounded answers**
Visitor tab → *Explore*: select the church of St Vitus → *How to get there — on foot* opens Google Maps
navigation (real routing, no key). *Trails* → Donja Lastva – Gornja Lastva: the GPX track renders with the
latest condition report ("caution: fallen branches after a storm"). *Ask*: "Kada se održava Lastovska
fešta?" → the answer with its citation (entry *Lastovska fešta*, source gornjalastva.org / hr.wikipedia).
Then the withheld one: "Gdje je sakriveno zlatno zvono Vrmca?" → the refusal. "That legend is in the
database as a draft. Not approved, so not answerable — and the refusal is logged as `answer_withheld`."
Mention the second control: every sentence of an answer is checked against the cited passage and dropped if
it is not supported. Optionally run the multi-village itinerary for three hours from Donja Lastva.

**5:30 – 6:30 · Institution dashboard**
Dashboard tab → *Recompute*, then publish the run in the **disclosure review** panel: "nothing reaches this
screen before a person reviews the small cells." The K01–K23 table refreshes from events only, with the
provisional-definitions banner visible: "these definitions come from a file, not from code — when §11 of the
SIP Draft is transcribed into it, every figure updates without touching the software." Point at a suppressed
cell ("k<5"), at gender coming only from voluntary self-report, at the median **active** authoring time next
to the elapsed time, at the heat map of measured visits per 100 m cell, and at the quality panel: speech
recognition error rate, cache hit rate and the monthly model spend against the 50 € cap.

**6:30 – 7:00 · Interoperability and close**
Open `/api/export/ngsi-ld` (Smart Data Models `PointOfInterest`, schema-validated in the test suite) and
`/api/export/dcat-ap`. "Open source under AGPL, open data models, open maps, an EU inference provider with
no data retention and a spend cap in code, running on a 4 GB server. With SMART ERA the next steps are K4's
surveyed GPX instead of our approximate coordinates, the verified Kotor-side villages, and the first real
hosts onboarded with the ambassadors."

## If something fails

| Symptom | Do |
|---|---|
| Microphone blocked | use *Upload* with a file from `docs/samples/`, or *type instead* |
| Transcription slow | the job runs on the worker and the page polls; keep talking about the gate |
| Empty or odd draft | the rules fallback takes over (labelled "rules"); edit the two text fields by hand |
| Model unreachable | `LLM_PROVIDER=none`: extractive answers with citations still work |
| Spend cap reached | that is a feature: show the cached answer and the "assistant paused" message |
| No KPI figures | `make kpi`, then publish the run in the review panel |
