/**
 * Connection status derivation for an evaluation set.
 *
 * Pure function over the single current credential (1:1 model); no extra
 * persisted state. Revoked or replaced credentials never appear in the status
 * response, so there is no separate disabled state — a scene whose credential
 * was revoked simply reads as unsigned again.
 */

import type { components } from "@/lib/api/generated";

export type SceneCredentialStatus = components["schemas"]["SceneCredentialStatusView"];

export type ConnectionStatus =
  | "unsigned" // no active credential
  | "issued" // credential active but never used
  | "connected"; // credential active and used at least once

export function deriveConnectionStatus(
  credential: SceneCredentialStatus | null,
): ConnectionStatus {
  if (credential === null || credential.status !== "active") return "unsigned";
  return credential.last_used_at != null ? "connected" : "issued";
}

export const CONNECTION_STATUS_LABEL: Record<ConnectionStatus, string> = {
  unsigned: "未签发",
  issued: "已签发待验证",
  connected: "已连接",
};
