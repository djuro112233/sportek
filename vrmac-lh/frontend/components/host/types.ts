/**
 * API shapes used by the host app.
 *
 * Coded strictly against docs/api-contract.md (sections auth, villages, onboarding, listings,
 * requests) and backend/app/schemas.py (`ListingOut`, `VillageOut`, `UserOut`) /
 * backend/app/models.py (`Listing`, `OnboardingSession`, `VisitorRequest`).
 * The backend is written concurrently, so optional members stay tolerant.
 */
import type { User } from "@/lib/api";

export type ContentStatus = "draft" | "reviewed" | "approved" | "rejected";

export type Category = "accommodation" | "food" | "guiding" | "craft" | "experience" | "transport" | "other";
export const CATEGORIES: Category[] = ["accommodation", "food", "guiding", "craft", "experience", "transport", "other"];

/** Voluntary self-report (POST /api/auth/me/gender). "undisclosed" is never offered as a choice. */
export type GenderChoice = "female" | "male" | "other" | "prefer_not_to_say";
export const GENDER_CHOICES: GenderChoice[] = ["female", "male", "other", "prefer_not_to_say"];

/**
 * `UserOut` carries `gender` / `gender_self_reported`; the shared `User` type in lib/api.ts still
 * declares the older `sex` member, so the host app reads the current fields through this view.
 */
export type HostUser = User & {
  gender?: GenderChoice | "undisclosed";
  gender_self_reported?: boolean;
  village_id?: string | null;
};

/** GET /api/villages → VillageOut[] (+ n_approved_items). */
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
}

/**
 * The structured groups the host must fill in and confirm. The assistant never fills any of them —
 * it only drafts `title_*` and `description_*`. The names match the backend vocabulary used by
 * `missing_fields` / `fields_required` (services/extraction.py REQUIRED_FIELDS).
 */
export type StructuredField = "category" | "price_range" | "season" | "capacity" | "accessibility" | "coordinates";
export const STRUCTURED_FIELDS: StructuredField[] = [
  "category",
  "price_range",
  "season",
  "capacity",
  "accessibility",
  "coordinates",
];

/** The model-drafted fields — title and description only, in both languages. */
export type NarrativeField = "title_local" | "title_en" | "description_local" | "description_en";

/** Listing payload (mirrors the writable half of `ListingOut`). */
export interface ListingFields {
  title_local: string;
  title_en: string;
  description_local: string;
  description_en: string;
  category: string;
  // --- host-entered and host-confirmed, never inferred ---
  price_min: number | null;
  price_max: number | null;
  currency: string;
  price_note_local: string;
  price_note_en: string;
  season_from: number | null; // month 1-12
  season_to: number | null;
  season_all_year: boolean;
  capacity: number | null;
  accessibility_step_free: boolean | null;
  accessibility_note_local: string;
  accessibility_note_en: string;
  lat: number | null;
  lng: number | null;
  coords_approximate: boolean;
  confirmed_fields: string[];
}

/** What the client sends; `village_id` is dropped automatically if the API rejects it as extra. */
export interface ListingPayload extends ListingFields {
  village_id?: string;
}

/** Mirrors backend app/schemas.py `ListingOut`. */
export interface Listing extends ListingFields {
  id: string;
  slug: string;
  village_id: string;
  photo_url: string;
  is_sample: boolean;
  missing_fields: string[];
  extraction_method: string; // llm | rules | manual
  translation_pending: boolean;
  status: ContentStatus | string;
  version: number;
  approved_at: string | null;
  published_at: string | null;
  updated_at: string;
}

export type OnboardingStatus =
  | "started"
  | "captured_offline"
  | "transcribed"
  | "drafted"
  | "confirmed"
  | "published"
  | "abandoned";

/** POST/GET /api/onboarding/sessions[/{id}] — session state and the two separate durations. */
export interface OnboardingSession {
  id: string;
  host_user_id?: string;
  ambassador_user_id?: string | null;
  village_id?: string | null;
  language: string;
  status: OnboardingStatus | string;
  started_at: string;
  captured_at?: string | null;
  transcript_ready_at?: string | null;
  draft_generated_at?: string | null;
  confirmed_at?: string | null;
  published_at?: string | null;
  /** Active authoring time accumulated from heartbeats (excludes waiting for the validator). */
  active_seconds?: number;
  elapsed_to_confirm_seconds?: number | null;
  elapsed_to_publish_seconds?: number | null;
  offline_captured?: boolean;
  upload_deferred_seconds?: number | null;
  audio_duration_s?: number | null;
  stt_provider?: string;
  stt_model?: string;
  llm_provider?: string;
  transcript?: string;
  draft?: Record<string, unknown>;
  listing_id?: string | null;
}

export interface HeartbeatResponse {
  active_seconds: number;
}

export interface SttInfo {
  provider?: string;
  model?: string;
  language?: string;
}

/**
 * POST /api/onboarding/sessions/{id}/audio → `{status, transcript?, stt}`.
 * A `job_id` (queued transcription) means: poll GET /api/onboarding/sessions/{id}.
 */
export interface AudioResponse {
  status?: string;
  transcript?: string | null;
  stt?: SttInfo | string | null;
  job_id?: string | null;
  audio_duration_s?: number | null;
}

export type NarrativeDraft = Partial<Record<NarrativeField, unknown>>;

/**
 * POST /api/onboarding/sessions/{id}/draft →
 * `{draft: {title_local, title_en, description_local, description_en}, extraction_method,
 *   translation_pending, fields_required[]}`.
 * `draft.fields` is tolerated because services/extraction.py nests its output that way.
 */
export interface DraftResponse {
  draft: (NarrativeDraft & { fields?: NarrativeDraft }) | null;
  extraction_method?: string;
  translation_pending?: boolean;
  fields_required?: string[];
  missing_fields?: string[];
  llm?: SttInfo | string | null;
}

export interface ConsentPayload {
  given: true;
  method: "checkbox";
  text_version: "v1";
}

export interface ConfirmPayload {
  listing: ListingPayload;
  consent: ConsentPayload;
}

/** POST /api/onboarding/sessions/{id}/confirm response. */
export interface ConfirmResponse {
  listing: Listing;
  consent_record_id: string;
  /** Active authoring time — the value the ≤ 30 min target refers to. */
  active_seconds: number;
  /** Wall-clock time, which includes any waiting; never compared against the target. */
  elapsed_to_confirm_seconds: number;
  target_minutes: number;
  within_active_target: boolean;
}

export type RequestStatus = "sent" | "confirmed" | "completed" | "cancelled" | "refused" | "expired";
export const OPEN_REQUEST_STATUSES: RequestStatus[] = ["sent", "confirmed"];

/** GET /api/requests/host rows (backend `VisitorRequest`); listing titles are optional extras. */
export interface HostRequest {
  id: string;
  listing_id: string;
  message: string;
  requested_date: string | null;
  party_size: number | null;
  status: RequestStatus | string;
  host_reply?: string;
  created_at: string;
  responded_at?: string | null;
  closed_at?: string | null;
  expires_at?: string | null;
  listing_title_local?: string;
  listing_title_en?: string;
  listing?: { id?: string; title_local?: string; title_en?: string } | null;
}

export interface RespondPayload {
  status: "confirmed" | "refused";
  reply: string;
}

export interface ClosePayload {
  status: "completed" | "cancelled";
  note: string;
}

/** String-valued form model bound to the inputs; converted to `ListingFields` on submit. */
export interface ListingFormValues {
  title_local: string;
  title_en: string;
  description_local: string;
  description_en: string;
  category: string;
  price_min: string;
  price_max: string;
  currency: string;
  price_note_local: string;
  price_note_en: string;
  season_all_year: boolean;
  season_from: string;
  season_to: string;
  capacity: string;
  /** "" = not answered yet, "yes" / "no" = the host's own answer. */
  accessibility_step_free: "" | "yes" | "no";
  accessibility_note_local: string;
  accessibility_note_en: string;
  lat: string;
  lng: string;
  coords_approximate: boolean;
  village_id: string;
}

export type Confirmations = Record<StructuredField, boolean>;

/** One recording held in IndexedDB until it can be uploaded (offline capture). */
export type QueuedState = "queued" | "uploading" | "uploaded" | "failed";

export interface QueuedRecording {
  id: string;
  session_id: string;
  language: string;
  /** ISO timestamp of when the host recorded it — sent as `captured_at`. */
  captured_at: string;
  duration_s: number;
  mime: string;
  size: number;
  blob: Blob;
  state: QueuedState;
  attempts: number;
  /** True when the browser was offline at capture time or the first upload attempt failed. */
  captured_offline: boolean;
  last_error?: string;
  uploaded_at?: string;
  transcript?: string;
  job_id?: string | null;
}

/** What the wizard needs to hear when a queued recording finally reaches the API. */
export interface UploadResult {
  record: QueuedRecording;
  response: AudioResponse;
}
