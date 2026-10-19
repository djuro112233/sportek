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
  verified_on?: string;
  notes?: string;
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
  consent_version?: string;
}

export interface SessionPreferences {
  lang?: Lang;
  script?: Script;
  region?: Region;
  low_bandwidth?: boolean;
}

export interface SessionInfo {
  session_id?: string;
  id?: string;
  lang?: string;
  script?: string;
  region?: string;
  is_minor?: boolean | null;
  consent_given?: boolean;
}

export interface SpeakRequest {
  text: string;
  lang: Lang;
  script: Script;
  low_bandwidth: boolean;
}

/** What the client keeps in localStorage: the pseudonymous id and display preferences only. */
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
