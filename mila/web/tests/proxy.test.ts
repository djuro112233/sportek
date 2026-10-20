import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  DEFAULT_UPSTREAM,
  FORWARDED_REQUEST_HEADERS,
  FORWARDED_RESPONSE_HEADERS,
  proxyRequest,
  upstreamBase,
  upstreamUrl,
} from '../lib/proxy.ts';

test('upstreamBase reads MILA_API_URL at runtime and strips trailing slashes', () => {
  assert.equal(upstreamBase({}), DEFAULT_UPSTREAM);
  assert.equal(upstreamBase({ MILA_API_URL: '' }), DEFAULT_UPSTREAM);
  assert.equal(upstreamBase({ MILA_API_URL: 'http://api:8000/' }), 'http://api:8000');
  assert.equal(upstreamUrl('http://api:8000', ['session', 'a b', 'preferences'], '?x=1'), 'http://api:8000/api/session/a%20b/preferences?x=1');
});

test('the header allow-lists are exactly the documented ones', () => {
  assert.deepEqual([...FORWARDED_REQUEST_HEADERS], ['content-type', 'x-admin-token', 'accept']);
  assert.deepEqual([...FORWARDED_RESPONSE_HEADERS], ['content-type', 'content-disposition', 'cache-control', 'retry-after']);
});

test('POST is streamed to the API with only the allowed headers; status and headers come back', async () => {
  let seenUrl = '';
  let seenInit: RequestInit | undefined;
  let seenBody = '';
  const fetchImpl = (async (input: RequestInfo | URL, init?: RequestInit) => {
    seenUrl = String(input);
    seenInit = init;
    seenBody = await new Response(init?.body as BodyInit).text();
    return new Response(JSON.stringify({ detail: 'rate limited' }), {
      status: 429,
      headers: {
        'Content-Type': 'application/json',
        'Retry-After': '60',
        'Cache-Control': 'no-store',
        'X-Internal': 'secret',
        'Set-Cookie': 'a=b',
      },
    });
  }) as typeof fetch;

  const req = new Request('http://web.local/api/ask?debug=1', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/json',
      'X-Admin-Token': 'tok',
      Cookie: 'session=leak',
      'User-Agent': 'browser',
      Authorization: 'Bearer leak',
    },
    body: JSON.stringify({ text: 'hi' }),
  });
  const res = await proxyRequest(req, ['ask'], { base: 'http://api:8000', fetchImpl });

  assert.equal(seenUrl, 'http://api:8000/api/ask?debug=1');
  assert.equal(seenInit?.method, 'POST');
  assert.equal(seenBody, '{"text":"hi"}');
  const sent = new Headers(seenInit?.headers);
  assert.equal(sent.get('content-type'), 'application/json');
  assert.equal(sent.get('accept'), 'application/json');
  assert.equal(sent.get('x-admin-token'), 'tok');
  assert.equal(sent.get('cookie'), null);
  assert.equal(sent.get('authorization'), null);
  assert.equal(sent.get('user-agent'), null);
  assert.equal((seenInit as { duplex?: string } | undefined)?.duplex, 'half');
  assert.equal(seenInit?.cache, 'no-store');

  assert.equal(res.status, 429);
  assert.equal(res.headers.get('retry-after'), '60');
  assert.equal(res.headers.get('content-type'), 'application/json');
  assert.equal(res.headers.get('cache-control'), 'no-store');
  assert.equal(res.headers.get('x-internal'), null);
  assert.equal(res.headers.get('set-cookie'), null);
  assert.deepEqual(await res.json(), { detail: 'rate limited' });
});

test('GET and DELETE carry no body; binary audio passes through with Content-Disposition', async () => {
  const seen: Array<{ method: string; body: unknown }> = [];
  const fetchImpl = (async (_input: RequestInfo | URL, init?: RequestInit) => {
    seen.push({ method: String(init?.method), body: init?.body });
    return new Response(new Uint8Array([82, 73, 70, 70]), {
      status: 200,
      headers: { 'Content-Type': 'audio/wav', 'Content-Disposition': 'inline; filename="mila.wav"' },
    });
  }) as typeof fetch;
  const get = await proxyRequest(new Request('http://web.local/api/audio/tok'), ['audio', 'tok'], { base: 'http://api', fetchImpl });
  assert.equal(get.status, 200);
  assert.equal(get.headers.get('content-type'), 'audio/wav');
  assert.equal(get.headers.get('content-disposition'), 'inline; filename="mila.wav"');
  assert.equal(get.headers.get('cache-control'), 'no-store');
  assert.equal((await get.arrayBuffer()).byteLength, 4);
  const del = await proxyRequest(new Request('http://web.local/api/session/x', { method: 'DELETE' }), ['session', 'x'], {
    base: 'http://api',
    fetchImpl,
  });
  assert.equal(del.status, 200);
  assert.deepEqual(
    seen.map((s) => s.method),
    ['GET', 'DELETE'],
  );
  assert.ok(seen.every((s) => s.body === undefined));
});

test('an unreachable or slow API answers 502 / 504 JSON instead of throwing', async () => {
  const down = (async () => {
    throw new TypeError('fetch failed');
  }) as typeof fetch;
  const res = await proxyRequest(new Request('http://web.local/api/health'), ['health'], { base: 'http://api', fetchImpl: down });
  assert.equal(res.status, 502);
  assert.deepEqual(await res.json(), { detail: 'upstream unavailable' });

  const slow = ((_input: RequestInfo | URL, init?: RequestInit) =>
    new Promise<Response>((_resolve, reject) => {
      init?.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')));
    })) as typeof fetch;
  const timeout = await proxyRequest(new Request('http://web.local/api/health'), ['health'], {
    base: 'http://api',
    fetchImpl: slow,
    timeoutMs: 20,
  });
  assert.equal(timeout.status, 504);

  const put = await proxyRequest(new Request('http://web.local/api/health', { method: 'PUT' }), ['health'], {
    base: 'http://api',
    fetchImpl: down,
  });
  assert.equal(put.status, 405);
});
