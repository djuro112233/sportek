/**
 * Safe web-storage wrappers. Everything is wrapped in try/catch because storage can be
 * missing (old WebViews), blocked (private mode) or full. The client stores only:
 *   - in sessionStorage (one tab, cleared when the browser closes): the pseudonymous session id
 *     plus the lang / script / region / is_minor fixed at consent (needed for requests). A shared
 *     clinic phone therefore never resumes a previous person's session without a new consent.
 *   - in localStorage: non-identifying display preferences only (language, script, low-data mode).
 * Never question text, transcripts or answers, and never the session id in localStorage.
 */

import type { Lang, Locale, Region, Script, StoredSession } from './types';
// Explicit extension so the file also loads under Node's native TypeScript runner (tests).
import { isLang, isRegion, isScript } from './types.ts';

export const SESSION_KEY = 'mila.session.v1';
export const PREFS_KEY = 'mila.prefs.v1';

export type StorageArea = 'session' | 'local';

export interface Prefs {
  low_bandwidth: boolean;
  lang: Lang | null;
  script: Script | null;
}

const DEFAULT_PREFS: Prefs = { low_bandwidth: false, lang: null, script: null };

function storage(area: StorageArea): Storage | null {
  try {
    const g = globalThis as { localStorage?: Storage; sessionStorage?: Storage };
    const candidate = area === 'session' ? g.sessionStorage : g.localStorage;
    if (!candidate || typeof candidate.getItem !== 'function') return null;
    return candidate;
  } catch {
    return null;
  }
}

export function readRaw(key: string, area: StorageArea = 'local'): string | null {
  try {
    const s = storage(area);
    return s ? s.getItem(key) : null;
  } catch {
    return null;
  }
}

export function writeRaw(key: string, value: string, area: StorageArea = 'local'): boolean {
  try {
    const s = storage(area);
    if (!s) return false;
    s.setItem(key, value);
    return true;
  } catch {
    return false;
  }
}

export function removeRaw(key: string, area: StorageArea = 'local'): void {
  try {
    storage(area)?.removeItem(key);
  } catch {
    // ignore: nothing to remove or storage blocked
  }
}

export function readJson<T>(key: string, validate: (value: unknown) => value is T, area: StorageArea = 'local'): T | null {
  const raw = readRaw(key, area);
  if (raw === null) return null;
  try {
    const parsed: unknown = JSON.parse(raw);
    return validate(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

export function writeJson(key: string, value: unknown, area: StorageArea = 'local'): boolean {
  try {
    return writeRaw(key, JSON.stringify(value), area);
  } catch {
    return false;
  }
}

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

export function isStoredSession(v: unknown): v is StoredSession {
  if (!isRecord(v)) return false;
  return (
    typeof v.session_id === 'string' &&
    v.session_id.length > 0 &&
    isLang(v.lang) &&
    isScript(v.script) &&
    isRegion(v.region) &&
    typeof v.is_minor === 'boolean'
  );
}

export function isPrefs(v: unknown): v is Prefs {
  if (!isRecord(v)) return false;
  const langOk = v.lang === null || isLang(v.lang);
  const scriptOk = v.script === null || isScript(v.script);
  return typeof v.low_bandwidth === 'boolean' && langOk && scriptOk;
}

/** The session of this tab, if any. Older builds kept it in localStorage; that copy is dropped. */
export function loadSession(): StoredSession | null {
  removeRaw(SESSION_KEY, 'local');
  return readJson(SESSION_KEY, isStoredSession, 'session');
}

export function saveSession(session: StoredSession): boolean {
  // Explicit field list: nothing else ever lands in storage.
  const minimal: StoredSession = {
    session_id: session.session_id,
    lang: session.lang,
    script: session.script,
    region: session.region,
    is_minor: session.is_minor,
  };
  return writeJson(SESSION_KEY, minimal, 'session');
}

/** Forget the session (expired, deleted, or refused by the server) but keep display preferences. */
export function clearSession(): void {
  removeRaw(SESSION_KEY, 'session');
  removeRaw(SESSION_KEY, 'local');
}

export function loadPrefs(): Prefs {
  return readJson(PREFS_KEY, isPrefs, 'local') ?? { ...DEFAULT_PREFS };
}

export function savePrefs(prefs: Partial<Prefs>): Prefs {
  // Explicit field list, as for the session: only these three preferences are persisted.
  const current = loadPrefs();
  const merged: Prefs = {
    low_bandwidth: prefs.low_bandwidth ?? current.low_bandwidth,
    lang: prefs.lang === undefined ? current.lang : prefs.lang,
    script: prefs.script === undefined ? current.script : prefs.script,
  };
  writeJson(PREFS_KEY, merged, 'local');
  return merged;
}

export function prefsLocale(prefs: Prefs): Locale | null {
  if (prefs.lang && prefs.script) return { lang: prefs.lang, script: prefs.script };
  return null;
}

export function regionOrDefault(value: unknown, fallback: Region = 'BA'): Region {
  return isRegion(value) ? value : fallback;
}

/** Remove everything MILA ever wrote to this browser ("Delete my data"). */
export function clearAll(): void {
  clearSession();
  removeRaw(PREFS_KEY, 'local');
  removeRaw(PREFS_KEY, 'session');
}
