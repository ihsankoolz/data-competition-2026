import type { NextConfig } from "next";

/** Where the FastAPI backend runs. The browser reaches it via /api/*. */
const API_ORIGIN = process.env.API_ORIGIN ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  // Playwright runs its own dev server with a separate build folder (see playwright.config.ts).
  distDir: process.env.NEXT_DIST_DIR ?? ".next",
  cacheComponents: true,
  // The "N" dev badge would show in the demo video (D-022 #5). Errors still show their overlay.
  devIndicators: false,
  // Next's gzip buffers a proxied text/event-stream until it ends, which turned the live AI
  // trace (D-023 #3) into one burst. Everything here is served on localhost, so gzip buys nothing.
  compress: false,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  async redirects() {
    return [{ source: "/", destination: "/inbox", permanent: false }];
  },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_ORIGIN}/:path*` }];
  },
};

export default nextConfig;
