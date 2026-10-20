// MILA web client. Output is a standalone server (used by the Dockerfile).
// By default the browser calls the same origin (/api/*) and app/api/[...path]/route.ts forwards
// to MILA_API_URL at runtime. NEXT_PUBLIC_API_BASE is an optional build-time override for static
// deployments; when set, that origin is also allow-listed in the Content-Security-Policy below.

const API_BASE = (process.env.NEXT_PUBLIC_API_BASE ?? '').trim().replace(/\/+$/, '');
const isDev = process.env.NODE_ENV !== 'production';

const apiOrigin = API_BASE ? ` ${API_BASE}` : '';
const csp = [
  "default-src 'self'",
  // Next.js injects inline bootstrap scripts; dev mode also needs eval for fast refresh.
  `script-src 'self' 'unsafe-inline'${isDev ? " 'unsafe-eval'" : ''}`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data:",
  "font-src 'self'",
  `connect-src 'self'${apiOrigin}${isDev ? ' ws: wss:' : ''}`,
  `media-src 'self' blob:${apiOrigin}`,
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
  "manifest-src 'self'",
].join('; ');

const securityHeaders = [
  { key: 'Content-Security-Policy', value: csp },
  { key: 'X-Content-Type-Options', value: 'nosniff' },
  { key: 'X-Frame-Options', value: 'DENY' },
  { key: 'Referrer-Policy', value: 'no-referrer' },
  { key: 'Permissions-Policy', value: 'camera=(), geolocation=(), microphone=(self), payment=(), usb=()' },
  { key: 'Cross-Origin-Opener-Policy', value: 'same-origin' },
  { key: 'Strict-Transport-Security', value: 'max-age=63072000; includeSubDomains' },
  { key: 'X-DNS-Prefetch-Control', value: 'off' },
];

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone',
  reactStrictMode: true,
  poweredByHeader: false,
  images: { unoptimized: true },
  async headers() {
    return [{ source: '/:path*', headers: securityHeaders }];
  },
};

export default nextConfig;
