/**
 * Typed client for the MILA backend (`/api`, see docs/architecture.md).
 * Every request has an AbortController timeout so a 2G connection never leaves the UI hanging.
 *
 * By default the client calls the same origin (`/api/...`); `app/api/[...path]/route.ts`
 * forwards those requests to the API at runtime (`MILA_API_URL`). `NEXT_PUBLIC_API_BASE` is an
 * optional build-time override for static deployments that talk to the API directly.
 */

import type { MsgKey } from './i18n';
import type {
  AskRequest,
  AskResponse,
  ConsentRequest,
  ConsentResponse,
  ConsentText,
  Lang,
  Locale,
  SessionInfo,
  SessionPreferences,
  SpeakRequest,
  Transcript,
} from './types';

const rawBase = process.env.NEXT_PUBLIC_API_BASE;
/** Base URL without a trailing slash. Empty string (the default) means "same origin". */
export const API_BASE: string = (rawBase ?? '').trim().replace(/\/+$/, '');

export const TIMEOUTS = {
  short: 12_000,
  ask: 60_000,
  transcribe: 45_000,
  speak: 30_000,
} as const;

export type ApiErrorKind = 'timeout' | 'network' | 'http' | 'parse' | 'aborted';

/** Fallback wait when a 429 arrives without a usable Retry-After (the server's window is a minute). */
export const DEFAULT_RETRY_AFTER_S = 60;

export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  readonly status: number;
  readonly detail: string;
  /** Seconds from the Retry-After header of a 429 (or 503); null when absent or unparseable. */
  readonly retryAfter: number | null;

  constructor(kind: ApiErrorKind, message: string, status = 0, detail = '', retryAfter: number | null = null) {
    super(message);
    this.name = 'ApiError';
    this.kind = kind;
    this.status = status;
    this.detail = detail;
    this.retryAfter = retryAfter;
  }
}

export function isApiError(err: unknown): err is ApiError {
  return err instanceof ApiError;
}

/**
 * Retry-After is either delta-seconds or an HTTP date. Returns whole seconds (at least 0),
 * or null when the header is missing or unparseable.
 */
export function parseRetryAfter(value: string | null | undefined, now: number = Date.now()): number | null {
  if (value === null || value === undefined) return null;
  const text = value.trim();
  if (text === '') return null;
  if (/^\d+$/.test(text)) return Number(text);
  const at = Date.parse(text);
  if (Number.isNaN(at)) return null;
  return Math.max(0, Math.ceil((at - now) / 1000));
}

/** Seconds the UI should wait before offering a retry after a 429, or null for other errors. */
export function retryAfterSeconds(err: unknown): number | null {
  if (!isApiError(err) || err.kind !== 'http' || err.status !== 429) return null;
  return err.retryAfter ?? DEFAULT_RETRY_AFTER_S;
}

/**
 * True when the server no longer accepts the stored session: 403 for an unknown session, a
 * session without consent, or a consent given under an older consent version
 * (`consent_version_outdated`). The client must forget the session and ask for consent again.
 */
export function isSessionGone(err: unknown): boolean {
  return isApiError(err) && err.kind === 'http' && err.status === 403;
}

/** 409 `consent_version_outdated` from POST /api/consent: the text changed while it was on screen. */
export function isConsentVersionOutdated(err: unknown): boolean {
  return isApiError(err) && err.kind === 'http' && err.status === 409 && err.detail === 'consent_version_outdated';
}

/** Map any failure to a user-facing message key. */
export function errorMessageKey(err: unknown): MsgKey {
  if (isApiError(err)) {
    if (err.kind === 'timeout') return 'error_timeout';
    if (err.kind === 'network' || err.kind === 'aborted') return 'error_network';
    if (err.kind === 'http' && err.status === 429) return 'error_rate_limited';
    // The backend answers 403 for an unknown, unconsented or outdated-consent session. A 404 may
    // only be a missing route, so it is reported as a server error instead of ending the session.
    if (isSessionGone(err)) return 'session_expired';
    return 'error_server';
  }
  return 'error_server';
}

/** Absolute URLs pass through; everything else is joined to API_BASE ('' = same origin). */
export function apiUrl(path: string): string {
  if (/^https?:\/\//i.test(path)) return path;
  const clean = path.startsWith('/') ? path : `/${path}`;
  return `${API_BASE}${clean}`;
}

/** `audio_url` may be absolute or relative to the API; make it fetchable from the page. */
export function resolveAudioUrl(url: string): string {
  if (/^(https?:)?\/\//i.test(url) || url.startsWith('blob:') || url.startsWith('data:')) return url;
  return apiUrl(url);
}

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'DELETE';
  json?: unknown;
  body?: BodyInit;
  timeoutMs?: number;
  signal?: AbortSignal;
  accept?: string;
}

async function rawRequest(path: string, opts: RequestOptions = {}): Promise<Response> {
  const controller = new AbortController();
  const timeoutMs = opts.timeoutMs ?? TIMEOUTS.short;
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);

  const external = opts.signal;
  const onExternalAbort = () => controller.abort();
  if (external) {
    if (external.aborted) controller.abort();
    else external.addEventListener('abort', onExternalAbort, { once: true });
  }

  const headers: Record<string, string> = { Accept: opts.accept ?? 'application/json' };
  let body: BodyInit | undefined = opts.body;
  if (opts.json !== undefined) {
    headers['Content-Type'] = 'application/json';
    body = JSON.stringify(opts.json);
  }

  try {
    return await fetch(apiUrl(path), {
      method: opts.method ?? 'GET',
      headers,
      body,
      signal: controller.signal,
      cache: 'no-store',
      credentials: 'omit',
    });
  } catch (err) {
    if (timedOut) throw new ApiError('timeout', `timeout after ${timeoutMs}ms`);
    if (external?.aborted) throw new ApiError('aborted', 'request aborted');
    const msg = err instanceof Error ? err.message : 'network error';
    throw new ApiError('network', msg);
  } finally {
    clearTimeout(timer);
    external?.removeEventListener('abort', onExternalAbort);
  }
}

async function readErrorDetail(res: Response): Promise<string> {
  try {
    const text = await res.text();
    try {
      const parsed: unknown = JSON.parse(text);
      if (typeof parsed === 'object' && parsed !== null && 'detail' in parsed) {
        const d = (parsed as { detail: unknown }).detail;
        return typeof d === 'string' ? d : JSON.stringify(d);
      }
    } catch {
      // not JSON
    }
    return text.slice(0, 200);
  } catch {
    return '';
  }
}

async function httpError(res: Response): Promise<ApiError> {
  const detail = await readErrorDetail(res);
  let retryAfter: number | null = null;
  try {
    retryAfter = parseRetryAfter(res.headers.get('Retry-After'));
  } catch {
    // headers unavailable on exotic Response objects
  }
  return new ApiError('http', `HTTP ${res.status}`, res.status, detail, retryAfter);
}

/** Low-level JSON request; exported for tests and for endpoints added later. */
export async function requestJson<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const res = await rawRequest(path, opts);
  if (!res.ok) throw await httpError(res);
  try {
    return (await res.json()) as T;
  } catch {
    throw new ApiError('parse', 'invalid JSON from server', res.status);
  }
}

async function requestBlob(path: string, opts: RequestOptions = {}): Promise<Blob> {
  const res = await rawRequest(path, opts);
  if (!res.ok) throw await httpError(res);
  try {
    return await res.blob();
  } catch {
    throw new ApiError('parse', 'could not read audio', res.status);
  }
}

// --- endpoints -------------------------------------------------------------------------------

export function getHealth(signal?: AbortSignal): Promise<{ status: string; demo_mode: boolean; version: string }> {
  return requestJson('/api/health', { signal });
}

export function getConsentText(locale: Locale, isMinor: boolean, signal?: AbortSignal): Promise<ConsentText> {
  const q = new URLSearchParams({
    lang: locale.lang,
    script: locale.script,
    is_minor: isMinor ? 'true' : 'false',
  });
  return requestJson(`/api/consent/text?${q.toString()}`, { signal });
}

export function postConsent(body: ConsentRequest, signal?: AbortSignal): Promise<ConsentResponse> {
  return requestJson('/api/consent', { method: 'POST', json: body, signal });
}

export function getSession(sessionId: string, signal?: AbortSignal): Promise<SessionInfo> {
  return requestJson(`/api/session/${encodeURIComponent(sessionId)}`, { signal });
}

export function postPreferences(sessionId: string, prefs: SessionPreferences, signal?: AbortSignal): Promise<unknown> {
  return requestJson(`/api/session/${encodeURIComponent(sessionId)}/preferences`, {
    method: 'POST',
    json: prefs,
    signal,
  });
}

export function deleteSession(sessionId: string, signal?: AbortSignal): Promise<{ deleted?: Record<string, number> }> {
  return requestJson(`/api/session/${encodeURIComponent(sessionId)}`, { method: 'DELETE', signal });
}

export function transcribe(
  audio: Blob,
  fileName: string,
  sessionId: string,
  lang: Lang,
  signal?: AbortSignal,
): Promise<Transcript> {
  const form = new FormData();
  form.append('file', audio, fileName);
  form.append('session_id', sessionId);
  form.append('lang', lang);
  return requestJson('/api/transcribe', { method: 'POST', body: form, timeoutMs: TIMEOUTS.transcribe, signal });
}

export function speak(req: SpeakRequest, signal?: AbortSignal): Promise<Blob> {
  return requestBlob('/api/speak', {
    method: 'POST',
    json: req,
    timeoutMs: TIMEOUTS.speak,
    accept: 'audio/wav',
    signal,
  });
}

export function ask(req: AskRequest, signal?: AbortSignal): Promise<AskResponse> {
  return requestJson('/api/ask', { method: 'POST', json: req, timeoutMs: TIMEOUTS.ask, signal });
}

/**
 * Fetch the one-time answer audio (`AskResponse.audio_url`, served once by `GET /api/audio/{token}`)
 * into a Blob. The caller keeps the Blob and replays it; the token must never be requested twice.
 */
export function getAudio(url: string, signal?: AbortSignal): Promise<Blob> {
  return requestBlob(resolveAudioUrl(url), { timeoutMs: TIMEOUTS.speak, accept: 'audio/wav', signal });
}
