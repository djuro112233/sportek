import { afterEach, test } from 'node:test';
import assert from 'node:assert/strict';

import {
  API_BASE,
  ApiError,
  apiUrl,
  ask,
  errorMessageKey,
  getConsentText,
  requestJson,
  resolveAudioUrl,
  speak,
} from '../lib/api.ts';

const g = globalThis as { fetch: typeof fetch };
const realFetch = g.fetch;

afterEach(() => {
  g.fetch = realFetch;
});

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

test('API_BASE defaults to localhost:8000 and builds URLs without double slashes', () => {
  assert.equal(API_BASE, 'http://localhost:8000');
  assert.equal(apiUrl('/api/ask'), 'http://localhost:8000/api/ask');
  assert.equal(apiUrl('api/ask'), 'http://localhost:8000/api/ask');
  assert.equal(resolveAudioUrl('/api/audio/x.wav'), 'http://localhost:8000/api/audio/x.wav');
  assert.equal(resolveAudioUrl('https://cdn.example/x.wav'), 'https://cdn.example/x.wav');
  assert.equal(resolveAudioUrl('blob:abc'), 'blob:abc');
});

test('getConsentText encodes the query and parses JSON', async () => {
  let seenUrl = '';
  let seenInit: RequestInit | undefined;
  g.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    seenUrl = String(input);
    seenInit = init;
    return jsonResponse({ version: '2026-10-01', text: 'hi', spoken_text: 'hi', items: [] });
  }) as typeof fetch;
  const res = await getConsentText({ lang: 'sr', script: 'cyrillic' }, true);
  assert.equal(seenUrl, 'http://localhost:8000/api/consent/text?lang=sr&script=cyrillic&is_minor=true');
  assert.equal(seenInit?.method, 'GET');
  assert.equal(res.version, '2026-10-01');
});

test('HTTP errors become ApiError with status and detail, and map to message keys', async () => {
  g.fetch = (async () => jsonResponse({ detail: 'consent required' }, 403)) as typeof fetch;
  await assert.rejects(
    ask({
      session_id: 's',
      text: 'q',
      lang: 'sr',
      script: 'latin',
      region: 'BA',
      input_mode: 'text',
      want_audio: false,
      low_bandwidth: false,
    }),
    (err: unknown) => {
      assert.ok(err instanceof ApiError);
      assert.equal(err.kind, 'http');
      assert.equal(err.status, 403);
      assert.equal(err.detail, 'consent required');
      assert.equal(errorMessageKey(err), 'session_expired');
      return true;
    },
  );
  assert.equal(errorMessageKey(new ApiError('http', 'x', 500)), 'error_server');
  assert.equal(errorMessageKey(new ApiError('http', 'x', 404)), 'error_server');
  assert.equal(errorMessageKey(new ApiError('network', 'x')), 'error_network');
  assert.equal(errorMessageKey(new ApiError('timeout', 'x')), 'error_timeout');
  assert.equal(errorMessageKey(new Error('other')), 'error_server');
});

test('network failures become ApiError(network)', async () => {
  g.fetch = (async () => {
    throw new TypeError('Failed to fetch');
  }) as typeof fetch;
  await assert.rejects(speak({ text: 'a', lang: 'sr', script: 'latin', low_bandwidth: true }), (err: unknown) => {
    assert.ok(err instanceof ApiError);
    assert.equal(err.kind, 'network');
    return true;
  });
});

test('requests abort on timeout and surface ApiError(timeout)', async () => {
  // The fake fetch honours the AbortSignal, exactly like a real network request.
  g.fetch = ((_input: RequestInfo | URL, init?: RequestInit) =>
    new Promise<Response>((_resolve, reject) => {
      init?.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')));
    })) as typeof fetch;
  const started = Date.now();
  await assert.rejects(requestJson('/api/health', { timeoutMs: 20 }), (err: unknown) => {
    assert.ok(err instanceof ApiError);
    assert.equal(err.kind, 'timeout');
    assert.equal(errorMessageKey(err), 'error_timeout');
    return true;
  });
  // An external abort is reported as "aborted", not as a timeout.
  const controller = new AbortController();
  const pending = getConsentText({ lang: 'en', script: 'latin' }, false, controller.signal);
  controller.abort();
  await assert.rejects(pending, (err: unknown) => err instanceof ApiError && err.kind === 'aborted');
  assert.ok(Date.now() - started < 5000, 'external abort must not wait for the timeout');
});

test('speak posts JSON and returns a Blob', async () => {
  let seenBody = '';
  g.fetch = (async (_input: RequestInfo | URL, init?: RequestInit) => {
    seenBody = String(init?.body);
    return new Response(new Uint8Array([82, 73, 70, 70]), { status: 200, headers: { 'Content-Type': 'audio/wav' } });
  }) as typeof fetch;
  const blob = await speak({ text: 'zdravo', lang: 'sr', script: 'latin', low_bandwidth: true });
  assert.deepEqual(JSON.parse(seenBody), { text: 'zdravo', lang: 'sr', script: 'latin', low_bandwidth: true });
  assert.equal(blob.size, 4);
});
