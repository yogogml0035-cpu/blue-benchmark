/**
 * The single API entry point for evaluation sets (scenes) and their upload
 * credentials. Components never call fetch directly; the shared request()
 * wrapper handles transport and maps backend errors to ApiError.
 *
 * Secret lifetime: issue/rotate return the one-time plaintext token. Callers
 * must keep it in transient component state only — never persist it.
 */

import { request } from "@/lib/api/client";
import type { components } from "@/lib/api/generated";

export type SceneView = components["schemas"]["SceneView"];
export type SceneListResponse = components["schemas"]["SceneListResponse"];
export type SceneStatusResponse = components["schemas"]["SceneStatusResponse"];
export type SceneCreateRequest = components["schemas"]["SceneCreateRequest"];
export type SceneUpdateRequest = components["schemas"]["SceneUpdateRequest"];
export type SceneCredentialIssueRequest = components["schemas"]["SceneCredentialIssueRequest"];
export type SceneCredentialIssuedView = components["schemas"]["SceneCredentialIssuedView"];
export type SceneCredentialStatusView = components["schemas"]["SceneCredentialStatusView"];

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

export function issueCredential(
  sceneId: string,
  payload: SceneCredentialIssueRequest,
  signal?: AbortSignal,
): Promise<SceneCredentialIssuedView> {
  return request<SceneCredentialIssuedView>(
    `/api/scenes/${encodeURIComponent(sceneId)}/credentials`,
    { method: "POST", body: payload, signal },
  );
}

export function rotateCredentials(
  sceneId: string,
  payload: SceneCredentialIssueRequest,
  signal?: AbortSignal,
): Promise<SceneCredentialIssuedView> {
  return request<SceneCredentialIssuedView>(
    `/api/scenes/${encodeURIComponent(sceneId)}/credentials/rotation`,
    { method: "POST", body: payload, signal },
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
