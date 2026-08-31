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
  const response = await fetch(path, { ...init, cache: "no-store", headers, credentials: "include" });
  if (response.status === 204) return undefined as T;
  const body = (await response.json().catch(() => undefined)) as
    | { error?: ErrorPayload }
    | undefined;
  if (!response.ok) throw new ApiError(response.status, body?.error);
  return body as T;
}

/**
 * 同源的增量响应入口。SSE 不是业务事实源，调用方仍需用 GET 快照确认
 * 状态；这里仅复用统一 Cookie 与错误合同，避免组件各自直接 fetch。
 */
export async function apiStream(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  const response = await fetch(path, { ...init, cache: "no-store", headers, credentials: "include" });
  if (response.ok) return response;

  const body = (await response.json().catch(() => undefined)) as
    | { error?: ErrorPayload }
    | undefined;
  throw new ApiError(response.status, body?.error);
}
