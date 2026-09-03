/**
 * Connection status derivation for an evaluation set.
 *
 * Pure function over the masked credential list; no extra persisted state.
 */

import type { components } from "@/lib/api/generated";

export type SceneCredentialStatus = components["schemas"]["SceneCredentialStatusView"];

export type ConnectionStatus =
  | "unsigned" // no credential ever issued
  | "issued" // at least one active, none used yet
  | "connected" // at least one active has been used
  | "disabled"; // credentials exist but none active

export function deriveConnectionStatus(credentials: SceneCredentialStatus[]): ConnectionStatus {
  if (credentials.length === 0) return "unsigned";
  const active = credentials.filter((c) => c.status === "active");
  if (active.length === 0) return "disabled";
  return active.some((c) => c.last_used_at != null) ? "connected" : "issued";
}

export const CONNECTION_STATUS_LABEL: Record<ConnectionStatus, string> = {
  unsigned: "未签发",
  issued: "已签发待验证",
  connected: "已连接",
  disabled: "已停用",
};

