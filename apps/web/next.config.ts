import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // The e2e server builds elsewhere so it can run next to `next dev`.
  distDir: process.env.NEXT_DIST_DIR ?? ".next",
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  // Same-origin proxy to FastAPI, so the session cookie needs no CORS.
  async rewrites() {
    // Render's private network gives "host:port" with no scheme.
    const raw = process.env.API_URL ?? "http://localhost:8000";
    const api = /^https?:\/\//.test(raw) ? raw : `http://${raw}`;
    return [{ source: "/api/:path*", destination: `${api}/:path*` }];
  },
};

export default nextConfig;
