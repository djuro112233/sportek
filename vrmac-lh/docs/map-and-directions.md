# Map, directions, trails and requests

> Innovation claim #5. An interactive map of the whole territory, real navigation to every point, GPX
> trails carrying their latest **approved** condition report, day plans that cross village and
> municipality boundaries, and a request lifecycle that is a conversation — **no bookings, no
> payments**.

Everything visitor-facing here reads through the row-level-security-limited visitor session
(`get_public_db`) **and** the explicit `validation.approved_only` filter. A draft, reviewed or
rejected item cannot reach the map, a GPX download or an itinerary.

## Base map: MapLibre GL over OpenStreetMap

`frontend/components/map/MapView.tsx` builds the map from an **inline** raster style:

```ts
tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"], tileSize: 256, maxzoom: 19,
attribution: "© OpenStreetMap contributors"
```

Why this and not a commercial SDK:

* **Open source.** MapLibre GL is a BSD-licensed fork of Mapbox GL JS; the prototype is AGPL-3.0 and
  carries no proprietary map SDK.
* **No API cost and no account.** There is no key to obtain, no billing to set up and nothing to
  expire between building the prototype and showing it. `docker compose up` gives a working map.
* **No style server.** The style object is in the source, so there is no third-party style endpoint in
  the critical path of the demo.
* **Attribution is always visible.** `AttributionControl` is not compact, and the attribution string
  is part of the source definition — OpenStreetMap's licence requires the credit, and it is not
  something a layout change can drop.

Point items become real `<button>` markers with an accessible name, so the map is keyboard-reachable;
trail segments go into a GeoJSON source drawn as lines. Symbols differ by **shape** first — ◆ heritage,
■ listing, ▲ trail, ◉ you, ✚ report, ✕ picked point, ● itinerary stop — and the condition of a trail is
carried by colour *and* dash pattern, so colour is never the only difference (WCAG 1.4.1). An
invisible 20 px hit line makes a 4 px trail tappable on a phone, and all animation is skipped under
`prefers-reduced-motion`.

### The optional Google base layer

`MAPS_PROVIDER=google` plus a `GOOGLE_MAPS_API_KEY` switches the *base layer* only.
`GET /api/meta` reports `maps_provider` and, when it is `google`, the key; `MapPanel.tsx` renders
`GoogleMapView` when both are present and falls back to MapLibre when the key is missing, saying so in
the caption. `GoogleMapView` implements the same `BaseMapProps` contract as `MapView`, so no page
knows which base map it is talking to. The shipped default is `MAPS_PROVIDER=osm`; the Google layer
exists because a partner may already have a maps contract, not because the prototype needs it.

Directions are unaffected either way — they need no key at all.

## Directions: Google Maps navigation deep links

`services/geo.py: directions_url` builds exactly this, and `tests/test_geo.py` pins the format:

```
https://www.google.com/maps/dir/?api=1&destination=<lat>,<lng>&travelmode=walking|driving
```

Coordinates are rounded to 6 decimals (≈0.1 m, far finer than the approximate seed data) so links stay
short and stable; a mode other than `walking`/`driving` and a coordinate outside the WGS84 range raise
before a URL is produced. `GET /api/map/directions?lat=&lng=&mode=` returns `{url, mode, destination,
provider: "google-maps-deeplink", maps_provider}`, and every map feature and itinerary stop already
carries `directions_walking` / `directions_driving` so the button needs no extra call.

Why a deep link rather than server-side routing:

* **Real routing, on the visitor's own device.** The link opens the navigation app the visitor already
  has, with live traffic, offline maps and turn-by-turn — none of which this prototype could match.
* **No API key, no quota, no bill.** The `dir/?api=1` form is the documented keyless URL scheme.
  A Directions API integration would need a key, a billing account and a per-request cost.
* **The server never calls Google.** No visitor coordinate, no request and no key leaves this process.
  The visitor's *origin* is never sent anywhere by us: the URL carries the destination only, and the
  navigation app asks the device for the starting point.
* **Nothing to keep in sync.** There is no routing graph, no OSRM/Valhalla instance and no road data
  to maintain for a plateau whose paths are mostly unmapped.

The trade-off is honest: the visitor leaves the app for navigation, and a device with no Google Maps
falls back to whatever handles the URL.

## Map features

`GET /api/map/features` returns a GeoJSON `FeatureCollection` of every approved item that has
coordinates — Points for heritage entries and listings, LineStrings for trail segments — in a
deterministic order (entries, then listings, then trails, each by slug), with a `bbox` so a map can fit
the view in one pass. `?village=`, `?municipality=` and `?item_type=` filter it; an unknown
`item_type` is a 422 rather than a silently empty result.

Every feature carries `item_type`, `id`, `slug`, `title_local`, `title_en`, `village_slug`,
`village_name_local`, `village_name_en`, `municipality`, `coords_approximate`, `coords_source`,
`directions_walking` and `directions_driving`. Listings additionally carry the **host-confirmed**
structured fields (`price_min`, `price_max`, `currency`, `season_*`, `capacity`,
`accessibility_step_free`, the accessibility notes and `confirmed_fields`); trail segments carry
`from_name`, `to_name`, `length_m`, `ascent_m`, `difficulty`, `gpx_url`, `village_slugs` and
`latest_report`.

## Trails and GPX

`GET /api/trails` lists approved segments; `GET /api/trails/{slug_or_id}` adds the approved reports,
newest first; `GET /api/trails/{slug_or_id}/gpx` returns GPX 1.1 as `application/gpx+xml`. A segment
that is not approved is a 404 on all three.

A segment's track comes from one of two places (`gpx_for_segment`), and the response says which in the
`X-GPX-Origin` header:

| Origin | When | How |
|---|---|---|
| `file` | the segment names a stored `gpx_file` | `safe_gpx_path` resolves `seed_data/gpx/<name>` **only** for a bare `*.gpx` file name: anything containing a path separator, `.`, `..`, or resolving outside that directory is rejected and the generated track is used instead. A stored name can never read an arbitrary file |
| `generated` | no file, or the name was rejected | `segment_to_gpx` writes one track/one segment from the stored GeoJSON `LineString`, carrying elevation when the geometry has a third ordinate |

Both are approximate in this prototype, and both say so: the creator is *"VRMAC-LH prototype (sample,
approximate)"*, the description appends "Coordinates are approximate." when `coords_approximate` is
set, and the response carries `X-Coords-Approximate`. Of the two approved seed segments, Donja
Lastva – Gornja Lastva ships a stored file and Gornja Lastva – Sveti Vid is generated from its
geometry.

A segment belongs to a village and **lists every village it connects** (`village_slugs`), so
`?village=` and `?municipality=` match on any of them, not only on the start.

### Condition reports go through the validation gate

`POST /api/trails/{id}/reports` accepts `{lat, lng, condition: good|caution|blocked, note, lang,
session_id, device_id}` from anyone — an anonymous visitor with a random client id, or a signed-in
host, ambassador or validator (an anonymous call without a `session_id` is a 422).

The report is created as a **draft** through `services/validation.create_item`, with the provenance
source *"condition report submitted from the visitor app (`<condition>`)"*, and the response is
**202 Accepted** with a localised message: *"Your report has been recorded and becomes visible on the
map only after a validator has checked it."* Nothing about it is public until then.

What the map shows is `latest_approved_report` — the newest **approved** report of the segment, by
`reported_at` then `created_at`. A draft closure notice cannot appear on the map, which is the point:
an unvalidated "blocked" would send walkers the wrong way as effectively as a wrong trail.

The report inherits the segment's `village_id`, so it lands in the territory model, and the
`trail_report` event carries its coordinates and condition into the heat map and K20.

## Approximate coordinates

Every coordinate in this build is hand-placed. The model says so rather than implying survey
accuracy:

* `coords_approximate` defaults to **true** on villages, heritage entries, listings and trail
  segments, and travels on every map feature and every itinerary stop;
* `coords_source` says where the position came from (a listing's is `"host-entered
  (approximate)"`, a trail's is its `source` string);
* every feature collection and every itinerary carries `coords_note` / `prototype_note` in both
  languages: *"Coordinates of the sample data are approximate (coords_approximate=true)."*;
* the seed rows carry it in their own `verification_note`, e.g. *"Coordinates approximate per
  hr.wikipedia; to be replaced by K4's surveyed GPX."*

The policy is: **approximate until K4's surveyed GPX replaces them**. When the surveyed tracks arrive,
the coordinates and the GPX files are replaced and `coords_approximate` is set to false per row —
nothing in the code needs to change, and the flag stops appearing in the interface by itself. Until
then no distance, ascent or arrival time on this platform should be treated as survey-grade.

Village coordinates are reference data and carry no claim; a village whose facts could not be verified
(`facts_verified = false`, currently Gornji Stoliv and Pasiglav) can never be approved, so nothing
about it reaches the map at all (`docs/decisions.md` §3).

## Itineraries across the territory

`POST /api/itinerary` takes `{interests[], hours, start?, villages?[], municipality?, lang,
session_id?, device_id?}`. Candidates are approved heritage entries and listings with coordinates,
matched against the interests (`INTEREST_VALUES` = the seven heritage kinds plus the seven listing
categories, with aliases such as `heritage`, `culture`, `nature`, `stay`, `eat`); an unknown interest
is a 422 that names the accepted values, and a non-existent village is a 404.

`plan_itinerary` is a greedy nearest-neighbour walk from the start point (default: the shore trailhead
in Donja Lastva, approximate) within the hours given. Travel time is the haversine distance ×
`DETOUR_FACTOR` 1.3 at `WALK_KMH` 4.0, plus `MINUTES_PER_STOP` 20 at each stop; a stop is added while
`elapsed + travel + 20 min` fits, and ties break on the slug, so the same request always returns the
same plan. The assumptions travel back in the response in both languages.

**The walk deliberately ignores village boundaries.** The nearest next stop may be in another village
or another municipality, so a plan spans the territory by default rather than by request. The response
carries `villages[]`, `municipalities[]`, `multi_village` and `multi_municipality`, every stop carries
its `village_slug`, `municipality` and its own `directions_url`, and the `itinerary_generated` event
carries `multi_village` — which is what K15 reads.

Whether a plan can be *cross-municipality* is a data question, not a code one: the Kotor-side content
is unverified and therefore unapproved, so on the seeded data `multi_municipality` is false. Verify
Gornji Stoliv and it becomes true with no change to the planner.

## Visitor requests — no bookings, no payments

A request is a **message** from a visitor to a provider. Nothing is held, nothing is charged, and the
prototype never asks the visitor for a name, an e-mail address or a phone number: the only identifier
is the random `session_id` their browser keeps, which is never shown to the host and never written to
the event stream in the clear.

```
sent ──> confirmed ──> completed
  │  └──> refused        └──> cancelled
  └──> cancelled (visitor or host)
sent | confirmed ──> expired   (scheduler / python -m app.cli expire-requests)
```

`REQUEST_TRANSITIONS` is the whole rule set; an impossible step is a 409, and a host may only act on
requests for their **own** listings (403 otherwise), a visitor only on a request matching their own
`session_id`.

`expires_at` is set when the request is created — the day after the requested date, or 30 days after
sending when no date was given — so an unanswered request closes itself instead of sitting in a
provider's list forever. `expire_stale_requests` is idempotent: a closed request is never touched
again.

The host's view (`host_payload`) carries the message, the dates, the party size and what they may do
next — **never** the visitor's session id — plus a standing note: *"A confirmation is a message to the
visitor, not a reservation: no booking and no payment."* The consent text the host agrees to says the
same thing in both languages, and `docs/api-contract.md` says it at the endpoint. Every transition
emits its event (`request_sent`, `request_confirmed`, `request_completed`, `request_cancelled`,
`request_refused`, `request_expired`), which is where K16–K19 come from.

## Checking it

```bash
cd backend && . .venv/bin/activate
TEST_DATABASE_URL=postgresql+psycopg://vrmac:vrmac@127.0.0.1:5432/vrmac_test pytest -q tests/test_geo.py tests/test_itinerary.py tests/test_requests.py
```

`tests/test_geo.py` covers the deep-link format, the feature collection, GPX from a file and from
geometry, the path-traversal guard and the approved-report rule; `tests/test_itinerary.py` covers the
planner and the multi-village flags; `tests/test_requests.py` covers the lifecycle, the ownership
rules and expiry. The frontend map components are type-checked and built by `make test-frontend`.
