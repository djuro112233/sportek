import { afterEach, beforeEach, test } from 'node:test';
import assert from 'node:assert/strict';

import {
  clearAll,
  clearSession,
  isStoredSession,
  loadPrefs,
  loadSession,
  PREFS_KEY,
  savePrefs,
  saveSession,
  SESSION_KEY,
} from '../lib/storage.ts';

class FakeStorage {
  private map = new Map<string, string>();
  get length(): number {
    return this.map.size;
  }
  clear(): void {
    this.map.clear();
  }
  getItem(key: string): string | null {
    return this.map.has(key) ? (this.map.get(key) as string) : null;
  }
  key(index: number): string | null {
    return Array.from(this.map.keys())[index] ?? null;
  }
  removeItem(key: string): void {
    this.map.delete(key);
  }
  setItem(key: string, value: string): void {
    this.map.set(key, String(value));
  }
}

const g = globalThis as { localStorage?: unknown; sessionStorage?: unknown };
const local = () => g.localStorage as FakeStorage;
const sess = () => g.sessionStorage as FakeStorage;

beforeEach(() => {
  g.localStorage = new FakeStorage();
  g.sessionStorage = new FakeStorage();
});

afterEach(() => {
  delete g.localStorage;
  delete g.sessionStorage;
});

test('session round-trips through sessionStorage only and keeps just the allowed fields', () => {
  const saved = saveSession({
    session_id: 'abc',
    lang: 'sr',
    script: 'cyrillic',
    region: 'ME',
    is_minor: true,
    // @ts-expect-error extra fields must be dropped
    question: 'never stored',
  });
  assert.equal(saved, true);
  const raw = sess().getItem(SESSION_KEY) ?? '';
  assert.doesNotMatch(raw, /never stored/);
  assert.deepEqual(loadSession(), { session_id: 'abc', lang: 'sr', script: 'cyrillic', region: 'ME', is_minor: true });
  // PRIV-6: the session id must never land in localStorage (shared clinic devices).
  assert.equal(local().getItem(SESSION_KEY), null);
  assert.equal(local().length, 0);
});

test('a session left in localStorage by an older build is dropped, never resumed', () => {
  local().setItem(SESSION_KEY, JSON.stringify({ session_id: 'old', lang: 'sr', script: 'latin', region: 'BA', is_minor: false }));
  assert.equal(loadSession(), null);
  assert.equal(local().getItem(SESSION_KEY), null);
});

test('corrupted or invalid stored values read as null', () => {
  sess().setItem(SESSION_KEY, '{not json');
  assert.equal(loadSession(), null);
  sess().setItem(SESSION_KEY, JSON.stringify({ session_id: 'x', lang: 'zz' }));
  assert.equal(loadSession(), null);
  assert.equal(isStoredSession({ session_id: '', lang: 'sr', script: 'latin', region: 'BA', is_minor: false }), false);
});

test('prefs live in localStorage, default to low_bandwidth off and merge on save', () => {
  assert.deepEqual(loadPrefs(), { low_bandwidth: false, lang: null, script: null });
  savePrefs({ low_bandwidth: true });
  savePrefs({ lang: 'hr', script: 'latin' });
  assert.deepEqual(loadPrefs(), { low_bandwidth: true, lang: 'hr', script: 'latin' });
  assert.ok(local().getItem(PREFS_KEY));
  assert.equal(sess().getItem(PREFS_KEY), null);
  // Only the three known preferences are written, whatever else is passed.
  savePrefs({ low_bandwidth: false, session_id: 'leak' } as Partial<{ low_bandwidth: boolean }>);
  assert.doesNotMatch(local().getItem(PREFS_KEY) ?? '', /leak/);
});

test('clearSession forgets the session but keeps preferences; clearAll removes both', () => {
  saveSession({ session_id: 'abc', lang: 'en', script: 'latin', region: 'BA', is_minor: false });
  savePrefs({ lang: 'en', script: 'latin' });
  clearSession();
  assert.equal(loadSession(), null);
  assert.deepEqual(loadPrefs(), { low_bandwidth: false, lang: 'en', script: 'latin' });
  clearAll();
  assert.equal(local().getItem(PREFS_KEY), null);
  assert.equal(sess().getItem(SESSION_KEY), null);
  assert.equal(loadSession(), null);
});

test('a throwing or missing storage never throws out of the wrappers', () => {
  const blocked = {
    getItem() {
      throw new Error('blocked');
    },
    setItem() {
      throw new Error('blocked');
    },
    removeItem() {
      throw new Error('blocked');
    },
  };
  g.localStorage = blocked;
  g.sessionStorage = blocked;
  assert.equal(loadSession(), null);
  assert.equal(saveSession({ session_id: 'a', lang: 'en', script: 'latin', region: 'BA', is_minor: false }), false);
  assert.doesNotThrow(() => clearAll());
  delete g.localStorage;
  delete g.sessionStorage;
  assert.equal(loadSession(), null);
  assert.equal(saveSession({ session_id: 'a', lang: 'en', script: 'latin', region: 'BA', is_minor: false }), false);
  assert.deepEqual(loadPrefs(), { low_bandwidth: false, lang: null, script: null });
});
