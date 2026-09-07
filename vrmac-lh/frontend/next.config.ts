import type { NextConfig } from "next";

// The browser always calls same-origin /api/*; Next proxies to the FastAPI service.
// Locally: http://localhost:8000. In docker compose: http://api:8000 (build arg).
const apiInternal = process.env.API_INTERNAL_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  output: "standalone",
  reactStrictMode: true,
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${apiInternal}/api/:path*` }];
  },
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "Permissions-Policy", value: "microphone=(self), geolocation=(self), camera=()" },
        ],
      },
    ];
  },
};

export default nextConfig;
