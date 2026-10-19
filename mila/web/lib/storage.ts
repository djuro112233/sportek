/**
 * Safe localStorage wrappers. Everything is wrapped in try/catch because storage can be
 * missing (old WebViews), blocked (private mode) or full. The client stores only:
 *   - the pseudonymous session id plus lang / script / region / is_minor (needed for requests)
 *   - display preferences (low-bandwidth mode and the chosen language)
 * Never question text, transcripts or answers.
 */

import type { Lang, Locale, Region, Script, StoredSession } from './types';
// Explicit extension so the file also loads under Node's native TypeScript runner (tests).
import { isLang, isRegion, isScript } from './types.ts';

export const SESSION_KEY = 'mila.session.v1';
export const PREFS_KEY = 'mila.prefs.v1';

export interface Prefs {
  low_bandwidth: boolean;
  lang: Lang | null;
  script: Script | null;
}

const DEFAULT_PREFS: Prefs = { low_bandwidth: false, lang: null, script: null };

function storage(): Storage | null {
  try {
    const candidate = (globalThis as { localStorage?: Storage }).localStorage;
    if (!candidate || typeof candidate.getItem !== 'function') return null;
    return candidate;
  } catch {
    return null;
  }
}

export function readRaw(key: string): string | null {
  try {
    const s = storage();
    return s ? s.getItem(key) : null;
  } catch {
    return null;
  }
}

export function writeRaw(key: string, value: string): boolean {
  try {
    const s = storage();
    if (!s) return false;
    s.setItem(key, value);
    return true;
  } catch {
    return false;
  }
}

export function removeRaw(key: string): void {
  try {
    storage()?.removeItem(key);
  } catch {
    // ignore: nothing to remove or storage blocked
  }
}

export function readJson<T>(key: string, validate: (value: unknown) => value is T): T | null {
  const raw = readRaw(key);
  if (raw === null) return null;
  try {
    const parsed: unknown = JSON.parse(raw);
    return validate(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

export function writeJson(key: string, value: unknown): boolean {
  try {
    return writeRaw(key, JSON.stringify(value));
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

export function loadSession(): StoredSession | null {
  return readJson(SESSION_KEY, isStoredSession);
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
  return writeJson(SESSION_KEY, minimal);
}

export function clearSession(): void {
  removeRaw(SESSION_KEY);
}

export function loadPrefs(): Prefs {
  return readJson(PREFS_KEY, isPrefs) ?? { ...DEFAULT_PREFS };
}

export function savePrefs(prefs: Partial<Prefs>): Prefs {
  const merged: Prefs = { ...loadPrefs(), ...prefs };
  writeJson(PREFS_KEY, merged);
  return merged;
}

export function prefsLocale(prefs: Prefs): Locale | null {
  if (prefs.lang && prefs.script) return { lang: prefs.lang, script: prefs.script };
  return null;
}

export function regionOrDefault(value: unknown, fallback: Region = 'BA'): Region {
  return isRegion(value) ? value : fallback;
}

/** Remove everything MILA ever wrote to this browser. */
export function clearAll(): void {
  removeRaw(SESSION_KEY);
  removeRaw(PREFS_KEY);
}
