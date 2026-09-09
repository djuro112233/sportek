/** Read models and constants for the validator queue and the institution dashboard.
 *
 *  Mirrors `backend/app/schemas.py`, `backend/app/models.py`,
 *  `backend/app/services/validation.py` (TRANSITIONS) and `docs/api-contract.md`.
 *  Fields the contract does not pin down exactly are optional so a partially built
 *  backend renders as "—" instead of crashing the screen.
 */
import type { Feature, FeatureCollection, Point, Polygon } from "geojson";

export type Role = "host" | "ambassador" | "validator" | "institution";
export type Status = "draft" | "reviewed" | "approved" | "rejected";
export type ItemType = "heritage_entry" | "listing" | "trail_segment" | "trail_report";

export const STATUS_VALUES: Status[] = ["draft", "reviewed", "approved", "rejected"];
export const ITEM_TYPES: ItemType[] = ["heritage_entry", "listing", "trail_segment", "trail_report"];
export const MUNICIPALITIES = ["Tivat", "Kotor"] as const;
export type Municipality = (typeof MUNICIPALITIES)[number];
export const HERITAGE_KINDS = ["place", "church", "building", "event", "tradition", "institution", "landscape"] as const;
export type HeritageKind = (typeof HERITAGE_KINDS)[number];

/* ---------- territory ---------- */

/** `VillageOut` (+ the approved-item counters of `/api/villages`). Reference data, no claims. */
export interface Village {
  id: string;
  slug: string;
  name_local: string;
  name_en: string;
  municipality: string;
  ridge_side: string;
  lat: number | null;
  lng: number | null;
  coords_approximate: boolean;
  elevation_m: number | null;
  source: string;
  facts_verified: boolean;
  verification_note: string;
  n_approved_items?: number;
  counts?: { heritage_entries?: number; listings?: number; trail_segments?: number };
}

/* ---------- validation ---------- */

/** One row of `GET /api/validation/queue`. `village` is a slug (or a name when no slug is set). */
export interface QueueItem {
  item_type: ItemType;
  id: string;
  title: string;
  village: string | null;
  municipality: string | null;
  status: Status;
  version: number;
  created_at: string;
  source: string;
  /** false ⇒ the facts of this item could not be checked; it may never be approved (409). */
  facts_verified: boolean;
}

export interface ProvenanceOut {
  id: string;
  item_type: string;
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
  village_id: string;
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
  facts_verified: boolean;
  verification_note: string;
  tags: string[];
  status: Status;
  version: number;
  approved_at: string | null;
  updated_at: string;
}

/** `ListingOut`. price / season / capacity / accessibility are **host-entered and host-confirmed**. */
export interface ListingOut {
  id: string;
  slug: string;
  village_id: string;
  category: string;
  title_local: string;
  title_en: string;
  description_local: string;
  description_en: string;
  price_min: number | null;
  price_max: number | null;
  currency: string;
  price_note_local: string;
  price_note_en: string;
  season_from: number | null;
  season_to: number | null;
  season_all_year: boolean;
  capacity: number | null;
  accessibility_step_free: boolean | null;
  accessibility_note_local: string;
  accessibility_note_en: string;
  /** Structured fields the host actually confirmed; a model never fills them. */
  confirmed_fields: string[];
  lat: number | null;
  lng: number | null;
  coords_approximate: boolean;
  photo_url: string;
  is_sample: boolean;
  missing_fields: string[];
  extraction_method: string;
  translation_pending: boolean;
  /** Consent is required before approval (409 without it). Either field may carry it. */
  consent_record_id?: string | null;
  consent_present?: boolean;
  status: Status;
  version: number;
  approved_at: string | null;
  published_at: string | null;
  updated_at: string;
}

export interface TrailSegmentOut {
  id: string;
  slug: string;
  village_id: string;
  village_slugs: string[];
  name_local: string;
  name_en: string;
  description_local: string;
  description_en: string;
  from_name: string;
  to_name: string;
  gpx_file: string | null;
  geometry: Record<string, unknown>;
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
  village_id: string | null;
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
/** The item as it arrives: a known shape plus whatever else the backend adds. */
export type RawItem = Record<string, unknown>;

export interface ValidationItem {
  item_type: ItemType;
  item: RawItem;
  provenance: ProvenanceOut[];
}

export interface TransitionIn {
  to_status: Status;
  note: string;
}

/** (from → to) → roles allowed. Mirrors `backend/app/services/validation.py` TRANSITIONS. */
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

/** Target statuses `role` may move an item to from `from`. Order: reviewed, approved, rejected, draft. */
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

/** Body of `POST /api/heritage` — always creates a draft. The slug is derived server-side. */
export interface HeritageEntryIn {
  village: string;
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
  event_date: string | null;
  established_year: number | null;
  source: string;
  sources: SourceRef[];
  facts_verified: boolean;
  verification_note: string;
  tags: string[];
}

/* ---------- kpi ---------- */

/** Gender buckets of the dashboard. Filled **only** from a voluntary self-report. */
export const GENDER_DIMENSIONS = ["female", "male", "other", "not_reported"] as const;
export type GenderDimension = (typeof GENDER_DIMENSIONS)[number];

export type DimensionKind = "total" | "gender" | "village" | "activity_date" | (string & {});

/** One published cell (`KpiAggregate`). Never carries an id of a person or a session. */
export interface KpiRow {
  kpi_key: string;
  kpi_label?: string;
  dimension: string;
  dimension_kind: DimensionKind;
  value: number | null;
  unit: string;
  n_persons: number | null;
  n_events: number;
  suppressed: boolean;
  suppression_reason?: string;
  provisional_definition?: boolean;
  note?: string;
}

/** `GET /api/kpi` — the latest **published** run, or an empty envelope when none is published. */
export interface KpiSnapshot {
  run_id: string | null;
  computed_at: string | null;
  period_start: string | null;
  period_end: string | null;
  k_min: number;
  definitions_version: string;
  definitions_provisional: boolean;
  rows: KpiRow[];
  status?: string;
}

export type RunStatus = "computed" | "reviewed" | "published" | "rejected" | (string & {});

/** A row of `GET /api/kpi/runs` / the summary returned by `POST /api/kpi/compute` (`KpiRun`). */
export interface KpiRunSummary {
  id?: string;
  run_id?: string;
  computed_at: string | null;
  period_start: string | null;
  period_end: string | null;
  k_min?: number;
  definitions_version?: string;
  definitions_provisional?: boolean;
  status: RunStatus;
  n_rows?: number;
  n_suppressed?: number;
  reviewed_at?: string | null;
  review_note?: string;
  n_events?: number;
  heat_cells?: number;
}

export function runIdOf(run: KpiRunSummary): string {
  return run.id ?? run.run_id ?? "";
}

/** One entry of `backend/kpi_definitions/sip_section_11.json` (served by `GET /api/kpi/definitions`). */
export interface KpiDefinition {
  key: string;
  label_en: string;
  label_local: string;
  definition: string;
  unit: string;
  person_level: boolean;
  gender_disaggregated: boolean;
  provisional: boolean;
  spec?: Record<string, unknown>;
}

export interface KpiDefinitionsFile {
  version: string;
  status?: string;
  warning?: string;
  replace_instructions?: string;
  kpis: KpiDefinition[];
}

/** Properties of one aggregated heat-map cell (`HeatCell`); k-anonymous by construction. */
export interface HeatCellProps {
  cell_lat: number;
  cell_lng: number;
  cell_size_deg?: number;
  n_visits: number;
  n_devices?: number;
  /** Older name of `n_devices`; accepted so an in-flight backend still renders. */
  n_sessions?: number;
  municipality?: string | null;
}

export type HeatFeature = Feature<Polygon | Point, HeatCellProps>;
export type HeatmapCollection = FeatureCollection<Polygon | Point, HeatCellProps>;

export function heatDevices(p: HeatCellProps): number | null {
  return p.n_devices ?? p.n_sessions ?? null;
}

/** `GET /api/kpi/quality` — internal quality metrics, not a KPI of the programme. */
export interface QualityMetrics {
  stt_wer?: {
    mean_wer?: number | null;
    median_wer?: number | null;
    n_samples?: number;
    provider?: string;
    model?: string;
    evaluated_at?: string | null;
    /** true while the test set is made of synthetic stand-ins (no consented recordings yet). */
    is_synthetic?: boolean;
    samples?: { sample_id?: string; wer?: number; speaker_note?: string; is_synthetic_sample?: boolean }[];
  } | null;
  cache?: {
    entries?: number;
    hits?: number;
    lookups?: number;
    misses?: number;
    hit_rate?: number | null;
    exact_hits?: number;
    semantic_hits?: number;
    invalidated?: number;
  } | null;
  budget?: {
    month?: string;
    cap_eur?: number;
    spent_eur?: number;
    remaining_eur?: number;
    cap_reached?: boolean;
    provider?: string;
    provider_name?: string;
    billable?: boolean;
  } | null;
}

/* ---------- onboarding timing ---------- */

/** One row of `GET /api/onboarding/timing-log`. Active and elapsed time are **separate**. */
export interface TimingRow {
  session_id: string;
  started_at: string;
  /** Active authoring time (heartbeats). The 30-minute target applies to this value only. */
  active_seconds: number;
  elapsed_to_confirm_seconds: number | null;
  elapsed_to_publish_seconds: number | null;
  within_active_target: boolean | null;
  offline_captured: boolean;
  stt_provider: string;
  llm_provider: string;
  status: string;
}
