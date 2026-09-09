/**
 * Every backend call the host app makes, in one place, coded against docs/api-contract.md.
 * The backend is written concurrently: nothing here assumes more than the contract states.
 */
import { api, ApiError } from "@/lib/api";
import type {
  AudioResponse,
  ClosePayload,
  ConfirmPayload,
  ConfirmResponse,
  ConsentPayload,
  DraftResponse,
  GenderChoice,
  HeartbeatResponse,
  HostRequest,
  HostUser,
  Listing,
  ListingPayload,
  OnboardingSession,
  RespondPayload,
  Village,
} from "./types";

// ---------------------------------------------------------------------------------------------
// villages, auth
// ---------------------------------------------------------------------------------------------

export function getVillages(): Promise<Village[]> {
  return api<Village[]>("/api/villages", { auth: false });
}

/** Voluntary self-report; the endpoint always writes to the token's own subject. */
export function reportGender(gender: GenderChoice): Promise<HostUser> {
  return api<HostUser>("/api/auth/me/gender", { method: "POST", body: { gender } });
}

// ---------------------------------------------------------------------------------------------
// onboarding
// ---------------------------------------------------------------------------------------------

export interface StartSessionInput {
  language: string;
  village?: string;
  host_user_id?: string;
}

export function createSession(input: StartSessionInput): Promise<OnboardingSession> {
  const body: Record<string, string> = { language: input.language };
  if (input.village) body.village = input.village;
  if (input.host_user_id) body.host_user_id = input.host_user_id;
  return api<OnboardingSession>("/api/onboarding/sessions", { method: "POST", body });
}

export function getSession(id: string): Promise<OnboardingSession> {
  return api<OnboardingSession>(`/api/onboarding/sessions/${id}`);
}

/** Accumulates **active authoring time** only; waiting for the validator is never sent here. */
export function heartbeat(id: string, activeSecondsDelta: number): Promise<HeartbeatResponse> {
  return api<HeartbeatResponse>(`/api/onboarding/sessions/${id}/heartbeat`, {
    method: "POST",
    body: { active_seconds_delta: Math.round(activeSecondsDelta) },
  });
}

export interface AudioUpload {
  blob: Blob;
  filename: string;
  /** ISO timestamp of the moment the host recorded it (not the moment of upload). */
  capturedAt: string;
  offlineCaptured: boolean;
  durationSeconds?: number;
}

export function uploadAudio(id: string, u: AudioUpload): Promise<AudioResponse> {
  const form = new FormData();
  form.append("file", u.blob, u.filename);
  form.append("captured_at", u.capturedAt);
  form.append("offline_captured", u.offlineCaptured ? "true" : "false");
  if (u.durationSeconds !== undefined && Number.isFinite(u.durationSeconds)) {
    form.append("audio_duration_s", String(Math.round(u.durationSeconds)));
  }
  return api<AudioResponse>(`/api/onboarding/sessions/${id}/audio`, { method: "POST", body: form });
}

export function saveTranscript(id: string, text: string): Promise<OnboardingSession> {
  return api<OnboardingSession>(`/api/onboarding/sessions/${id}/transcript`, { method: "POST", body: { text } });
}

/** The assistant drafts title and description only. */
export function generateDraft(id: string): Promise<DraftResponse> {
  return api<DraftResponse>(`/api/onboarding/sessions/${id}/draft`, { method: "POST" });
}

export const CONSENT: ConsentPayload = { given: true, method: "checkbox", text_version: "v1" };

export function confirmListing(id: string, listing: ListingPayload): Promise<ConfirmResponse> {
  return withListingFallback(listing, (l) => {
    const body: ConfirmPayload = { listing: l, consent: CONSENT };
    return api<ConfirmResponse>(`/api/onboarding/sessions/${id}/confirm`, { method: "POST", body });
  });
}

// ---------------------------------------------------------------------------------------------
// listings
// ---------------------------------------------------------------------------------------------

export function getMyListings(): Promise<Listing[]> {
  return api<Listing[]>("/api/listings/mine");
}

/** An edit creates a new version and puts the listing back to draft for re-validation. */
export function updateListing(listingId: string, listing: ListingPayload): Promise<Listing> {
  return withListingFallback(listing, (l) => api<Listing>(`/api/listings/${listingId}`, { method: "PUT", body: l }));
}

// ---------------------------------------------------------------------------------------------
// requests — messages only: no booking, no payment
// ---------------------------------------------------------------------------------------------

export function getHostRequests(): Promise<HostRequest[]> {
  return api<HostRequest[]>("/api/requests/host");
}

export function respondToRequest(requestId: string, body: RespondPayload): Promise<HostRequest> {
  return api<HostRequest>(`/api/requests/${requestId}/respond`, { method: "POST", body });
}

export function closeRequest(requestId: string, body: ClosePayload): Promise<HostRequest> {
  return api<HostRequest>(`/api/requests/${requestId}/close`, { method: "POST", body });
}

// ---------------------------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------------------------

/**
 * `village_id` is sent with the listing because a listing must belong to a village; if the API
 * rejects a member as an extra input (FastAPI 422, `extra_forbidden`), it is dropped and the call
 * is retried once — the onboarding session already carries the village that was picked in step 1.
 */
async function withListingFallback<T>(listing: ListingPayload, send: (l: ListingPayload) => Promise<T>): Promise<T> {
  try {
    return await send(listing);
  } catch (e) {
    const keys = extraForbiddenKeys(e).filter((k) => k in listing);
    if (keys.length === 0) throw e;
    const trimmed: Record<string, unknown> = { ...listing };
    for (const k of keys) delete trimmed[k];
    return await send(trimmed as unknown as ListingPayload);
  }
}

function extraForbiddenKeys(e: unknown): string[] {
  if (!(e instanceof ApiError) || e.status !== 422 || !Array.isArray(e.detail)) return [];
  const keys: string[] = [];
  for (const item of e.detail as unknown[]) {
    if (!item || typeof item !== "object") continue;
    const rec = item as { type?: unknown; msg?: unknown; loc?: unknown };
    const type = typeof rec.type === "string" ? rec.type : "";
    const msg = typeof rec.msg === "string" ? rec.msg : "";
    if (type !== "extra_forbidden" && !/extra (inputs|fields)/i.test(msg)) continue;
    if (Array.isArray(rec.loc) && rec.loc.length > 0) {
      const last = rec.loc[rec.loc.length - 1];
      if (typeof last === "string") keys.push(last);
    }
  }
  return keys;
}

/**
 * When the audio endpoint answers with a `job_id` the transcription runs in the background:
 * poll the session every 2 s until `transcript_ready_at` is set.
 */
export async function pollForTranscript(
  sessionId: string,
  opts: { intervalMs?: number; timeoutMs?: number; onTick?: (attempt: number) => void; signal?: AbortSignal } = {},
): Promise<OnboardingSession> {
  const interval = opts.intervalMs ?? 2000;
  const timeout = opts.timeoutMs ?? 5 * 60 * 1000;
  const started = Date.now();
  let attempt = 0;
  for (;;) {
    if (opts.signal?.aborted) throw new DOMException("aborted", "AbortError");
    attempt += 1;
    opts.onTick?.(attempt);
    const session = await getSession(sessionId);
    if (session.transcript_ready_at) return session;
    if (Date.now() - started > timeout) return session;
    await sleep(interval, opts.signal);
  }
}

function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const id = window.setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    const onAbort = () => {
      window.clearTimeout(id);
      reject(new DOMException("aborted", "AbortError"));
    };
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}
