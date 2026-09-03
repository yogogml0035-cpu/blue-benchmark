/**
 * Next.js configuration for the local admin console.
 *
 * The browser only talks to the same-origin `/api` prefix; every request is
 * rewritten to the FastAPI backend so the HttpOnly session cookie stays
 * first-party. `BACKEND_URL` is server-side only and never leaks to the
 * browser bundle.
 */

const BACKEND_URL = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";

/** @type {import('next').NextConfig} */
const nextConfig = {
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${BACKEND_URL}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
