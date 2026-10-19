import { afterEach, beforeEach, test } from 'node:test';
import assert from 'node:assert/strict';

import {
  clearAll,
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

const g = globalThis as { localStorage?: unknown };

beforeEach(() => {
  g.localStorage = new FakeStorage();
});

afterEach(() => {
  delete g.localStorage;
});

test('session round-trips and only the allowed fields are stored', () => {
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
  const raw = (g.localStorage as FakeStorage).getItem(SESSION_KEY) ?? '';
  assert.doesNotMatch(raw, /never stored/);
  assert.deepEqual(loadSession(), { session_id: 'abc', lang: 'sr', script: 'cyrillic', region: 'ME', is_minor: true });
});

test('corrupted or invalid stored values read as null', () => {
  (g.localStorage as FakeStorage).setItem(SESSION_KEY, '{not json');
  assert.equal(loadSession(), null);
  (g.localStorage as FakeStorage).setItem(SESSION_KEY, JSON.stringify({ session_id: 'x', lang: 'zz' }));
  assert.equal(loadSession(), null);
  assert.equal(isStoredSession({ session_id: '', lang: 'sr', script: 'latin', region: 'BA', is_minor: false }), false);
});

test('prefs default to low_bandwidth off and merge on save', () => {
  assert.deepEqual(loadPrefs(), { low_bandwidth: false, lang: null, script: null });
  savePrefs({ low_bandwidth: true });
  savePrefs({ lang: 'hr', script: 'latin' });
  assert.deepEqual(loadPrefs(), { low_bandwidth: true, lang: 'hr', script: 'latin' });
  clearAll();
  assert.equal((g.localStorage as FakeStorage).getItem(PREFS_KEY), null);
  assert.equal(loadSession(), null);
});

test('a throwing or missing storage never throws out of the wrappers', () => {
  g.localStorage = {
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
  assert.equal(loadSession(), null);
  assert.equal(saveSession({ session_id: 'a', lang: 'en', script: 'latin', region: 'BA', is_minor: false }), false);
  assert.doesNotThrow(() => clearAll());
  delete g.localStorage;
  assert.equal(loadSession(), null);
  assert.deepEqual(loadPrefs(), { low_bandwidth: false, lang: null, script: null });
});
