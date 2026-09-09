/** Read models and constants for the validator queue and the institution dashboard.
 *  Mirrors backend/app/schemas.py + services/validation.TRANSITIONS + docs/api-contract.md. */
import type { Feature, FeatureCollection, Point, Polygon } from "geojson";

export type Role = "host" | "ambassador" | "validator" | "institution";
export type Status = "draft" | "reviewed" | "approved" | "rejected";
export type ItemType = "heritage_entry" | "listing" | "trail_segment" | "trail_report";

export const STATUS_VALUES: Status[] = ["draft", "reviewed", "approved", "rejected"];
export const ITEM_TYPES: ItemType[] = ["heritage_entry", "listing", "trail_segment", "trail_report"];
export const HERITAGE_KINDS = ["place", "church", "building", "event", "tradition", "institution", "landscape"] as const;
export type HeritageKind = (typeof HERITAGE_KINDS)[number];

/* ---------- validation ---------- */

export interface QueueItem {
  item_type: ItemType;
  id: string;
  title: string;
  status: Status;
  version: number;
  created_at: string;
  source: string;
}

export interface ProvenanceOut {
  id: string;
  item_type: ItemType;
  item_id: string;
  version: number;
  action: string;
  from_status: Status | null;
  to_status: Status | null;
  actor_user_id: string | null;
  actor_role: string;
  source: string;
  note: string;
  created_at: string;
}

export interface SourceRef {
  title: string;
  url?: string | null;
}

export interface HeritageEntryOut {
  id: string;
  slug: string;
  kind: string;
  title_local: string;
  title_en: string;
  summary_local: string;
  summary_en: string;
  body_local: string;
  body_en: string;
  lat: number | null;
  lng: number | null;
  coords_approximate: boolean;
  coords_source: string;
  elevation_m: number | null;
  event_date: string | null;
  recurrence_rule: string | null;
  established_year: number | null;
  source: string;
  sources: SourceRef[];
  tags: string[];
  status: Status;
  version: number;
  approved_at: string | null;
  updated_at: string;
}

export interface ListingOut {
  id: string;
  slug: string;
  category: string;
  title_local: string;
  title_en: string;
  description_local: string;
  description_en: string;
  price_min: number | null;
  price_max: number | null;
  currency: string;
  season: string | null;
  capacity: number | null;
  accessibility_local: string;
  accessibility_en: string;
  lat: number | null;
  lng: number | null;
  coords_approximate: boolean;
  photo_url: string;
  is_sample: boolean;
  missing_fields: string[];
  extraction_method: string;
  translation_pending: boolean;
  /** Not part of ListingOut in schemas.py yet; the validator needs it to see consent before approving. */
  consent_record_id?: string | null;
  status: Status;
  version: number;
  approved_at: string | null;
  published_at: string | null;
  updated_at: string;
}

export interface TrailSegmentOut {
  id: string;
  slug: string;
  name_local: string;
  name_en: string;
  description_local: string;
  description_en: string;
  from_name: string;
  to_name: string;
  gpx_file: string | null;
  geometry: { type?: string; coordinates?: unknown } | Record<string, unknown>;
  length_m: number | null;
  ascent_m: number | null;
  difficulty: string;
  lat: number | null;
  lng: number | null;
  coords_approximate: boolean;
  source: string;
  status: Status;
  version: number;
  approved_at: string | null;
}

export interface TrailReportOut {
  id: string;
  segment_id: string;
  lat: number;
  lng: number;
  condition: string;
  note_local: string;
  note_en: string;
  reported_at: string;
  reporter_role: string;
  is_sample: boolean;
  status: Status;
  version: number;
  approved_at: string | null;
}

export type AnyItem = HeritageEntryOut | ListingOut | TrailSegmentOut | TrailReportOut;

export interface ValidationItem {
  item_type: ItemType;
  item: AnyItem;
  provenance: ProvenanceOut[];
}

export interface TransitionIn {
  to_status: Status;
  note: string;
}

/** (from → to) → roles allowed. Mirrors backend/app/services/validation.py TRANSITIONS. */
export const TRANSITIONS: Record<string, Role[]> = {
  "draft->reviewed": ["ambassador", "validator"],
  "reviewed->approved": ["validator"],
  "draft->approved": ["validator"],
  "draft->rejected": ["validator"],
  "reviewed->rejected": ["validator"],
  "reviewed->draft": ["ambassador", "validator"],
  "rejected->draft": ["host", "ambassador", "validator"],
  "approved->draft": ["validator"],
};

/** Target statuses the given role may move an item to from `from`. Order: reviewed, approved, rejected, draft. */
export function allowedTransitions(from: Status, role: Role): Status[] {
  const order: Status[] = ["reviewed", "approved", "rejected", "draft"];
  return order.filter((to) => (TRANSITIONS[`${from}->${to}`] ?? []).includes(role));
}

export interface AuditRow {
  id: string;
  occurred_at: string;
  user_id?: string | null;
  role: string;
  action: string;
  resource_type: string;
  resource_id: string;
  detail: Record<string, unknown>;
  request_id: string;
}

/** Body of POST /api/heritage (creates a draft). */
export interface HeritageEntryIn {
  slug: string;
  kind: HeritageKind;
  title_local: string;
  title_en: string;
  summary_local: string;
  summary_en: string;
  body_local: string;
  body_en: string;
  lat: number | null;
  lng: number | null;
  coords_approximate: boolean;
  coords_source: string;
  source: string;
  sources: SourceRef[];
  tags: string[];
}

/* ---------- kpi ---------- */

export type KpiDimension = "total" | "sex=F" | "sex=M" | "sex=X";

export interface KpiRow {
  kpi_key: string;
  dimension: KpiDimension;
  value: number | null;
  unit: string;
  n_persons: number | null;
  n_events: number;
  suppressed: boolean;
  note: string;
}

export interface KpiRun {
  run_id: string | null;
  computed_at: string | null;
  period_start: string | null;
  period_end: string | null;
  k_min: number;
  rows: KpiRow[];
}

export interface KpiDefinition {
  key: string;
  label_en: string;
  label_local: string;
  formula: string;
  unit: string;
  person_level: boolean;
}

export interface HeatCellProps {
  cell_lat: number;
  cell_lng: number;
  cell_size_deg?: number;
  n_visits: number;
  n_sessions: number;
}

export type HeatFeature = Feature<Polygon | Point, HeatCellProps>;
export type HeatmapCollection = FeatureCollection<Polygon | Point, HeatCellProps>;

/* ---------- onboarding timing ---------- */

export interface TimingRow {
  session_id: string;
  started_at: string;
  confirmed_at: string | null;
  duration_seconds: number | null;
  stt_provider: string;
  llm_provider: string;
  within_target: boolean | null;
  /** Optional in the contract; shown when the backend includes it. */
  status?: string;
}
