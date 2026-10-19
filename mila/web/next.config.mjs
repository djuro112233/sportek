// MILA web client. Output is a standalone server (used by the Dockerfile).
// The API base is inlined at build time from NEXT_PUBLIC_API_BASE and also
// allow-listed in the Content-Security-Policy below.

const rawBase = process.env.NEXT_PUBLIC_API_BASE;
const API_BASE = (rawBase === undefined ? 'http://localhost:8000' : rawBase).replace(/\/+$/, '');
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
