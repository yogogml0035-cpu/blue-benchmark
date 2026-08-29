import { ApiError } from "@/src/lib/api/client";

/**
 * 页面级故障：把 HTTP 状态收敛成“页面该整屏呈现什么”。
 * 按架构合同，401 跳登录并保留 returnTo，403 不渲染任何资源数据，404 显示不存在，
 * 409 要求重新读取资源，其余按通用失败处理。
 */
export type PageFault =
  | { kind: "unauthorized"; code: string; message: string }
  | { kind: "forbidden"; code: string; message: string }
  | { kind: "not_found"; code: string; message: string }
  | { kind: "conflict"; code: string; message: string }
  | { kind: "failed"; code: string; message: string };

export function toPageFault(cause: unknown): PageFault {
  if (cause instanceof ApiError) {
    const shared = { code: cause.code, message: cause.message };
    if (cause.status === 401) return { kind: "unauthorized", ...shared };
    if (cause.status === 403) return { kind: "forbidden", ...shared };
    if (cause.status === 404) return { kind: "not_found", ...shared };
    if (cause.status === 409) return { kind: "conflict", ...shared };
    return { kind: "failed", ...shared };
  }
  return {
    kind: "failed",
    code: "NETWORK_UNREACHABLE",
    message: "无法连接后端服务，请确认 FastAPI 已启动后重试。",
  };
}

export function loginHref(returnTo?: string) {
  if (!returnTo || !returnTo.startsWith("/")) return "/login";
  return `/login?returnTo=${encodeURIComponent(returnTo)}`;
}
