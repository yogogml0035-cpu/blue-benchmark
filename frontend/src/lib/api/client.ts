import type { components } from "./generated";

/**
 * Unified error shape for every backend call.
 *
 * Mirrors the backend `ErrorResponse` contract so callers can branch on a
 * machine-readable `code` instead of parsing status codes or free text.
 */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: unknown;

  constructor(status: number, code: string, message: string, details: unknown = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }

  /** True when the session expired or was never established. */
  get isAuthError(): boolean {
    return this.status === 401;
  }
}

type ErrorPayload = components["schemas"]["ErrorPayload"];

export interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE";
  /** JSON-serializable request body. */
  body?: unknown;
  signal?: AbortSignal;
  /**
   * Extra headers. JSON content type is applied automatically when a body is
   * present.
   */
  headers?: Record<string, string>;
  /**
   * Whether a 401 should fire the global auth-failure handler (session-expired
   * redirect). Intentional probes and credential submissions opt out so a
   * failed login or an anonymous `/auth/me` check does not itself trigger the
   * redirect. Defaults to true.
   */
  authRedirect?: boolean;
}

let onAuthFailure: (() => void) | null = null;

/**
 * Register the single app-wide handler invoked when any request resolves 401.
 * The session boundary uses this to redirect to the login flow exactly once.
 */
export function setAuthFailureHandler(handler: (() => void) | null): void {
  onAuthFailure = handler;
}

function parseErrorPayload(payload: unknown): ErrorPayload {
  if (
    payload !== null &&
    typeof payload === "object" &&
    "error" in payload &&
    (payload as { error?: unknown }).error !== null &&
    typeof (payload as { error?: unknown }).error === "object"
  ) {
    const error = (payload as { error: Partial<ErrorPayload> }).error;
    return {
      code: typeof error.code === "string" ? error.code : "UNKNOWN",
      message: typeof error.message === "string" ? error.message : "请求失败。",
      details: error.details ?? null,
    };
  }
  return { code: "UNKNOWN", message: "请求失败。", details: null };
}

/**
 * The single fetch wrapper for the app.
 *
 * - Talks to the same-origin `/api` prefix (proxied to FastAPI), so the
 *   HttpOnly session cookie stays first-party.
 * - Parses JSON and 204 responses uniformly.
 * - Converts every non-2xx response into an `ApiError` built from the backend
 *   error contract; network failures become a synthetic `NETWORK` ApiError.
 * - Fires the registered auth handler exactly once per 401.
 */
export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, signal, headers = {}, authRedirect = true } = options;

  const init: RequestInit = {
    method,
    signal,
    credentials: "same-origin",
    // Administrative data is never cacheable; keep every read fresh.
    cache: "no-store",
    headers: {
      Accept: "application/json",
      ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
      ...headers,
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  };

  let response: Response;
  try {
    response = await fetch(path, init);
  } catch (cause) {
    // An AbortError surfaces as a cancellation, not a backend failure.
    if (cause instanceof DOMException && cause.name === "AbortError") {
      throw cause;
    }
    throw new ApiError(0, "NETWORK", "无法连接到服务，请稍后重试。");
  }

  if (response.status === 204) {
    return undefined as T;
  }

  let payload: unknown = null;
  const text = await response.text();
  if (text.length > 0) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = null;
    }
  }

  if (!response.ok) {
    const parsed = parseErrorPayload(payload);
    if (response.status === 401 && authRedirect && onAuthFailure) {
      onAuthFailure();
    }
    throw new ApiError(response.status, parsed.code, parsed.message, parsed.details);
  }

  return payload as T;
}
