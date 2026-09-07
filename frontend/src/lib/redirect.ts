/**
 * Safe handling of the `returnTo` query parameter.
 *
 * Only a same-origin relative path is ever honored. Anything that could
 * navigate off-site — protocol-relative URLs, absolute URLs, scheme-bearing
 * strings, or backslash tricks — is rejected so the login flow can never be
 * turned into an open redirect.
 */

export function isSafeReturnPath(value: string | null | undefined): value is string {
  if (typeof value !== "string" || value.length === 0) {
    return false;
  }
  // Must start with exactly one "/".
  if (!value.startsWith("/")) {
    return false;
  }
  // Reject protocol-relative ("//host") and any backslash variant.
  if (value.startsWith("//") || value.includes("\\")) {
    return false;
  }
  // Reject control characters that could confuse the URL parser.
  if (/[\u0000-\u001f\u007f]/.test(value)) {
    return false;
  }
  // Final guard: parse it against a dummy base and require the origin to stay
  // put and the path to remain relative.
  try {
    const parsed = new URL(value, "http://localhost");
    if (parsed.origin !== "http://localhost") {
      return false;
    }
    return true;
  } catch {
    return false;
  }
}

/** Normalize a validated return path, dropping any query/fragment tail. */
export function sanitizeReturnPath(value: string): string {
  // At this point the value is a safe relative path; keep only the pathname.
  const parsed = new URL(value, "http://localhost");
  return parsed.pathname || "/";
}

/** Build the redirect target for a successful auth, honoring a safe returnTo. */
export function resolvePostAuthPath(returnTo: string | null | undefined): string {
  if (isSafeReturnPath(returnTo)) {
    return sanitizeReturnPath(returnTo);
  }
  return "/evaluation-sets";
}

/** Build a login URL that carries a safe returnTo forward. */
export function buildAuthUrl(base: "/login", returnTo?: string | null): string {
  if (isSafeReturnPath(returnTo)) {
    return `${base}?returnTo=${encodeURIComponent(sanitizeReturnPath(returnTo))}`;
  }
  return base;
}
