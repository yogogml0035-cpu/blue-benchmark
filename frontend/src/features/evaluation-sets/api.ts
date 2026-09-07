/**
 * The single API entry point for evaluation sets (scenes) and their upload
 * credentials. Components never call fetch directly; the shared request()
 * wrapper handles transport and maps backend errors to ApiError.
 *
 * Secret lifetime: each scene holds exactly one active credential (1:1
 * model). createOrReplaceCredential returns the plaintext once for handoff
 * convenience; the plaintext is also persisted server-side and can be
 * fetched again through revealCredential (eye icon). Callers keep plaintext
 * in transient component state only — never persist it client-side.
 */

import { request } from "@/lib/api/client";
import type { components } from "@/lib/api/generated";

export type SceneView = components["schemas"]["SceneView"];
export type SceneListResponse = components["schemas"]["SceneListResponse"];
export type SceneStatusResponse = components["schemas"]["SceneStatusResponse"];
export type SceneCreateRequest = components["schemas"]["SceneCreateRequest"];
export type SceneUpdateRequest = components["schemas"]["SceneUpdateRequest"];
export type SceneCredentialIssuedView = components["schemas"]["SceneCredentialIssuedView"];
export type SceneCredentialStatusView = components["schemas"]["SceneCredentialStatusView"];
export type SceneCredentialPlaintextView = components["schemas"]["SceneCredentialPlaintextView"];

export function listScenes(signal?: AbortSignal): Promise<SceneListResponse> {
  return request<SceneListResponse>("/api/scenes", { signal });
}

export function getSceneStatus(sceneId: string, signal?: AbortSignal): Promise<SceneStatusResponse> {
  return request<SceneStatusResponse>(`/api/scenes/${encodeURIComponent(sceneId)}`, { signal });
}

export function createScene(payload: SceneCreateRequest, signal?: AbortSignal): Promise<SceneView> {
  return request<SceneView>("/api/scenes", { method: "POST", body: payload, signal });
}

export function updateScene(
  sceneId: string,
  payload: SceneUpdateRequest,
  signal?: AbortSignal,
): Promise<SceneView> {
  return request<SceneView>(`/api/scenes/${encodeURIComponent(sceneId)}`, {
    method: "PATCH",
    body: payload,
    signal,
  });
}

export function deleteScene(sceneId: string, signal?: AbortSignal): Promise<void> {
  return request<void>(`/api/scenes/${encodeURIComponent(sceneId)}`, { method: "DELETE", signal });
}

export function createOrReplaceCredential(
  sceneId: string,
  signal?: AbortSignal,
): Promise<SceneCredentialIssuedView> {
  return request<SceneCredentialIssuedView>(
    `/api/scenes/${encodeURIComponent(sceneId)}/credentials`,
    { method: "POST", signal },
  );
}

export function revealCredential(
  sceneId: string,
  signal?: AbortSignal,
): Promise<SceneCredentialPlaintextView> {
  return request<SceneCredentialPlaintextView>(
    `/api/scenes/${encodeURIComponent(sceneId)}/credential`,
    { signal },
  );
}

export function revokeCredential(
  sceneId: string,
  credentialId: string,
  signal?: AbortSignal,
): Promise<SceneCredentialStatusView> {
  return request<SceneCredentialStatusView>(
    `/api/scenes/${encodeURIComponent(sceneId)}/credentials/${encodeURIComponent(credentialId)}`,
    { method: "DELETE", signal },
  );
}
