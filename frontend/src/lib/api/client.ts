import type { components } from "@/src/lib/api/generated";

type ErrorPayload = components["schemas"]["ErrorPayload"];

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: ErrorPayload["details"];

  constructor(status: number, payload?: ErrorPayload) {
    super(payload?.message ?? "请求失败，请稍后重试。");
    this.name = "ApiError";
    this.status = status;
    this.code = payload?.code ?? "UNKNOWN_ERROR";
    this.details = payload?.details;
  }
}

export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !(init.body instanceof FormData)) {
    headers.set("content-type", "application/json");
  }
  const response = await fetch(path, { ...init, headers, credentials: "include" });
  if (response.status === 204) return undefined as T;
  const body = (await response.json().catch(() => undefined)) as
    | { error?: ErrorPayload }
    | undefined;
  if (!response.ok) throw new ApiError(response.status, body?.error);
  return body as T;
}

