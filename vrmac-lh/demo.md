# VRMAC-LH — 7-minute pitch script (SMART ERA)

> Prototype built for the SMART ERA application, September–October 2026. Sample data.

## Before the demo (15 minutes earlier)

1. `docker compose up -d` on the demo machine or the VPS; open `/api/health` — providers must show
   `llm=ollama`, `embeddings=ollama`, `stt=faster-whisper`. Run `make kpi` once so the dashboard has a fresh run.
2. Open four browser tabs: `/host` (logged in as `host1@example.org`), `/validate` (`validator1@example.org`),
   `/visitor`, `/dashboard` (`institution1@example.org`). Language toggle set to *Crnogorski* on the host and visitor tabs.
3. Test the microphone once (record 3 seconds, discard). A real host voice sample in the local language is spoken
   live in step 2; keep `docs/samples/` handy as a backup recording. If the STT is slow on the machine, use
   "type instead" — the flow is identical.
4. Fallbacks: if Ollama is slow, set `LLM_PROVIDER=none` — answers become extractive quotes with citations and the
   listing extraction is rule-based (both are labelled in the UI). Nothing else changes.

## Script

**0:00 – 0:45 · The problem and the promise**
"Gornja Lastva has no permanent residents in the 2011 census but a festival held every first Saturday of August since
1974. Its heritage lives in people and documents that never meet visitors. VRMAC-LH is one validated source of truth:
hosts speak, validators approve, visitors get answers only from approved facts — or a refusal." Point at the yellow
banner: everything here is a prototype with sample data.

**0:45 – 3:00 · Host flow, live (voice-first onboarding)**
Host tab → *New listing by voice* → the timer starts. Press *Record* and speak ~30 seconds in Montenegrin, e.g.:
"Zovem se … imam apartman u Donjoj Lastvi, dvije sobe, do četiri gosta, cijena od 45 do 70 eura po noći, od maja do
oktobra, prizemlje bez stepenica, tristo metara od mora." Stop → *Upload*. Show the transcript from faster-whisper
(label under the text). *Generate listing* → the structured draft appears: title, description, price range 45–70 €,
season May–October, capacity 4, accessibility; missing fields are highlighted (coordinates → *use my location*).
Confirm → consent text → *Confirm*. The final screen shows the measured duration against the 30-minute target and
"draft — in validation queue". "This duration is logged; it is KPI data, not a claim."

**3:00 – 4:00 · Validation gate**
Validator tab → the new listing is in the queue with its provenance (created by voice onboarding session, version 1,
host consent v1). Approve with a note. "Only now the listing exists for visitors — the database role used by the
visitor app can physically not read drafts: row-level security, tested in CI." Switch to the visitor tab, reload the
map: the new provider appears, in Montenegrin and English.

**4:00 – 5:30 · Visitor: map, directions, trail, grounded answers**
Visitor tab → *Explore*: click St Vitus → *How to get there — on foot* opens Google Maps navigation (real routing, no
key). *Trails* → Donja Lastva – Gornja Lastva: the GPX track renders with the latest condition report ("caution: fallen
branches after a storm"). *Ask*: "Kada se održava Lastovska fešta?" → answer with citation: entry *Lastovska fešta*,
source gornjalastva.org / hr.wikipedia. Then the withheld question: "Gdje je sakriveno zlatno zvono Vrmca?" → refusal:
"Nemam potvrđen izvor za ovo pitanje…". "That legend exists in the database as a draft. Not approved, not answerable,
and the refusal is logged as an `answer_withheld` event." (Optional: *Itinerary* for 3 hours from Donja Lastva.)

**5:30 – 6:30 · Institution dashboard**
Dashboard tab → *Recompute now*. The KPI table refreshes from events only: hosts onboarded by sex (F/M published,
the small group suppressed with "k<5"), median onboarding minutes, share within 30 minutes, answers served vs
withheld, requests confirmed, trail reports. Heat map of measured visits per ~100 m cell — cells below 5 sessions
are not shown. "No number on this screen is typed in; delete the events and the table is empty."

**6:30 – 7:00 · Interoperability and close**
Open `/api/export/ngsi-ld` (NGSI-LD `PointOfInterest` entities, Smart Data Models, schema-validated in the test
suite) and `/api/export/dcat-ap`. "Open source (AGPL), open data models, open maps, runs on a 4 GB server. Next step
with SMART ERA: replace the sample coordinates with K4's surveyed GPX and onboard the first real hosts with the
ambassadors."

## If something fails

| Symptom | Do |
|---|---|
| Microphone blocked | use *Upload* with `docs/samples/*.webm` or *type instead* |
| Transcription > 60 s | the job runs on the worker; keep talking about the gate, the page polls automatically |
| LLM returns an empty draft | rules extraction takes over automatically (label "rules"); edit the fields by hand |
| Ollama not answering | `LLM_PROVIDER=none` → extractive answers with citations still work |
| No KPI run | `make kpi` |
