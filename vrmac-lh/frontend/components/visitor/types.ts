/**
 * API shapes used by the visitor app. Coded strictly against `docs/api-contract.md`
 * (map, trails, itinerary, requests, ask, villages, heritage calendar, events, listings, meta)
 * and `backend/app/schemas.py` (`VillageOut`, `HeritageEntryOut`, `ListingOut`, `TrailSegmentOut`,
 * `TrailReportOut`, `Citation`, `SupportResult`).
 *
 * The backend is written concurrently by other agents, so every field the UI can live without is
 * optional: a missing property degrades the screen, it never breaks it.
 */
import type { Feature, FeatureCollection, Geometry, LineString, Position } from "geojson";

export type Municipality = "Tivat" | "Kotor";
export const MUNICIPALITIES: Municipality[] = ["Tivat", "Kotor"];

export type ContentStatus = "draft" | "reviewed" | "approved" | "rejected";
export type MapItemType = "heritage_entry" | "listing" | "trail_segment";
export const MAP_ITEM_TYPES: MapItemType[] = ["heritage_entry", "listing", "trail_segment"];

export type TrailCondition = "good" | "caution" | "blocked";
export const TRAIL_CONDITIONS: TrailCondition[] = ["good", "caution", "blocked"];

export type HeritageKind = "place" | "church" | "building" | "landscape" | "tradition" | "event" | "institution";
export const HERITAGE_KINDS: HeritageKind[] = [
  "place",
  "church",
  "building",
  "landscape",
  "tradition",
  "event",
  "institution",
];

export type ListingCategory = "accommodation" | "food" | "guiding" | "craft" | "experience" | "transport" | "other";
export const LISTING_CATEGORIES: ListingCategory[] = [
  "accommodation",
  "food",
  "guiding",
  "craft",
  "experience",
  "transport",
  "other",
];

/** A geographic point in WGS84, the only coordinate system used anywhere in this app. */
export interface LatLng {
  lat: number;
  lng: number;
}

/* --------------------------------------------------------------------------- villages */

export interface VillageCounts {
  heritage_entries?: number;
  listings?: number;
  trail_segments?: number;
}

/** `VillageOut` (+ `n_approved_items`) — reference data: names, municipality, approximate coordinates. */
export interface Village {
  id: string;
  slug: string;
  name_local: string;
  name_en: string;
  municipality: string;
  ridge_side?: string;
  lat: number | null;
  lng: number | null;
  coords_approximate?: boolean;
  elevation_m?: number | null;
  source?: string;
  /** false while the village's public sources could not be confirmed — the UI must mark it. */
  facts_verified?: boolean;
  verification_note?: string;
  n_approved_items?: number;
  counts?: VillageCounts;
}

/* --------------------------------------------------------------------------- map */

/** `latest_report` as it travels inside GeoJSON properties (services/geo.py `report_summary`). */
export interface TrailReportSummary {
  id?: string;
  condition?: TrailCondition | string;
  note_local?: string;
  note_en?: string;
  reported_at?: string | null;
  lat?: number | null;
  lng?: number | null;
  reporter_role?: string;
}

/** Properties of `GET /api/map/features`. Everything past the contract's core keys is optional. */
export interface MapFeatureProperties {
  item_type: MapItemType;
  id: string;
  slug: string;
  title_local: string;
  title_en: string;
  village_slug?: string | null;
  village_id?: string | null;
  municipality?: string | null;
  coords_approximate?: boolean;
  coords_source?: string;
  directions_walking?: string | null;
  directions_driving?: string | null;
  latest_report?: TrailReportSummary | null;

  kind?: string;
  category?: string;
  summary_local?: string;
  summary_en?: string;
  source?: string;
  elevation_m?: number | null;

  /* listings — host-confirmed structured fields */
  price_min?: number | null;
  price_max?: number | null;
  currency?: string;
  price_note_local?: string;
  price_note_en?: string;
  season_from?: number | null;
  season_to?: number | null;
  season_all_year?: boolean;
  capacity?: number | null;
  accessibility_step_free?: boolean | null;
  accessibility_note_local?: string;
  accessibility_note_en?: string;
  confirmed_fields?: string[];
  photo_url?: string;
  is_sample?: boolean;

  /* trail segments */
  name_local?: string;
  name_en?: string;
  from_name?: string;
  to_name?: string;
  length_m?: number | null;
  ascent_m?: number | null;
  difficulty?: string;
  gpx_url?: string;
  village_slugs?: string[];
}

export type MapFeature = Feature<Geometry | null, MapFeatureProperties>;
export type MapFeatureCollection = FeatureCollection<Geometry | null, MapFeatureProperties>;

/** Stable key of a feature across the map, the list and the detail panel. */
export function featureKey(p: Pick<MapFeatureProperties, "item_type" | "id">): string {
  return `${p.item_type}:${p.id}`;
}

/* --------------------------------------------------------------------------- heritage */

export interface SourceRef {
  title?: string;
  url?: string | null;
}

/** `HeritageEntryOut`. */
export interface HeritageEntry {
  id: string;
  slug: string;
  village_id?: string | null;
  village_slug?: string | null;
  municipality?: string | null;
  kind: string;
  title_local: string;
  title_en: string;
  summary_local?: string;
  summary_en?: string;
  body_local?: string;
  body_en?: string;
  lat: number | null;
  lng: number | null;
  coords_approximate?: boolean;
  coords_source?: string;
  elevation_m?: number | null;
  event_date?: string | null;
  recurrence_rule?: string | null;
  established_year?: number | null;
  source: string;
  sources?: SourceRef[];
  facts_verified?: boolean;
  verification_note?: string;
  tags?: string[];
  status?: ContentStatus;
  version?: number;
  approved_at?: string | null;
  updated_at?: string | null;
}

/** `GET /api/heritage/calendar` — approved `kind=event` entries sorted by `event_date`. */
export type CalendarEntry = HeritageEntry;

/* --------------------------------------------------------------------------- listings */

/** `ListingOut`. The structured fields are **host-entered and host-confirmed**; a model never fills them. */
export interface Listing {
  id: string;
  slug: string;
  village_id?: string | null;
  village_slug?: string | null;
  municipality?: string | null;
  category: string;
  title_local: string;
  title_en: string;
  description_local?: string;
  description_en?: string;
  price_min: number | null;
  price_max: number | null;
  currency?: string;
  price_note_local?: string;
  price_note_en?: string;
  season_from: number | null;
  season_to: number | null;
  season_all_year?: boolean;
  capacity: number | null;
  accessibility_step_free: boolean | null;
  accessibility_note_local?: string;
  accessibility_note_en?: string;
  /** What the host explicitly confirmed: "price" | "season" | "capacity" | "accessibility" | … */
  confirmed_fields?: string[];
  lat: number | null;
  lng: number | null;
  coords_approximate?: boolean;
  photo_url?: string;
  is_sample?: boolean;
  missing_fields?: string[];
  status?: ContentStatus;
  version?: number;
  updated_at?: string | null;
}

/* --------------------------------------------------------------------------- trails */

/** `TrailReportOut` — a geotagged condition report (segment + point). */
export interface TrailReport {
  id: string;
  segment_id?: string;
  village_id?: string | null;
  lat: number;
  lng: number;
  condition: TrailCondition | string;
  note_local?: string;
  note_en?: string;
  reported_at?: string | null;
  reporter_role?: string;
  is_sample?: boolean;
  status?: ContentStatus;
  version?: number;
  approved_at?: string | null;
}

/** `TrailSegmentOut` + `latest_report` + `village_slugs` (`GET /api/trails`). */
export interface Trail {
  id: string;
  slug: string;
  village_id?: string | null;
  village_slugs?: string[];
  name_local: string;
  name_en: string;
  description_local?: string;
  description_en?: string;
  from_name?: string;
  to_name?: string;
  gpx_file?: string | null;
  gpx_url?: string;
  geometry?: LineString | Geometry | null;
  length_m: number | null;
  ascent_m: number | null;
  difficulty?: string;
  lat?: number | null;
  lng?: number | null;
  coords_approximate?: boolean;
  source?: string;
  status?: ContentStatus;
  version?: number;
  latest_report?: TrailReport | TrailReportSummary | null;
  reports?: TrailReport[];
}

export interface TrailReportIn {
  lat: number;
  lng: number;
  condition: TrailCondition;
  note: string;
  lang?: string;
  session_id?: string;
  device_id?: string;
}

/** 202 response: the report is a draft until a validator approves it. */
export interface TrailReportAccepted {
  id?: string;
  status?: ContentStatus;
}

/* --------------------------------------------------------------------------- ask */

/** `Citation` — one approved passage that supports the answer. */
export interface Citation {
  entry_id: string;
  slug: string;
  title: string;
  source: string;
  lang?: string;
  chunk_index?: number;
  score?: number;
  excerpt: string;
  entry_version?: number;
  village_slug?: string | null;
}

/** `SupportResult` — the per-sentence attributability verdict. */
export interface SupportResult {
  sentence: string;
  supported: boolean;
  score?: number;
  method?: string;
  passage_index?: number | null;
  reason?: string;
}

export type RefusalReason =
  | "low_confidence"
  | "no_approved_source"
  | "llm_declined"
  | "unsupported_answer"
  | "assistant_paused";

export interface AskProviders {
  llm?: string;
  embeddings?: string;
  support_check?: string;
}

export interface AskResponse {
  answered: boolean;
  answer: string | null;
  citations: Citation[];
  confidence?: number;
  support?: SupportResult[];
  /** Unsupported sentences removed by the automatic support check before answering. */
  dropped_sentences?: number;
  refusal_reason: RefusalReason | string | null;
  refusal_message: string | null;
  served_from_cache?: boolean;
  provider?: AskProviders;
  event?: "answer_served" | "answer_withheld" | string;
}

/* --------------------------------------------------------------------------- itinerary */

export interface ItineraryRequest {
  interests: string[];
  hours: number;
  start?: LatLng;
  villages?: string[];
  municipality?: string;
  lang?: string;
  session_id?: string;
  device_id?: string;
}

export interface ItineraryStop {
  order?: number;
  item_type?: string;
  id?: string;
  slug?: string;
  title?: string;
  title_local?: string;
  title_en?: string;
  summary_local?: string;
  summary_en?: string;
  lat?: number | null;
  lng?: number | null;
  village_slug?: string | null;
  village_name_local?: string | null;
  village_name_en?: string | null;
  municipality?: string | null;
  minutes_from_previous?: number | null;
  minutes_here?: number | null;
  distance_m?: number | null;
  directions_url?: string | null;
}

/** The `route` the backend returns may be a bare geometry, a Feature or a FeatureCollection. */
export type ItineraryRoute =
  | LineString
  | Geometry
  | Feature<Geometry | null>
  | FeatureCollection<Geometry | null>
  | Position[]
  | null;

export interface ItineraryResponse {
  stops: ItineraryStop[];
  route?: ItineraryRoute;
  total_km?: number | null;
  est_hours?: number | null;
  villages?: string[];
  municipalities?: string[];
  multi_village?: boolean;
}

/* --------------------------------------------------------------------------- requests */

export type RequestStatus = "sent" | "confirmed" | "completed" | "cancelled" | "refused" | "expired";
export const REQUEST_STATUSES: RequestStatus[] = [
  "sent",
  "confirmed",
  "completed",
  "cancelled",
  "refused",
  "expired",
];

/** A visitor's message to a provider. **No booking, no payment.** */
export interface VisitorRequest {
  id: string;
  listing_id: string;
  listing_slug?: string;
  listing_title_local?: string;
  listing_title_en?: string;
  message: string;
  requested_date?: string | null;
  party_size?: number | null;
  status: RequestStatus | string;
  host_reply?: string;
  created_at?: string | null;
  responded_at?: string | null;
  closed_at?: string | null;
  expires_at?: string | null;
}

export interface VisitorRequestIn {
  listing_id: string;
  message: string;
  requested_date?: string | null;
  party_size?: number | null;
  session_id: string;
  device_id?: string;
}

/* --------------------------------------------------------------------------- events */

export interface VisitEventIn {
  event_type: "visit_recorded";
  session_id: string;
  device_id?: string;
  lat: number;
  lng: number;
  item_type?: string;
  item_id?: string;
}
