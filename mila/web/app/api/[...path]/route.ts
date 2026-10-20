/**
 * Runtime proxy: `/api/*` on the web origin -> `MILA_API_URL` (default http://localhost:8000).
 * See lib/proxy.ts. Forwards GET, POST and DELETE only; never cached.
 */

import { proxyRequest } from '@/lib/proxy';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

interface Context {
  params: { path: string[] };
}

function handle(req: Request, ctx: Context): Promise<Response> {
  return proxyRequest(req, ctx.params.path ?? []);
}

export const GET = handle;
export const POST = handle;
export const DELETE = handle;
