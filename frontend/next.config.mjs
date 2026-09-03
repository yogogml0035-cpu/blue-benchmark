/**
 * Next.js configuration for the local admin console.
 *
 * The browser only talks to the same-origin `/api` prefix; every request is
 * rewritten to the FastAPI backend so the HttpOnly session cookie stays
 * first-party. `BACKEND_URL` is server-side only and never leaks to the
 * browser bundle.
 */

function resolveBackendUrl(raw) {
  const value = raw ?? "http://127.0.0.1:8000";
  let parsed;
  try {
    parsed = new URL(value);
  } catch {
    throw new Error(`BACKEND_URL is not a valid URL: ${value}`);
  }
  // The /api rewrite forwards the session cookie to this destination; refuse
  // anything that is not plain http(s) so a misconfiguration cannot silently
  // exfiltrate the cookie to an unexpected scheme/host.
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    throw new Error(`BACKEND_URL must use http(s), got: ${value}`);
  }
  return value;
}

const BACKEND_URL = resolveBackendUrl(process.env.BACKEND_URL);

/** @type {import('next').NextConfig} */
const nextConfig = {
  // Defense-in-depth headers applied to every page.
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "same-origin" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Content-Security-Policy", value: "frame-ancestors 'none'" },
        ],
      },
    ];
  },
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
