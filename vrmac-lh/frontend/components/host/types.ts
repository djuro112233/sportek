/**
 * API shapes used by the host app. Coded strictly against docs/api-contract.md
 * (sections onboarding, listings, requests) and backend/app/schemas.py (ListingOut);
 * the backend is built concurrently, so optional members are kept tolerant.
 */

export type ContentStatus = "draft" | "reviewed" | "approved" | "rejected";

export type Category = "accommodation" | "food" | "guiding" | "craft" | "experience" | "transport" | "other";
export const CATEGORIES: Category[] = ["accommodation", "food", "guiding", "craft", "experience", "transport", "other"];

/** Draft / listing fields as listed in the contract ("Draft fields") + coords_approximate (ListingOut). */
export interface ListingFields {
  title_local: string;
  title_en: string;
  description_local: string;
  description_en: string;
  category: string;
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
}

export const LISTING_FIELD_KEYS: (keyof ListingFields)[] = [
  "title_local",
  "title_en",
  "description_local",
  "description_en",
  "category",
  "price_min",
  "price_max",
  "currency",
  "season",
  "capacity",
  "accessibility_local",
  "accessibility_en",
  "lat",
  "lng",
  "coords_approximate",
];

/** Mirrors backend app/schemas.py ListingOut. */
export interface Listing extends ListingFields {
  id: string;
  slug: string;
  photo_url: string;
  is_sample: boolean;
  missing_fields: string[];
  extraction_method: string; // llm | rules | manual
  translation_pending: boolean;
  status: ContentStatus;
  version: number;
  approved_at: string | null;
  published_at: string | null;
  updated_at: string;
}

export type OnboardingStatus = "started" | "transcribed" | "drafted" | "confirmed" | "published" | "abandoned";

/** GET /api/onboarding/sessions/{id} — session state + timings (backend OnboardingSession model). */
export interface OnboardingSession {
  id: string;
  host_user_id?: string;
  ambassador_user_id?: string | null;
  language: string;
  status: OnboardingStatus | string;
  started_at: string;
  transcript_ready_at?: string | null;
  draft_generated_at?: string | null;
  confirmed_at?: string | null;
  published_at?: string | null;
  duration_seconds?: number | null;
  audio_duration_s?: number | null;
  stt_provider?: string;
  stt_model?: string;
  llm_provider?: string;
  transcript?: string;
  draft?: Record<string, unknown>;
  listing_id?: string | null;
}

export interface SttInfo {
  provider?: string;
  model?: string;
  language?: string;
}

/** POST /api/onboarding/sessions/{id}/audio → {status, transcript?, stt}; a `job_id` means "poll the session". */
export interface AudioResponse {
  status: string;
  transcript?: string | null;
  stt?: SttInfo | string | null;
  job_id?: string | null;
}

export type DraftFieldValues = Partial<Record<keyof ListingFields, unknown>>;

/** POST /api/onboarding/sessions/{id}/draft → {draft, missing_fields, extraction_method, translation_pending}. */
export interface DraftResponse {
  draft: (DraftFieldValues & { fields?: DraftFieldValues; missing_fields?: string[] }) | null;
  missing_fields?: string[];
  extraction_method?: string;
  translation_pending?: boolean;
  llm?: SttInfo | string | null;
}

export interface ConsentPayload {
  given: true;
  method: "checkbox";
  text_version: "v1";
}

export interface ConfirmPayload {
  listing: ListingFields;
  consent: ConsentPayload;
}

/** POST /api/onboarding/sessions/{id}/confirm response. */
export interface ConfirmResponse {
  listing: Listing;
  consent_record_id: string;
  duration_seconds: number;
  target_minutes: number;
  within_target: boolean;
}

export type RequestStatus = "sent" | "confirmed" | "declined";

/** GET /api/requests/host rows (backend VisitorRequest); listing title members are optional extras. */
export interface HostRequest {
  id: string;
  listing_id: string;
  message: string;
  requested_date: string | null;
  party_size: number | null;
  status: RequestStatus;
  host_reply?: string;
  reply?: string;
  created_at: string;
  responded_at?: string | null;
  listing_title_local?: string;
  listing_title_en?: string;
  listing?: { id?: string; title_local?: string; title_en?: string } | null;
}

export interface RespondPayload {
  status: "confirmed" | "declined";
  reply: string;
}

/** String-valued form model bound to inputs; converted to ListingFields on submit. */
export interface ListingFormValues {
  title_local: string;
  title_en: string;
  description_local: string;
  description_en: string;
  category: string;
  price_min: string;
  price_max: string;
  currency: string;
  season: string;
  capacity: string;
  accessibility_local: string;
  accessibility_en: string;
  lat: string;
  lng: string;
  coords_approximate: boolean;
}
