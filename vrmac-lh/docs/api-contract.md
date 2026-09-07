# API contract (agreed interface between backend modules and the Next.js apps)

All paths are prefixed with `/api`. The browser calls same-origin `/api/*`; Next.js proxies to FastAPI.
Auth: `Authorization: Bearer <jwt>` from `POST /api/auth/login`. Roles: `host`, `ambassador`, `validator`,
`institution`; visitors are anonymous and identify a browser session with a random `session_id` (not PII).
Content status: `draft | reviewed | approved | rejected`. **Visitor endpoints return approved rows only**
(they use the RLS-limited DB role `get_public_db` *and* filter `status == 'approved'`).

Shared read models: `app/schemas.py` (`HeritageEntryOut`, `ListingOut`, `TrailSegmentOut`, `TrailReportOut`,
`ProvenanceOut`, `Citation`, `UserOut`, `TokenOut`).

## auth (`app/routers/auth.py`)
| Method | Path | Who | Body → Response |
|---|---|---|---|
| POST | `/api/auth/login` | anyone | `{email, password}` → `TokenOut` |
| GET | `/api/auth/me` | any role | → `UserOut` |

## heritage (`app/routers/heritage.py`)
| GET | `/api/heritage` | public | `?kind=&lang=` → `HeritageEntryOut[]` (approved only) |
| GET | `/api/heritage/calendar` | public | approved `kind=event` entries with `event_date`/`recurrence_rule`, sorted |
| GET | `/api/heritage/{slug_or_id}` | public | `HeritageEntryOut` (404 unless approved) |
| POST | `/api/heritage` | ambassador, validator | entry fields → draft entry (provenance `created`) |
| PUT | `/api/heritage/{id}` | ambassador, validator | fields → new version; approved entries drop to draft |
| GET | `/api/heritage/{id}/provenance` | ambassador, validator, institution | `ProvenanceOut[]` |

## listings (`app/routers/listings.py`)
| GET | `/api/listings` | public | `?category=` → `ListingOut[]` (approved only) |
| GET | `/api/listings/mine` | host | own listings, every status |
| GET | `/api/listings/{slug_or_id}` | public | `ListingOut` (404 unless approved) |
| PUT | `/api/listings/{id}` | host (owner), ambassador | edit → new version, back to draft |
| GET | `/api/listings/{id}/provenance` | host (owner), ambassador, validator, institution | `ProvenanceOut[]` |

## validation (`app/routers/validation.py`)
| GET | `/api/validation/queue` | validator, ambassador | `?item_type=` → `[{item_type, id, title, status, version, created_at, source}]` |
| GET | `/api/validation/items/{item_type}/{id}` | validator, ambassador | `{item_type, item, provenance[]}` (any status) |
| POST | `/api/validation/items/{item_type}/{id}/transition` | per `services/validation.TRANSITIONS` | `{to_status, note}` → item |
| GET | `/api/validation/audit` | validator, institution | last 200 audit rows |

`item_type ∈ heritage_entry | listing | trail_segment | trail_report`.

## ask (`app/routers/ask.py`) — grounded answers or refusal
| POST | `/api/ask` | public (rate-limited) | `{question, lang?: "cnr"|"en", session_id?}` → `AskResponse` |

```
AskResponse = {
  answered: bool, answer: string|null, citations: Citation[], confidence: number,
  refusal_reason: string|null,          # "low_confidence" | "no_approved_source" | "llm_declined"
  refusal_message: string|null,         # localized refusal text
  provider: {llm: string, embeddings: string}, event: "answer_served"|"answer_withheld"
}
```

## onboarding (`app/routers/onboarding.py`) — voice-first host flow
| POST | `/api/onboarding/sessions` | host, ambassador | `{language?, host_user_id? (ambassador on behalf)}` → session (`onboarding_started`) |
| POST | `/api/onboarding/sessions/{id}/audio` | host, ambassador | multipart `file` (webm/ogg/wav/m4a/mp3) → `{status, transcript?, stt}` (`transcript_ready`) |
| POST | `/api/onboarding/sessions/{id}/transcript` | host, ambassador | `{text}` (typed/edited transcript) → session |
| POST | `/api/onboarding/sessions/{id}/draft` | host, ambassador | → `{draft, missing_fields, extraction_method, translation_pending}` (`draft_generated`) |
| POST | `/api/onboarding/sessions/{id}/confirm` | host, ambassador | `{listing: {...fields}, consent: {given: true, method, text_version}}` → `{listing, consent_record_id, duration_seconds, target_minutes, within_target}` (`listing_confirmed`) |
| GET | `/api/onboarding/sessions/{id}` | host, ambassador | session state + timings |
| GET | `/api/onboarding/timing-log` | validator, institution | `[{session_id, started_at, confirmed_at, duration_seconds, stt_provider, llm_provider, within_target}]` |

Draft fields: `title_local, title_en, description_local, description_en, category, price_min, price_max, currency,
season, capacity, accessibility_local, accessibility_en, lat, lng`; `missing_fields` lists what the host must add.

## validation gate for listings
Confirmed listing = `draft` → validator approves via `/api/validation/...` → `approved` + `published_at` → visible.
A listing cannot be approved without a consent record (enforced in `services/validation.transition`).

## kpi (`app/routers/kpi.py`)
| GET | `/api/kpi` | institution, validator | latest run: `{run_id, computed_at, period_start, period_end, k_min, rows: KpiRow[]}` |
| POST | `/api/kpi/compute` | institution, validator | `{period_days?}` → run summary |
| GET | `/api/kpi/heatmap` | institution, validator | GeoJSON FeatureCollection of aggregated cells (k≥5) |
| GET | `/api/kpi/definitions` | public | `[{key, label_en, label_local, formula, unit, person_level: bool}]` |

`KpiRow = {kpi_key, dimension: "total"|"sex=F"|"sex=M"|"sex=X", value: number|null, unit, n_persons, n_events, suppressed, note}`

## map (`app/routers/map.py`)
| GET | `/api/map/features` | public | GeoJSON FeatureCollection: Points for approved entries + listings, LineStrings for approved trails. `properties`: `item_type, id, slug, title_local, title_en, kind|category, coords_approximate, directions_walking, directions_driving, latest_report?` |
| GET | `/api/map/directions` | public | `?lat=&lng=&mode=walking|driving` → `{url}` (Google Maps navigation URL) |

## trails (`app/routers/trails.py`)
| GET | `/api/trails` | public | approved segments + `latest_report` (approved only) |
| GET | `/api/trails/{slug_or_id}` | public | segment + `reports[]` (approved only) |
| GET | `/api/trails/{slug_or_id}/gpx` | public | GPX file (`application/gpx+xml`) |
| POST | `/api/trails/{id}/reports` | public (rate-limited) or any role | `{lat, lng, condition, note, lang?, session_id?}` → 202 `{id, status: "draft"}` (`trail_report` event; visible after validation) |

## itinerary (`app/routers/itinerary.py`)
| POST | `/api/itinerary` | public | `{interests: string[], hours: number, start?: {lat, lng}, lang?, session_id?}` → `{stops: [{item_type, id, slug, title, lat, lng, directions_url, minutes}], route: GeoJSON LineString, total_km, est_hours}` (`itinerary_generated`) |

## requests (`app/routers/requests.py`) — no bookings, no payments
| POST | `/api/requests` | public (rate-limited) | `{listing_id, message, requested_date?, party_size?, session_id}` → request (`request_sent`) |
| GET | `/api/requests/mine?session_id=` | public | the visitor's own requests |
| GET | `/api/requests/host` | host | requests for own listings |
| POST | `/api/requests/{id}/respond` | host (owner) | `{status: "confirmed"|"declined", reply}` → request (`request_confirmed` on confirm) |

## events (`app/routers/events.py`)
| POST | `/api/events` | public (rate-limited) | `{event_type: "visit_recorded", session_id, lat, lng, item_type?, item_id?}` → 201 |
| GET | `/api/events/types` | public | list of event types |

## export (`app/routers/export.py`) — interoperability stub
| GET | `/api/export/ngsi-ld` | public | NGSI-LD normalized `PointOfInterest[]` (+ `@context`) |
| GET | `/api/export/ngsi-ld/keyvalues` | public | key-values form (validated against Smart Data Models schema) |
| GET | `/api/export/dcat-ap` | public | DCAT-AP dataset description (JSON-LD) |

CLI: `python -m app.cli export-ngsi-ld --out exports/` writes both files + validation report.

## meta
`GET /api/health`, `GET /api/meta` (prototype label, languages, maps provider, k-min, onboarding target).

## Events emitted (see `app/models.py: EVENT_TYPES`)
`onboarding_started, transcript_ready, draft_generated, listing_confirmed, entry_approved, itinerary_generated,
answer_served, answer_withheld, request_sent, request_confirmed, trail_report` + `item_rejected`, `visit_recorded`.
