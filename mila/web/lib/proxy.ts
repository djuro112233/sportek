/**
 * Same-origin proxy for the MILA API, used by `app/api/[...path]/route.ts`.
 *
 * The browser calls `/api/...` on the web origin; the Next.js server forwards the request to
 * `MILA_API_URL` (default `http://localhost:8000`) at runtime, so one image works wherever it
 * is deployed. Only a short allow-list of headers crosses in each direction, bodies are streamed
 * (no buffering of audio uploads), nothing is cached, and no cookies exist on either side.
 *
 * Kept outside the route file because Next.js rejects unknown exports from route modules.
 */

export const DEFAULT_UPSTREAM = 'http://localhost:8000';

/** Longer than the client's longest timeout (60 s for /api/ask) so the client decides first. */
export const UPSTREAM_TIMEOUT_MS = 75_000;

/** Request headers forwarded to the API. Everything else (cookies, host, user agent) is dropped. */
export const FORWARDED_REQUEST_HEADERS: readonly string[] = ['content-type', 'x-admin-token', 'accept'];

/** Response headers passed back to the browser. */
export const FORWARDED_RESPONSE_HEADERS: readonly string[] = [
  'content-type',
  'content-disposition',
  'cache-control',
  'retry-after',
];

export type ProxyMethod = 'GET' | 'POST' | 'DELETE';

export interface ProxyOptions {
  /** API origin without a trailing slash; defaults to `MILA_API_URL` or `DEFAULT_UPSTREAM`. */
  base?: string;
  fetchImpl?: typeof fetch;
  timeoutMs?: number;
}

/** `MILA_API_URL` without a trailing slash, or the default. */
export function upstreamBase(env: Record<string, string | undefined> = process.env): string {
  const raw = (env.MILA_API_URL ?? '').trim();
  return (raw || DEFAULT_UPSTREAM).replace(/\/+$/, '');
}

/** Rebuild the API URL from the decoded path segments and the original query string. */
export function upstreamUrl(base: string, path: readonly string[], search: string): string {
  const joined = path.map((segment) => encodeURIComponent(segment)).join('/');
  return `${base}/api/${joined}${search}`;
}

function jsonResponse(status: number, detail: string): Response {
  return new Response(JSON.stringify({ detail }), {
    status,
    headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' },
  });
}

/** Forward one request to the API and stream the answer back. Never throws. */
export async function proxyRequest(req: Request, path: readonly string[], opts: ProxyOptions = {}): Promise<Response> {
  const method = req.method.toUpperCase();
  if (method !== 'GET' && method !== 'POST' && method !== 'DELETE') {
    return new Response(null, { status: 405, headers: { Allow: 'GET, POST, DELETE', 'Cache-Control': 'no-store' } });
  }
  const base = opts.base ?? upstreamBase();
  const doFetch = opts.fetchImpl ?? fetch;
  const url = upstreamUrl(base, path, new URL(req.url).search);

  const headers = new Headers();
  for (const name of FORWARDED_REQUEST_HEADERS) {
    const value = req.headers.get(name);
    if (value !== null) headers.set(name, value);
  }

  const controller = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, opts.timeoutMs ?? UPSTREAM_TIMEOUT_MS);
  const onClientAbort = () => controller.abort();
  try {
    req.signal.addEventListener('abort', onClientAbort, { once: true });
  } catch {
    // a minimal Request without a signal (tests)
  }

  // Streams the body through; `duplex: 'half'` is required by Node's fetch for streamed bodies.
  const init = {
    method,
    headers,
    body: method === 'POST' ? req.body : undefined,
    signal: controller.signal,
    cache: 'no-store',
    redirect: 'manual',
    credentials: 'omit',
    duplex: 'half',
  } as RequestInit;

  let upstream: Response;
  try {
    upstream = await doFetch(url, init);
  } catch {
    if (timedOut) return jsonResponse(504, 'upstream timeout');
    return jsonResponse(502, 'upstream unavailable');
  } finally {
    clearTimeout(timer);
    try {
      req.signal.removeEventListener('abort', onClientAbort);
    } catch {
      // see above
    }
  }

  const out = new Headers();
  for (const name of FORWARDED_RESPONSE_HEADERS) {
    const value = upstream.headers.get(name);
    if (value !== null) out.set(name, value);
  }
  if (!out.has('cache-control')) out.set('cache-control', 'no-store');
  const bodyless = upstream.status === 204 || upstream.status === 304;
  return new Response(bodyless ? null : upstream.body, { status: upstream.status, headers: out });
}
