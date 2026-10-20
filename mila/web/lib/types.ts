/**
 * Shared API types. These mirror `backend/app/core/types.py` (the module contract).
 * Keep field names snake_case to match the wire format exactly.
 */

export type Lang = 'sr' | 'bs' | 'hr' | 'me' | 'en';
export type Script = 'latin' | 'cyrillic';
export type Outcome = 'answered' | 'withheld' | 'redflag';
export type ReviewStatus = 'reviewed' | 'public_unreviewed' | 'blocked';
export type InputMode = 'text' | 'voice';
export type Region = 'BA' | 'ME';

export const SUPPORTED_LANGS: readonly Lang[] = ['sr', 'bs', 'hr', 'me', 'en'];
export const SUPPORTED_SCRIPTS: readonly Script[] = ['latin', 'cyrillic'];
export const SUPPORTED_REGIONS: readonly Region[] = ['BA', 'ME'];

export interface Locale {
  lang: Lang;
  script: Script;
}

export interface Citation {
  marker: string; // "S1"
  chunk_id: string;
  source_id: string;
  source_title: string;
  section: string;
  version: string;
  date: string;
  page: number | null;
  review_status: ReviewStatus | string;
  lang: string;
}

export interface AnswerSentence {
  text: string;
  citations: string[]; // markers, e.g. ["S1"]
  supported: boolean;
  support_score: number;
  flagged_medication?: boolean;
  reason?: string;
}

/** The validation gate's decision as the API exposes it (`public_gate`: removed text is blank). */
export interface GateDecision {
  status: 'approved' | 'withheld';
  gate_version?: string;
  reasons: string[]; // e.g. low_support_ratio, medication_or_dose, pipeline_error
  support_ratio: number;
  confidence: number;
  relevance: number | null;
  kept: AnswerSentence[];
  removed: AnswerSentence[];
}

/** Gate reason set by the backend when a pipeline stage failed (infrastructure, not a knowledge gap). */
export const GATE_REASON_PIPELINE_ERROR = 'pipeline_error';

export function isPipelineError(response: Pick<AskResponse, 'gate'>): boolean {
  const reasons = response.gate?.reasons;
  return Array.isArray(reasons) && reasons.includes(GATE_REASON_PIPELINE_ERROR);
}

/**
 * A referral point as the API returns it. There is no `notes` field on the wire any more and
 * the UI must never show internal notes; `verified_on` is '' until the clinic verified the entry.
 */
export interface ReferralPoint {
  name: string;
  kind: string; // clinic | er | helpline | child_protection | violence | mental_health
  region?: string;
  city?: string;
  phone?: string;
  address?: string;
  url?: string;
  hours?: string;
  emergency?: boolean;
  verified_on?: string; // ISO date, '' = not yet verified
}

export interface Referral {
  emergency: boolean;
  message: string;
  points: ReferralPoint[];
}

export interface AskRequest {
  session_id: string;
  text: string;
  lang: Lang;
  script: Script;
  region: Region;
  input_mode: InputMode;
  want_audio: boolean;
  low_bandwidth: boolean;
}

export interface AskResponse {
  outcome: Outcome;
  session_id: string;
  lang: string;
  script?: string;
  topic_class?: string;
  sentences: AnswerSentence[];
  citations: Citation[];
  confidence: number;
  support_ratio?: number;
  message: string;
  referral: Referral | null;
  disclaimer_short: string;
  translated: boolean;
  demo_unreviewed_sources: boolean;
  redflag_category: string | null;
  gate: GateDecision | null;
  /** One localised line for minors ("you can also talk to a trusted adult"); '' otherwise. */
  minor_note: string;
  audio_url: string | null;
  latency_ms: number;
}

export interface Transcript {
  text: string;
  lang: string;
  confidence: number;
  duration_s?: number;
  confirm_required?: boolean;
}

export type ConsentItem = string | { id?: string; text?: string; label?: string };

export interface ConsentText {
  version: string;
  text: string;
  spoken_text: string;
  items: ConsentItem[];
}

export interface ConsentRequest {
  lang: Lang;
  script: Script;
  region: Region;
  is_minor: boolean;
  accepted: true;
  save_questions: boolean;
  consent_version: string;
}

export interface ConsentResponse {
  session_id: string;
  consent_version: string;
  lang?: string;
  script?: string;
  region?: string;
  is_minor?: boolean;
  save_questions?: boolean;
}

export interface SessionPreferences {
  lang?: Lang;
  script?: Script;
  region?: Region;
  low_bandwidth?: boolean;
}

/** `GET /api/session/{id}`: `exists: false` (everything else null) for an unknown id, never a 403. */
export interface SessionInfo {
  exists: boolean;
  consent_given: boolean | null;
  consent_version: string | null;
  lang: string | null;
  script: string | null;
  region: string | null;
  is_minor: boolean | null;
  save_questions: boolean | null;
}

export interface SpeakRequest {
  text: string;
  lang: Lang;
  script: Script;
  low_bandwidth: boolean;
}

/**
 * What the client keeps in sessionStorage (one tab, gone when the browser closes): the
 * pseudonymous id and the settings fixed at consent. Nothing identifying ever lands in
 * localStorage; see lib/storage.ts.
 */
export interface StoredSession {
  session_id: string;
  lang: Lang;
  script: Script;
  region: Region;
  is_minor: boolean;
}

export function isLang(v: unknown): v is Lang {
  return typeof v === 'string' && (SUPPORTED_LANGS as readonly string[]).includes(v);
}

export function isScript(v: unknown): v is Script {
  return typeof v === 'string' && (SUPPORTED_SCRIPTS as readonly string[]).includes(v);
}

export function isRegion(v: unknown): v is Region {
  return typeof v === 'string' && (SUPPORTED_REGIONS as readonly string[]).includes(v);
}
