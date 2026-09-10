# API contract (interface between backend modules and the Next.js apps)

All paths are prefixed with `/api`. The browser calls same-origin `/api/*`; Next.js proxies to FastAPI.
Auth: `Authorization: Bearer <jwt>` from `POST /api/auth/login`. Roles: `host`, `ambassador`, `validator`,
`institution`; visitors are anonymous and send a random `session_id` and `device_id` (kept in the browser,
pseudonymised server-side, never stored in the clear).

**Territory.** Every heritage entry, listing, trail segment, trail report and event carries a `village_id`;
villages carry their `municipality` (Tivat or Kotor). Itineraries may span villages and municipalities.

**Validation gate.** Content status is `draft | reviewed | approved | rejected`. Visitor endpoints return
approved rows only: they use the RLS-limited DB role (`get_public_db`) *and* filter `status == 'approved'`.

Shared read models: `app/schemas.py` — `VillageOut`, `HeritageEntryOut`, `ListingOut`, `TrailSegmentOut`,
`TrailReportOut`, `ProvenanceOut`, `Citation`, `SupportResult`, `UserOut`, `TokenOut`. Every content
read model carries `village_id`, `village_slug` and `municipality`, so a client never has to fetch
`/api/villages` and join by hand.

## auth (`app/routers/auth.py`)
| Method | Path | Who | Body → Response |
|---|---|---|---|
| POST | `/api/auth/login` | anyone | `{email, password}` → `TokenOut` |
| GET | `/api/auth/me` | any role | → `UserOut` |
| POST | `/api/auth/me/gender` | any role | `{gender: "female"\|"male"\|"other"\|"prefer_not_to_say"}` → `UserOut`; **voluntary self-report**, the only way `gender_self_reported` becomes true |

## villages (`app/routers/villages.py`)
| GET | `/api/villages` | public | `?municipality=` → `VillageOut[]` (+ `n_approved_items` per village) |
| GET | `/api/villages/{slug_or_id}` | public | `VillageOut` + counts |

## heritage (`app/routers/heritage.py`)
| GET | `/api/heritage` | public | `?kind=&village=&municipality=` → `HeritageEntryOut[]` (approved only) |
| GET | `/api/heritage/calendar` | public | approved `kind=event` entries, sorted by `event_date` (nulls last) |
| GET | `/api/heritage/{slug_or_id}` | public | `HeritageEntryOut` (404 unless approved) |
| POST | `/api/heritage` | ambassador, validator | entry fields incl. `village` (slug or id) and `source` (required citation) → draft |
| PUT | `/api/heritage/{id}` | ambassador, validator | → new version; an approved entry drops back to draft |
| GET | `/api/heritage/{id}/provenance` | ambassador, validator, institution | `ProvenanceOut[]` |

An entry with `facts_verified=false` may **never** be approved (409 from the validation service).

## listings (`app/routers/listings.py`)
| GET | `/api/listings` | public | `?category=&village=&municipality=` → `ListingOut[]` (approved only) |
| GET | `/api/listings/mine` | host | own listings, every status |
| GET | `/api/listings/{slug_or_id}` | public | `ListingOut` (404 unless approved) |
| PUT | `/api/listings/{id}` | host (owner), ambassador | edit → new version, back to draft |
| GET | `/api/listings/{id}/provenance` | host (owner), ambassador, validator, institution | `ProvenanceOut[]` |

Structured fields (`price_min`, `price_max`, `currency`, `season_from`, `season_to`, `season_all_year`,
`capacity`, `accessibility_step_free`, `accessibility_note_*`) are **host-entered and host-confirmed**;
`confirmed_fields` lists what the host confirmed. A model never fills them.

## validation (`app/routers/validation.py`)
| GET | `/api/validation/queue` | validator, ambassador | `?item_type=&village=` → `[{item_type, id, title, village, municipality, status, version, created_at, source, facts_verified}]` |
| GET | `/api/validation/items/{item_type}/{id}` | validator, ambassador | `{item_type, item, provenance[]}` (any status) |
| POST | `/api/validation/items/{item_type}/{id}/transition` | per `services/validation.TRANSITIONS` | `{to_status, note}` → item |
| GET | `/api/validation/audit` | validator, institution | last 200 audit rows |

`item_type ∈ heritage_entry | listing | trail_segment | trail_report`.

## ask (`app/routers/ask.py`) — grounded answers or refusal
| POST | `/api/ask` | public (rate-limited) | `{question, lang?: "cnr"\|"en", session_id?, device_id?}` → `AskResponse` |

```
AskResponse = {
  answered: bool, answer: string|null, citations: Citation[], confidence: number,
  support: SupportResult[],             # one verdict per candidate sentence
  dropped_sentences: number,            # unsupported sentences removed before answering
  refusal_reason: string|null,          # "low_confidence" | "no_approved_source" | "llm_declined"
                                        # | "unsupported_answer" | "assistant_paused"
  refusal_message: string|null,         # localised
  served_from_cache: bool,
  provider: {llm: string, embeddings: string, support_check: string},
  event: "answer_served" | "answer_withheld"
}
```

Pipeline: retrieve over approved chunks → confidence gate → generate (or extract) → **support check per
sentence** (drop unsupported ones) → if nothing remains, withhold. Cache: exact hash and semantic
(cosine ≥ `CACHE_SEMANTIC_MIN_SIMILARITY`), invalidated when any cited entry's version changes.
When the monthly cap is reached, a valid cache entry is served, otherwise the assistant pauses politely
(`refusal_reason="assistant_paused"`, event `assistant_paused`) — never unsourced text.

## onboarding (`app/routers/onboarding.py`) — voice-first, offline-capable
| POST | `/api/onboarding/sessions` | host, ambassador | `{language?, village?, host_user_id?}` → session (`onboarding_started`) |
| POST | `/api/onboarding/sessions/{id}/heartbeat` | host, ambassador | `{active_seconds_delta}` → `{active_seconds}`; accumulates **active authoring time** |
| POST | `/api/onboarding/sessions/{id}/audio` | host, ambassador | multipart `file` + optional `captured_at` (ISO) and `offline_captured` → `{status, transcript?, stt}` (`transcript_ready`) |
| POST | `/api/onboarding/sessions/{id}/transcript` | host, ambassador | `{text}` → session |
| POST | `/api/onboarding/sessions/{id}/draft` | host, ambassador | → `{draft: {title_local, title_en, description_local, description_en}, extraction_method, translation_pending, fields_required[]}` (`draft_generated`) |
| POST | `/api/onboarding/sessions/{id}/confirm` | host, ambassador | `{listing, consent}` → `{listing, consent_record_id, active_seconds, elapsed_to_confirm_seconds, target_minutes, within_active_target}` (`listing_confirmed`) |
| GET | `/api/onboarding/sessions/{id}` | owner host, its ambassador, ambassador/validator | session state + timings |
| GET | `/api/onboarding/timing-log` | validator, institution | `[{session_id, started_at, active_seconds, elapsed_to_confirm_seconds, elapsed_to_publish_seconds, within_active_target, offline_captured, stt_provider, llm_provider, status}]` |

**The model drafts `title_*` and `description_*` only.** `fields_required` lists the structured fields the
host must fill in (price, season, capacity, accessibility, coordinates). `confirm` rejects a listing whose
structured fields were not confirmed (`confirmed_fields`), 422.

## kpi (`app/routers/kpi.py`)
| GET | `/api/kpi` | institution, validator | latest **published** run: `{run_id, computed_at, period_start, period_end, k_min, definitions_version, definitions_provisional, rows: KpiRow[]}` |
| POST | `/api/kpi/compute` | institution, validator | `{period_days?}` → run summary (status `computed`) |
| POST | `/api/kpi/runs/{id}/review` | validator, institution | `{decision: "publish"\|"reject", note}` → disclosure review; only a published run reaches `/api/kpi` |
| GET | `/api/kpi/runs` | institution, validator | recent runs with status |
| GET | `/api/kpi/heatmap` | institution, validator | GeoJSON of aggregated cells (k≥5) of the published run |
| GET | `/api/kpi/definitions` | public | the K01–K23 definition file (with `provisional` flags) |
| GET | `/api/kpi/quality` | institution, validator | `{stt_wer: {...}, cache: {...}, budget: {...}}` internal metrics |

`KpiRow = {kpi_key, kpi_label, dimension, dimension_kind, value|null, unit, n_persons, n_events,
suppressed, suppression_reason, provisional_definition, note}`

## map (`app/routers/map.py`)
| GET | `/api/map/features` | public | GeoJSON FeatureCollection; properties include `item_type, id, slug, title_local, title_en, village_slug, municipality, coords_approximate, directions_walking, directions_driving, latest_report?` |
| GET | `/api/map/directions` | public | `?lat=&lng=&mode=walking\|driving` → `{url}` |

## trails (`app/routers/trails.py`)
| GET | `/api/trails` | public | approved segments + `latest_report` + `village_slugs` |
| GET | `/api/trails/{slug_or_id}` | public | segment + approved `reports[]` |
| GET | `/api/trails/{slug_or_id}/gpx` | public | GPX (`application/gpx+xml`) |
| POST | `/api/trails/{id}/reports` | public (rate-limited) | `{lat, lng, condition, note, lang?, session_id?, device_id?}` → 202 `{id, status: "draft"}` (`trail_report`) |

## itinerary (`app/routers/itinerary.py`)
| POST | `/api/itinerary` | public | `{interests[], hours, start?, villages?[], municipality?, lang?, session_id?, device_id?}` → `{stops[], route, total_km, est_hours, villages[], municipalities[], multi_village}` (`itinerary_generated`) |

Stops carry `village_slug`, `municipality` and `directions_url`.

## requests (`app/routers/requests.py`) — no bookings, no payments
| POST | `/api/requests` | public (rate-limited) | `{listing_id, message, requested_date?, party_size?, session_id, device_id?}` → (`request_sent`) |
| GET | `/api/requests/mine?session_id=` | public | the visitor's own requests |
| GET | `/api/requests/host` | host | requests for own listings |
| POST | `/api/requests/{id}/respond` | host (owner) | `{status: "confirmed"\|"refused", reply}` → (`request_confirmed` / `request_refused`) |
| POST | `/api/requests/{id}/close` | host (owner) | `{status: "completed"\|"cancelled", note?}` → (`request_completed` / `request_cancelled`) |
| POST | `/api/requests/{id}/cancel` | public (own `session_id`) | `{session_id}` → (`request_cancelled`) |

Expiry: requests older than their `expires_at` are closed as `expired` by the scheduler / CLI
(`request_expired`).

## events (`app/routers/events.py`)
| POST | `/api/events` | public (rate-limited) | `{event_type: "visit_recorded", session_id, device_id?, lat, lng, item_type?, item_id?}` → 201 |
| GET | `/api/events/types` | public | list of event types |

## export (`app/routers/export.py`)
| GET | `/api/export/ngsi-ld` | public | NGSI-LD normalised `PointOfInterest[]` (+ `@context`) |
| GET | `/api/export/ngsi-ld/keyvalues` | public | key-values form, validated against the Smart Data Models schema |
| GET | `/api/export/dcat-ap` | public | DCAT-AP dataset description (JSON-LD) |

All three export responses carry `X-Schema-Valid`, `X-Schema-Id` and `X-Schema-Version`; the DCAT-AP
response reports the verdict of the data it describes.

## meta
`GET /api/health` (providers, spend cap), `GET /api/meta` (prototype label, languages, municipalities,
maps provider, k-min, onboarding target, cache and support-check settings).

## Events emitted (`app/models.py: EVENT_TYPES`, all pseudonymised)
`onboarding_started, transcript_ready, draft_generated, listing_confirmed, entry_approved,
itinerary_generated, answer_served, answer_withheld, request_sent, request_confirmed, request_completed,
request_cancelled, request_refused, request_expired, trail_report` plus `item_rejected`, `visit_recorded`,
`assistant_paused`.
