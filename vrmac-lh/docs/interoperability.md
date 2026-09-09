# Interoperability stub — NGSI-LD `PointOfInterest` + DCAT-AP (innovation claim #6)

> Prototype for the SMART ERA application. Sample data: the heritage entries are public facts with cited
> sources, the provider listings are fictional. No personal data is exported.

The platform exposes its **validated** content in the two formats the European smart-community stack expects:

* **NGSI-LD entities** of type `PointOfInterest` following the FIWARE **Smart Data Models**
  (`dataModel.PointOfInterest`, schema version 0.3.1), ready to be pushed into an NGSI-LD context broker
  (Orion-LD, Scorpio, Stellio).
* A **DCAT-AP** dataset description (JSON-LD) so the export can be listed in a national / EU open-data portal.

Definition of done: *the NGSI-LD export validates against the PointOfInterest JSON schema* — checked on every
export (CLI) and on every API call (`X-Schema-Valid` header), and covered by `backend/tests/test_export.py`.

## What is exported

Only rows that passed the validation gate (`status = 'approved'`), read with the explicit `approved_only`
filter (and, on the API, through the row-level-security-limited visitor DB role) — plus a defensive re-check
of `status` on every row before mapping.

| Source table       | Filter                                   | `category` (first item = primary)                                                       |
|--------------------|------------------------------------------|-----------------------------------------------------------------------------------------|
| `heritage_entries` | approved **and** has `lat`/`lng`          | by `kind`: `place` → `village` (or `town` when tagged `town`), `church`, `building`, `event`, `tradition`, `institution` (→ `culture_house` when tagged `culture-house`), `landscape` |
| `listings`         | approved **and** has `lat`/`lng`          | the listing category: `accommodation`, `food`, `guiding`, `craft`, `experience`, `transport`, `other` |

Not exported: trail segments/reports (they are `LineString`s and condition reports, not POIs — a
`dataModel.Transportation`/`Road` mapping is future work), anything not approved, anything without coordinates,
and **any host identity** (no names, e-mails, phone numbers, user ids).

Entity ids are stable: `urn:ngsi-ld:PointOfInterest:vrmac-lh:<slug>`.

**Unverified territory stays out.** `Village.facts_verified = false` (currently *Gornji Stoliv* and
*Pasiglav*) means no public source could be checked in this build environment, so nothing about those
villages is approved and therefore nothing about them is exported — `tests/test_export.py::
test_unverified_and_non_approved_content_is_absent` asserts that their slugs appear nowhere in the payload,
next to the three `sample-draft|reviewed|rejected-…` gate-test entries.

### Territory: every entity carries its village and its municipality

The prototype covers Vrmac **on both sides of the ridge**, so a POI without its village would be useless for
a municipality that wants to harvest it. Every exported entity therefore carries:

| Where | Value | Example |
|---|---|---|
| `address.addressLocality` | `Village.name_en` | `Gornja Lastva` |
| `address.addressRegion`   | `"<Village.municipality> municipality, Bay of Kotor"` | `Tivat municipality, Bay of Kotor` |
| `address.addressCountry`  | ISO 3166-1 alpha-2 | `ME` |
| `areaServed`              | `Village.name_en` | `Gornja Lastva` |
| `description` (suffix)    | `[village: <slug> — <name_en>, <municipality> municipality]` | `[village: gornja-lastva — Gornja Lastva, Tivat municipality]` |
| `refSeeAlso`              | the village's own `PointOfInterest` (NGSI-LD `Relationship`) | `["urn:ngsi-ld:PointOfInterest:vrmac-lh:gornja-lastva"]` |

`address` uses only the three properties of the vendored `Location-Commons.address` definition, so it stays
schema-valid. The **village slug** has no home in the Smart Data Model, so instead of inventing an attribute
it travels inside `description` in a machine-readable bracket note; `services.export.village_slug_of(entity)`
and `municipality_of(entity)` read both back out (round-tripped in the tests). A POI whose village has its own
approved `place` entry links to it with a real NGSI-LD `Relationship` (`refSeeAlso`); a village never links to
itself.

## Mapping table (our field → `PointOfInterest` attribute)

All target attributes exist in the vendored schema (`GSMA-Commons`, `Location-Commons`, `Contact-Commons` or
the POI-specific block). Nothing outside the schema is emitted, so the export cannot drift into "valid only
because `additionalProperties` is unrestricted" — see *How validation works offline*.

| Our field (heritage entry / listing)                      | NGSI-LD attribute     | Notes |
|-----------------------------------------------------------|-----------------------|-------|
| `slug`                                                    | `id`                  | `urn:ngsi-ld:PointOfInterest:vrmac-lh:<slug>` |
| —                                                         | `type`                | always `PointOfInterest` |
| `title_en` (fallback `title_local`)                       | `name`                | required by the schema |
| `title_local`                                             | `alternateName`       | Montenegrin (Latin script) title |
| `summary_en`/`summary_local`, `description_en`/`description_local` | `description` | one string: `"<en> \| cnr: <local>"`, then the `[village: …]` note and, when `coords_approximate`, `(coordinates approximate)` |
| `kind` (+ tags) / `category`                              | `category`            | array of strings, see table above |
| `lng`, `lat`                                              | `location`            | GeoJSON `Point`, `[lng, lat]` (WGS 84) |
| `village.name_en`, `village.municipality`                 | `address`             | `{addressLocality, addressRegion, addressCountry}` — see the territory table above |
| `village.name_en`                                         | `areaServed`          | plain string (`Location-Commons`) |
| `village.slug` → the village's POI id                     | `refSeeAlso`          | NGSI-LD `Relationship` in the normalized form; omitted when the village has no exported entry |
| `sources[0].url` (fallback `source` citation string)      | `source`              | heritage entries; listings use the constant `"VRMAC-LH host onboarding (host-confirmed, validated listing)"` |
| all `sources[].url`                                       | `seeAlso`             | heritage entries only; omitted when no URL is known (schema needs ≥ 1 item) |
| `price_min`, `price_max`, `currency`, `price_note_en`     | `priceRange`          | listings, e.g. `"12–30 EUR per person"` (illustrative prices) |
| `season_from`, `season_to`, `season_all_year`             | `description`         | listings: `"Season: May–October."` / `"Season: open all year."` / `"Season: from May onwards."` + the Montenegrin sentence (`services.export.season_text`) |
| `accessibility_step_free`, `accessibility_note_en/_local` | `description`         | listings: `"Accessibility: step-free access."` / `"… not step-free."` / `"… not stated by the host."` followed by the host's note, in both languages (`services.export.accessibility_text`) |
| `confirmed_fields`                                        | `description`         | listings: `"Host-confirmed: price, season, capacity, accessibility, coordinates."` — makes explicit that a model never filled these in |
| `capacity`                                                | `capacity`            | listings |
| `is_sample`                                               | `description`         | listings: `"Sample provider (fictional)."` when the text does not already say so |
| `photo_url`                                               | `image`               | listings; absolute URL (`base_url` + `/api/static/…`) |
| — (constant, no PII)                                      | `contactPoint`        | listings: `contactType` = "visitor request through the VRMAC-LH platform…", `availableLanguage: ["cnr","en"]`, `url` = `<base_url>/api/requests` |
| API detail URL                                            | `additionalInfoURL`   | `<base_url>/api/heritage/<slug>` or `/api/listings/<slug>` |
| — (constant)                                              | `dataProvider`        | `"VRMAC-LH prototype (SMART ERA)"` |
| `created_at`                                              | `dateCreated`         | ISO 8601 UTC with `Z` |
| `updated_at` (`published_at` for listings)                | `dateModified`        | ISO 8601 UTC with `Z` |

There is no `season` or `accessibility` attribute in `dataModel.PointOfInterest`, and the host-confirmed
structured fields are too important to drop, so they are rendered as sentences in `description` (both
languages) rather than smuggled in as invented attributes. A future revision can move them to
`dataModel.Hospitality`/`schema.org` extensions with a richer context.

Deliberately **omitted**: `owner` (would reference user ids), `municipalityInfo`/`wardId`/`zoneId`
(IUDX-specific, modelled on Indian urban local bodies), `relevance`, `occupancy`, `title`.

### The three representations

* **key-values** (`GET /api/export/ngsi-ld/keyvalues`, file `pois.keyvalues.json`) — the simplified NGSI-LD
  representation (`?options=keyValues`). This is exactly what the Smart Data Models JSON schema describes,
  so this is the form that is validated.
* **normalized** (`GET /api/export/ngsi-ld`, file `pois.ngsi-ld.json`) — every attribute becomes
  `{"type": "Property", "value": …}`; `location` becomes `{"type": "GeoProperty", "value": <GeoJSON>}`;
  `refSeeAlso` becomes `{"type": "Relationship", "object": ["urn:ngsi-ld:PointOfInterest:…"]}`;
  `dateCreated`/`dateModified` become `{"type": "Property", "value": {"@type": "DateTime", "@value": "…Z"}}`.
  Each entity carries
  `"@context": ["https://smart-data-models.github.io/dataModel.PointOfInterest/context.jsonld", "https://uri.etsi.org/ngsi-ld/v1/ngsi-ld-core-context-v1.6.jsonld"]`.
  Only these three NGSI-LD attribute kinds occur (asserted in the tests).
* **DCAT-AP** (`GET /api/export/dcat-ap`, file `dataset.dcat-ap.jsonld`) — see below.

Both NGSI-LD forms are generated from the same key-values dict (`services.export.to_normalized`), so they
always carry the same attributes.

## How validation works offline

The schema's `$ref`s point at `https://smart-data-models.github.io/...`, which the sandbox (and a demo laptop
without internet) cannot reach. The two schemas are therefore **vendored** under `backend/schemas/sdm/`:

* `PointOfInterest.schema.json` — `$id: https://smart-data-models.github.io/dataModel.PointOfInterest/PointOfInterest/schema.json`
* `common-schema.json` — `$id: https://smart-data-models.github.io/data-models/common-schema.json`
  (`GSMA-Commons`, `Location-Commons`, `Contact-Commons`, `EntityIdentifierType`, …)

`services.export.registry()` builds a `referencing.Registry` that maps **both** public URIs to the vendored
documents (`Resource.from_contents(...)`, specification taken from each document's `$schema`), and
`poi_validator()` hands it to a `jsonschema.Draft202012Validator`. Every `$ref` — the two absolute `allOf`
refs, the nested `#/definitions/...` refs inside `common-schema.json` and the `EntityIdentifierType` ref used
by `refSeeAlso` — resolves through the registry; nothing is fetched. `Draft202012Validator.check_schema` runs
once at load time.

Format checking is real and dependency-free: a `FormatChecker` with checks for `date-time`
(RFC 3339 with time zone) and `uri` (absolute URI with scheme) is attached, so a wrong timestamp or a
relative `seeAlso` link fails validation (`tests/test_export.py::test_broken_entities_fail_validation`).

**`additionalProperties` is unrestricted in the Smart Data Models schemas.** A hand-rolled attribute such as
`villageSlug` would therefore validate happily and the "it validates" claim would be worth nothing. To close
that hole, `known_attributes()` walks the schema's `allOf` branches through the same registry and collects
every property name the model actually defines; `unknown_attributes(entity)` lists anything outside that set
and `validate_entity` reports it as a `knownAttributes` violation. This is why the village slug lives in
`description` and not in an invented attribute.

Every run writes `validation-report.json`:

```json
{
  "schema_id": "https://smart-data-models.github.io/dataModel.PointOfInterest/PointOfInterest/schema.json",
  "schema_version": "0.3.1",
  "validated_at": "2026-09-09T14:54:25Z",
  "n_entities": 15,
  "valid": true,
  "errors": [],
  "villages": ["donja-lastva", "gornja-lastva", "sveti-vid", "tivat"],
  "municipalities": ["Tivat"],
  "offline": true
}
```

`export_all` never claims success on a failure: `valid` is `false` and `errors` lists
`{id, path, message, validator}` for each violation; the API sets `X-Schema-Valid: false`.

To refresh the vendored schemas, download the two URLs above into `backend/schemas/sdm/` (keep the file names)
and update `schema_version` expectations if `$schemaVersion` changed.

## CLI and files

```bash
cd backend && . .venv/bin/activate
python -m app.cli export-ngsi-ld --out ../exports/
```

writes into `exports/` (default `EXPORT_DIR`):

| File                      | Content |
|---------------------------|---------|
| `pois.ngsi-ld.json`       | normalized NGSI-LD entity list (with `@context`) |
| `pois.keyvalues.json`     | key-values entity list (validated) |
| `dataset.dcat-ap.jsonld`  | DCAT-AP dataset description |
| `validation-report.json`  | schema id/version, entity count, `valid`, errors, villages, municipalities |

and prints `{n_entities, valid, schema_version, villages, municipalities, files, errors}`. The CLI uses the
application DB role but the same `approved_only` filter and the same defensive `status` re-check. Link
attributes (`image`, `additionalInfoURL`, `contactPoint.url`) are rendered against
`base_url="http://localhost:8000"` by default — pass `export_all(db, out_dir, base_url="https://…")` to
generate files for a public deployment.

## Pushing into an NGSI-LD context broker (documentation only — not run in the prototype)

The normalized list is a valid body for the NGSI-LD batch upsert operation. With Orion-LD listening on
`localhost:1026`:

```bash
# 1. fetch the normalized entities from the running prototype
curl -s http://localhost:8000/api/export/ngsi-ld -o pois.ngsi-ld.json

# 2. batch upsert (create or replace) into Orion-LD
curl -i -X POST 'http://localhost:1026/ngsi-ld/v1/entityOperations/upsert?options=update' \
  -H 'Content-Type: application/ld+json' \
  --data-binary @pois.ngsi-ld.json

# 3. read back one entity in key-values form
curl -s 'http://localhost:1026/ngsi-ld/v1/entities/urn:ngsi-ld:PointOfInterest:vrmac-lh:crkva-sv-vida?options=keyValues' \
  -H 'Link: <https://smart-data-models.github.io/dataModel.PointOfInterest/context.jsonld>; rel="http://www.w3.org/ns/json-ld#context"; type="application/ld+json"'

# 4. geo-query: POIs within 2 km of Gornja Lastva
curl -s 'http://localhost:1026/ngsi-ld/v1/entities?type=PointOfInterest&georel=near;maxDistance==2000&geometry=Point&coordinates=[18.6919,42.4425]&options=keyValues' \
  -H 'Link: <https://smart-data-models.github.io/dataModel.PointOfInterest/context.jsonld>; rel="http://www.w3.org/ns/json-ld#context"; type="application/ld+json"'

# 5. everything in one village / one municipality (the territory attributes)
curl -s 'http://localhost:1026/ngsi-ld/v1/entities?type=PointOfInterest&q=address.addressLocality=="Gornja Lastva"&options=keyValues' \
  -H 'Link: <https://smart-data-models.github.io/dataModel.PointOfInterest/context.jsonld>; rel="http://www.w3.org/ns/json-ld#context"; type="application/ld+json"'
```

Notes for a real deployment: the broker must be able to fetch the two `@context` URLs (or be given a local
copy through its context cache); `entityOperations/upsert` needs `Content-Type: application/ld+json` because
the context is inline; re-running the command is idempotent (same `id`s → replace). `refSeeAlso` is a
`Relationship`, so the village entity should be upserted in the same batch (it is — the list is one payload).
Withdrawn content is *not* deleted from the broker by this prototype: a production sync would diff the
exported id set against `GET /ngsi-ld/v1/entities?type=PointOfInterest` and `DELETE` the difference.

## DCAT-AP notes

`GET /api/export/dcat-ap` (and `dataset.dcat-ap.jsonld`) is a single `dcat:Dataset` in JSON-LD with the
prefixes `dcat`, `dct`, `foaf`, `vcard`, `xsd`, `locn`, `geo`, `rdfs`:

* `@id` = `<base_url>/api/export/dcat-ap#dataset`; `dct:identifier` = `vrmac-lh-points-of-interest`.
* `dct:title` / `dct:description` language-tagged in `en` and `cnr`; both state that this is a **prototype
  with sample (fictional) providers** and that only validated content is exported.
* `dct:publisher` — `foaf:Agent` "VRMAC-LH prototype consortium (sample)"; `dcat:contactPoint` — a
  `vcard:Kind` with a role name only (no personal contact).
* `dct:license` — CC BY 4.0; `dct:accessRights` — PUBLIC.
* `dcat:keyword` — topic keywords plus the **villages and municipalities** actually present in the export and
  the POI categories, so a portal search on "Gornja Lastva" or "Tivat municipality" finds the dataset.
* `dcat:theme` — EU data-theme NAL `EDUC` (education, culture and sport), `ENVI` (cultural landscape),
  `REGI` (regions and cities). `TRAN` is left out because trails/directions are not part of this dataset.
* `dct:language` — EU language NAL `ENG` and `CNR`.
* `dct:spatial` — a `dct:Location` with a bilingual `rdfs:label` (the municipalities covered), `dcat:bbox`
  (WKT `POLYGON` as `geo:wktLiteral`) **and** `locn:geometry` (GeoJSON literal typed
  `application/vnd.geo+json`), all computed from the exported points.
* `dct:temporal` — a `dct:PeriodOfTime` with `dcat:startDate` = earliest `dateCreated` and `dcat:endDate` =
  latest `dateModified` of the exported entities (typed `xsd:dateTime`).
* `dct:accrualPeriodicity` — `CONT` (the API reflects the live validated content).
* `dct:issued` / `dct:modified` — earliest `dateCreated` / latest `dateModified` of the exported entities.
* `dct:conformsTo` — the Smart Data Models PointOfInterest schema URI (on the dataset and on each distribution).
* `dct:provenance` — a `dct:ProvenanceStatement` stating that this is a prototype with sample providers,
  approximate coordinates and validated-only content.
* `rdfs:comment` — the counts (entities, heritage entries, listings, villages, municipalities) and the schema
  version the key-values form was validated against.
* `dcat:distribution` — two `dcat:Distribution`s: normalized NGSI-LD (`application/ld+json`) and key-values
  (`application/json`), each with a bilingual title and description, `accessURL`/`downloadURL`, `mediaType`,
  `dct:format`, `dct:license` and `dct:conformsTo`.

The base URL comes from the incoming request (`request.base_url`); behind the Next.js proxy set the
public origin at the proxy or generate the file with `export_all(db, out_dir, base_url="https://…")`.

## API

| Method | Path | Response | Headers |
|---|---|---|---|
| GET | `/api/export/ngsi-ld` | normalized `PointOfInterest[]` with `@context` (`application/ld+json`) | `X-Schema-Valid`, `X-Schema-Id`, `X-Schema-Version` |
| GET | `/api/export/ngsi-ld/keyvalues` | key-values `PointOfInterest[]` (`application/json`) | idem |
| GET | `/api/export/dcat-ap` | `dcat:Dataset` (`application/ld+json`) | idem — a harvester must never advertise a dataset whose entities do not validate |

All three are public, rate-limited (`RATE_LIMIT_PUBLIC`) and read through `get_public_db`.

## Limits / next steps

* The vendored schema is a snapshot (0.3.1); the SDM project publishes updates without changing the URL.
* Season, accessibility and the host-confirmation marker are prose inside `description`; a richer model
  (or a project-specific `@context` extension) would make them queryable in the broker.
* Trails should be exported as a second entity type once a fitting Smart Data Model is agreed.
* DCAT-AP validity against the official SHACL shapes has not been machine-checked in the sandbox (no network);
  the document follows DCAT-AP 2.1 mandatory/recommended properties.
* Deletions are not propagated to a context broker (see the sync note above).
