# K01–K23 — definitions, engine and disclosure control

> **Read this first. Twenty-two of these twenty-three definitions are placeholders.**
> `SIP_Draft_Vrmac_Living_Heritage.pdf` §11 was not present in the repository and could not be
> fetched from the build environment, so **no wording on this page can be attributed to it**. The
> brief says "compute them exactly as defined in §11; do not invent definitions", so nothing was
> invented in code: the engine executes a *definition file*, and every placeholder is flagged.
> Only **K11** follows a definition given in the brief itself. See `docs/decisions.md` §2 — **ACTION**.

## What is provisional, and what replacing it costs

The definitions live in `backend/kpi_definitions/sip_section_11.json`
(`KPI_DEFINITIONS_PATH`). The file carries a `version`, a `status`, a `warning`, a
`spec_reference` and 23 entries. `backend/app/services/kpi.py` is a **generic evaluator** for those
entries: no KPI is defined in Python, and the module's own docstring says so.

To adopt §11:

1. For each key, copy the §11 wording into `definition`, set `unit`, `person_level` and
   `gender_disaggregated`, and adjust `spec` to the event types and properties §11 names.
2. Set `provisional: false` on each entry (and remove the file-level `status` warning).
3. Run `make kpi` — or `python -m app.cli kpi-compute` — and review the run.

**No code changes.** Every figure the dashboard shows changes with the file. The engine re-reads the
file automatically when its modification time or size changes (`load_definitions`), and a run
stamps `definitions_version` and `definitions_provisional` onto `kpi_runs` and onto every row of
`kpi_aggregates`, so an old published run stays honest about the definitions it was computed under.

Until then: `GET /api/kpi/definitions` returns the file with its warning, every aggregate row carries
`provisional_definition = true`, and the dashboard header shows the provisional banner.

If a spec names an operator the engine does not implement, the run does **not** fail: the row is
stored with `value = null` and the note `unsupported spec`, and the review summary lists the key under
`kpis_unsupported_spec`. A broken spec that raises is caught the same way, with the note
`spec error: <ExceptionName>`.

## The twenty-three

`person_level` decides what the k-rule counts and whether `date × activity × gender` cells are built;
`gender_disaggregated` decides whether gender cells are built at all.

| Key | Label (en) | Unit | Person-level | Gender-disaggregated | Provisional | Spec operator |
|---|---|---|---|---|---|---|
| `K01` | Hosts onboarded | count | yes | yes | yes | `count_distinct_actors` |
| `K02` | Listings confirmed by hosts | count | yes | yes | yes | `count_events` |
| `K03` | Listings published after validation | count | — | — | yes | `count_events` |
| `K04` | Heritage entries approved | count | — | — | yes | `count_events` |
| `K05` | Villages with published content | count | — | — | yes | `count_distinct_villages` |
| `K06` | Median active authoring time | minutes | yes | yes | yes | `median_property` |
| `K07` | Share of listings authored within the target | share | yes | yes | yes | `share_property_true` |
| `K08` | Median elapsed time to publication | minutes | — | — | yes | `median_property` |
| `K09` | Offline-captured recordings | count | — | — | yes | `share_property_true` |
| `K10` | Assistant answers served | count | — | — | yes | `count_events` |
| `K11` | Distinct visitor devices reached | count | — | — | **no** | `count_distinct_devices` |
| `K12` | Answers withheld | count | — | — | yes | `count_events` |
| `K13` | Withholding rate | share | — | — | yes | `ratio_events` |
| `K14` | Itineraries generated | count | — | — | yes | `count_events` |
| `K15` | Multi-village itineraries | share | — | — | yes | `share_property_true` |
| `K16` | Requests sent to providers | count | — | — | yes | `count_events` |
| `K17` | Requests confirmed by providers | count | yes | yes | yes | `count_events` |
| `K18` | Requests completed | count | yes | yes | yes | `count_events` |
| `K19` | Request completion rate | share | — | — | yes | `ratio_events` |
| `K20` | Trail condition reports | count | — | — | yes | `count_events` |
| `K21` | Measured visits recorded | count | — | — | yes | `count_events` |
| `K22` | Content items rejected at validation | count | — | — | yes | `count_events` |
| `K23` | Assistant paused by the spend cap | count | — | — | yes | `count_events` |

Which event feeds which KPI is listed the other way round in `docs/events.md`. The full placeholder
wording of each `definition` is in the JSON file and is served verbatim by
`GET /api/kpi/definitions`; it is not duplicated here, so there is one place to correct.

**Two inconsistencies in the placeholder file, left as they are because the file is what §11 must
replace, not something to guess at now:**

* `K09` is labelled "Offline-captured recordings" with `unit: "count"`, but its spec is
  `share_property_true`, so the engine stores a share between 0 and 1. The unit string is wrong for
  the spec; whichever §11 intends, one of the two has to change.
* `K11` counts distinct devices, which are visitors, but is marked `person_level: false`. That is
  deliberate — see the k-rule below — and it means K11's own k-threshold is applied against the same
  device set it counts.

## The `spec` operators

Every operator receives the events of the current dimension after `event_types` and `filters` have
been applied. `filters` matches on `event_type`, `item_type`, `actor_role`, `municipality` or
`actor_gender` (columns), on `properties.<name>` explicitly, or on a bare key, which is read as a
property; a list value means "any of".

| `spec.type` | What it computes |
|---|---|
| `count_events` | number of matching events |
| `count_distinct_actors` | distinct non-null `actor_pseudonym` — the person-level count |
| `count_distinct_devices` | distinct `(device_pseudonym, deduplication window)` pairs — the K11 rule below |
| `count_distinct_villages` | distinct non-null `village_id` |
| `count_distinct_property` | distinct non-null values of `properties.<property>` (lists and objects compared by their canonical JSON) |
| `count_items` | distinct non-null `item_id` |
| `median_property` | median of the numeric `properties.<property>` × `scale`; `null` when no event carries a usable number. Booleans and non-numeric values are skipped, not coerced |
| `mean_property` | the same, as an arithmetic mean |
| `share_property_true` | share of matching events whose `properties.<property>` is truthy; `null` when there are no matching events |
| `ratio_events` | `count(numerator_event_types) / (count(numerator) + count(denominator))`, both filtered by the same `filters`; `null` when both are empty |

Note what `ratio_events` is **not**: the denominator list is the *complement*, not the whole. K13 is
`withheld / (withheld + served)`; K19 is `completed / (completed + cancelled + refused + expired)`.

`count_distinct_property`, `mean_property` and `count_items` are implemented but no current
placeholder spec uses them — they are there so §11 can be transcribed without new code.

## K11 — the one rule that is not provisional

> Distinct pseudonymous device ids over the pilot period, with a single 180-day deduplication.

```json
{"type": "count_distinct_devices",
 "event_types": ["answer_served", "answer_withheld", "itinerary_generated",
                 "visit_recorded", "request_sent", "trail_report"],
 "dedup_days": 180}
```

The engine builds the set of `(device_pseudonym, window)` pairs and counts it
(`_op_count_distinct_devices`). The window index is
`(event date − PILOT_START_DATE).days // dedup_days`, floored at 0 (`dedup_window`):

* windows are anchored at `PILOT_START_DATE` (default `2026-09-01`), not at the query period, so the
  same device produces the same window index in every run;
* anything recorded **before** the pilot started — the synthetic demo history, a pre-pilot test — folds
  into window 0 and cannot inflate the count;
* a device seen again after 180 days counts a second time. That is the deduplication rule as given
  ("reached again after 180 days"), not a defect.

`dedup_days` comes from the spec, falling back to `K11_DEDUP_DAYS` (default 180). A device pseudonym
is stable only for the life of `EVENT_PSEUDONYM_KEY`: rotating the key resets every K11 count
(`docs/events.md`).

## Dimensions

For each KPI the engine writes (`build_cells`):

| `dimension_kind` | `dimension` | When |
|---|---|---|
| `total` | `total` | always |
| `gender` | `female`, `male`, `other`, `not_reported` | when `gender_disaggregated` is true. Only a voluntary self-report reaches the first three; everything else, including `prefer_not_to_say`, lands in `not_reported`, so the four cells reconcile with the total |
| `village` | the village slug | one row per village that the KPI's events actually touched (a cell with zero events is not written) |
| `activity_date_gender` | `YYYY-MM-DD\|<event_type>\|<gender>` | when `person_level` is true — the finest grain, and the one the small-cell rule governs |

## Disclosure control

`services/disclosure.py` runs three rules in this order, over all cells of a run, before anything is
stored. `k_min` is `KPI_K_MIN` (default **5**) and is a minimum: raising it raises the threshold in
the engine, in the review summary and on the dashboard at once.

1. **Small-cell rule** (`small_cell`). Every `date × activity × gender` cell backed by fewer than
   `k_min` distinct persons is suppressed outright and **not written at all**. The finest table the
   dashboard can reach therefore contains no small cell — not a suppressed one, not an empty one.
2. **Primary suppression** (`k<5`). Any remaining cell backed by fewer than `k_min` distinct persons
   or devices loses its value (`value = NULL`, `suppressed = true`); the row stays so the dashboard
   can say *why* a figure is missing. A cell that no individual stands behind carries
   `n_persons = NULL` and is exempt: a count of editorial decisions (entries approved, items
   rejected) says nothing about a host or a visitor, and hiding it would conceal the validation
   gate's own output for no privacy gain.
3. **Secondary suppression** (`secondary`). If exactly **one** gender cell of a KPI is suppressed
   while that KPI's total is published, the smallest surviving gender cell is suppressed too —
   otherwise the hidden value is recoverable by subtracting the published cells from the total. Zero
   suppressed cells means nothing is hidden; two or more means nothing is recoverable.

What counts as "a person behind a cell" (`_persons_behind`):

* a **person-level** KPI counts distinct `actor_pseudonym`;
* any other KPI counts distinct visitor **devices** plus distinct actors whose `actor_role` is `host`
  or `visitor` — the two groups the statistics are about. Staff actions by a validator or an
  ambassador do not make a cell person-backed;
* when neither exists, `n_persons` is `NULL` and rule 2 does not apply.

The **heat map** has its own threshold in the same spirit: visits and trail reports are aggregated
onto a 0.001° grid (≈111 m north–south, ≈82 m east–west at 42.4° N) and a cell is stored only when at
least `k_min` distinct device pseudonyms fall inside it (`build_heat_cells`). A quiet junction never
becomes a row.

The review summary a human signs off (`review_summary`) reports `k_min`, `n_cells`, `n_published`,
`n_suppressed`, the count per rule, the count per dimension kind, `kpis_with_suppressed_cells`,
`kpis_fully_suppressed` and `kpis_unsupported_spec`.

## A run, and the review that publishes it

```
compute → status "computed" → human disclosure review → "published" | "rejected"
```

* `POST /api/kpi/compute` (institution, validator) computes a run over the last `period_days`
  (default 365) and stores it as `computed`. The scheduler does the same nightly at 02:00 UTC.
* `POST /api/kpi/runs/{id}/review` with `{"decision": "publish" | "reject", "note": …}` records the
  reviewer, the timestamp and the note on `kpi_runs`. A run that has already been reviewed cannot be
  reviewed again.
* `GET /api/kpi` returns the **latest published run only**. A computed-but-unreviewed run is not
  readable through it, and neither is a rejected one. `GET /api/kpi/runs` lists runs and their status
  so a reviewer can find the one waiting.

The one bypass is deliberate and labelled: `python -m app.cli kpi-compute --publish` marks the run
published without a review and writes the note *"published without a disclosure review
(kpi-compute --publish, demo only)"* onto the run. Use it to fill a demo laptop, never for a figure
anyone will quote.

## What the dashboard can see

The institutions' dashboard reads **`kpi_aggregates` and `kpi_heat_cells` of a published run, and
nothing else**. It has no path to the `events` table, to `answer_records`, to `consent_records` or to
`users`. Each row it receives is
`{kpi_key, kpi_label, dimension, dimension_kind, value|null, unit, n_persons, n_events, suppressed,
suppression_reason, provisional_definition, note}` — an aggregate, its provenance and, when the value
is missing, the rule that removed it.

`GET /api/kpi/quality` is separate and is not a KPI: it carries the internal metrics — the
speech-to-text word error rate with its `is_synthetic` flag (`docs/samples/README.md`), response-cache
effectiveness and the month's model spend against the cap.

## Reproducing a run

```bash
cd backend && . .venv/bin/activate
TEST_DATABASE_URL=postgresql+psycopg://vrmac:vrmac@127.0.0.1:5432/vrmac_test pytest -q tests/test_kpi.py tests/test_disclosure.py
python -m app.cli kpi-compute --days 365      # against a seeded database
```

On a freshly seeded database (the deterministic synthetic history of `docs/decisions.md` §11, seed
`random.Random(42)`) a 365-day run produced 538 events → 227 cells, of which 86 `date × activity ×
gender` cells were dropped by the small-cell rule, 24 were primary-suppressed and 4
secondary-suppressed, leaving 141 stored rows and 4 heat cells; K23 was the only KPI suppressed at
every dimension. Those figures describe **synthetic sample data**, not usage: they exist so the
suppression rules are visible in the demo. Re-seed and the same numbers come back; delete the events
and the table empties.
