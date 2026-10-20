import { afterEach, test } from 'node:test';
import assert from 'node:assert/strict';

import {
  API_BASE,
  ApiError,
  apiUrl,
  ask,
  DEFAULT_RETRY_AFTER_S,
  errorMessageKey,
  getAudio,
  getConsentText,
  getSession,
  isConsentVersionOutdated,
  isSessionGone,
  parseRetryAfter,
  postConsent,
  requestJson,
  resolveAudioUrl,
  retryAfterSeconds,
  speak,
} from '../lib/api.ts';
import { isPipelineError } from '../lib/types.ts';

const g = globalThis as { fetch: typeof fetch };
const realFetch = g.fetch;

afterEach(() => {
  g.fetch = realFetch;
});

function jsonResponse(body: unknown, status = 200, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json', ...headers } });
}

const askBody = {
  session_id: 's',
  text: 'q',
  lang: 'sr',
  script: 'latin',
  region: 'BA',
  input_mode: 'text',
  want_audio: false,
  low_bandwidth: false,
} as const;

test('API_BASE defaults to the same origin and builds URLs without double slashes', () => {
  assert.equal(API_BASE, '');
  assert.equal(apiUrl('/api/ask'), '/api/ask');
  assert.equal(apiUrl('api/ask'), '/api/ask');
  assert.equal(apiUrl('https://api.example/api/audio/x'), 'https://api.example/api/audio/x');
  assert.equal(resolveAudioUrl('/api/audio/x.wav'), '/api/audio/x.wav');
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
  assert.equal(seenUrl, '/api/consent/text?lang=sr&script=cyrillic&is_minor=true');
  assert.equal(seenInit?.method, 'GET');
  assert.equal(res.version, '2026-10-01');
});

test('HTTP errors become ApiError with status and detail, and map to message keys', async () => {
  g.fetch = (async () => jsonResponse({ detail: 'consent_version_outdated' }, 403)) as typeof fetch;
  await assert.rejects(ask(askBody), (err: unknown) => {
    assert.ok(err instanceof ApiError);
    assert.equal(err.kind, 'http');
    assert.equal(err.status, 403);
    assert.equal(err.detail, 'consent_version_outdated');
    assert.equal(err.retryAfter, null);
    assert.equal(errorMessageKey(err), 'session_expired');
    assert.equal(isSessionGone(err), true);
    assert.equal(isConsentVersionOutdated(err), false);
    return true;
  });
  assert.equal(errorMessageKey(new ApiError('http', 'x', 403, 'consent required')), 'session_expired');
  assert.equal(errorMessageKey(new ApiError('http', 'x', 403, 'unknown session; give consent first')), 'session_expired');
  assert.equal(errorMessageKey(new ApiError('http', 'x', 500)), 'error_server');
  assert.equal(errorMessageKey(new ApiError('http', 'x', 404)), 'error_server');
  assert.equal(errorMessageKey(new ApiError('http', 'x', 409, 'consent_version_outdated')), 'error_server');
  assert.equal(errorMessageKey(new ApiError('network', 'x')), 'error_network');
  assert.equal(errorMessageKey(new ApiError('timeout', 'x')), 'error_timeout');
  assert.equal(errorMessageKey(new Error('other')), 'error_server');
  assert.equal(isSessionGone(new ApiError('http', 'x', 404)), false);
  assert.equal(isSessionGone(new Error('x')), false);
});

test('429 carries Retry-After, maps to error_rate_limited and tells the UI how long to wait', async () => {
  g.fetch = (async () => jsonResponse({ detail: 'rate limited' }, 429, { 'Retry-After': '17' })) as typeof fetch;
  await assert.rejects(ask(askBody), (err: unknown) => {
    assert.ok(err instanceof ApiError);
    assert.equal(err.status, 429);
    assert.equal(err.retryAfter, 17);
    assert.equal(errorMessageKey(err), 'error_rate_limited');
    assert.equal(retryAfterSeconds(err), 17);
    return true;
  });
  // Without the header (e.g. a cross-origin deployment that does not expose it) the UI waits the default.
  g.fetch = (async () => jsonResponse({ detail: 'rate limited' }, 429)) as typeof fetch;
  await assert.rejects(ask(askBody), (err: unknown) => {
    assert.ok(err instanceof ApiError);
    assert.equal(err.retryAfter, null);
    assert.equal(retryAfterSeconds(err), DEFAULT_RETRY_AFTER_S);
    return true;
  });
  assert.equal(retryAfterSeconds(new ApiError('http', 'x', 500)), null);
  assert.equal(retryAfterSeconds(new Error('x')), null);
});

test('parseRetryAfter accepts delta-seconds and HTTP dates', () => {
  const now = Date.parse('Wed, 21 Oct 2026 07:28:00 GMT');
  assert.equal(parseRetryAfter('60'), 60);
  assert.equal(parseRetryAfter(' 5 '), 5);
  assert.equal(parseRetryAfter('0'), 0);
  assert.equal(parseRetryAfter('Wed, 21 Oct 2026 07:28:30 GMT', now), 30);
  assert.equal(parseRetryAfter('Wed, 21 Oct 2026 07:27:00 GMT', now), 0);
  assert.equal(parseRetryAfter('soon'), null);
  assert.equal(parseRetryAfter(''), null);
  assert.equal(parseRetryAfter(null), null);
  assert.equal(parseRetryAfter(undefined), null);
});

test('409 consent_version_outdated from POST /api/consent is recognised', async () => {
  g.fetch = (async () => jsonResponse({ detail: 'consent_version_outdated', current: '2026-11-01' }, 409)) as typeof fetch;
  await assert.rejects(
    postConsent({
      lang: 'sr',
      script: 'latin',
      region: 'BA',
      is_minor: false,
      accepted: true,
      save_questions: false,
      consent_version: '2026-10-01',
    }),
    (err: unknown) => {
      assert.equal(isConsentVersionOutdated(err), true);
      assert.equal(isSessionGone(err), false);
      return true;
    },
  );
  assert.equal(isConsentVersionOutdated(new ApiError('http', 'x', 409, 'other')), false);
});

test('getSession returns the session info shape (exists:false for an unknown id, no error)', async () => {
  g.fetch = (async () =>
    jsonResponse({
      exists: false,
      consent_given: null,
      consent_version: null,
      lang: null,
      script: null,
      region: null,
      is_minor: null,
      save_questions: null,
    })) as typeof fetch;
  const info = await getSession('gone');
  assert.equal(info.exists, false);
  assert.equal(info.consent_given, null);
});

test('isPipelineError only fires on the pipeline_error gate reason', () => {
  const gate = { status: 'withheld' as const, reasons: ['pipeline_error'], support_ratio: 0, confidence: 0, relevance: null, kept: [], removed: [] };
  assert.equal(isPipelineError({ gate }), true);
  assert.equal(isPipelineError({ gate: { ...gate, reasons: ['low_support_ratio'] } }), false);
  assert.equal(isPipelineError({ gate: null }), false);
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

test('getAudio fetches the one-time audio_url once into a Blob and reports a consumed token as 404', async () => {
  const urls: string[] = [];
  g.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    urls.push(String(input));
    assert.equal(new Headers(init?.headers).get('Accept'), 'audio/wav');
    return urls.length === 1
      ? new Response(new Uint8Array([82, 73, 70, 70]), { status: 200, headers: { 'Content-Type': 'audio/wav' } })
      : jsonResponse({ detail: 'unknown or expired audio token' }, 404);
  }) as typeof fetch;
  const blob = await getAudio('/api/audio/tok');
  assert.equal(blob.size, 4);
  assert.deepEqual(urls, ['/api/audio/tok']);
  await assert.rejects(getAudio('/api/audio/tok'), (err: unknown) => err instanceof ApiError && err.status === 404);
});
