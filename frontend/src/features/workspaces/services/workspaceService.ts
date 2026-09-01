import { apiFetch } from "@/src/lib/api/client";
import type { components } from "@/src/lib/api/generated";

export type Workspace = components["schemas"]["Workspace"];
type WorkspaceCreateRequest = components["schemas"]["WorkspaceCreateRequest"];

export function listWorkspaces() {
  return apiFetch<{ items: Workspace[] }>("/api/workspaces");
}

export function createWorkspace(input: WorkspaceCreateRequest) {
  return apiFetch<{ workspace: Workspace }>("/api/workspaces", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function getWorkspace(workspaceId: string) {
  return apiFetch<{ workspace: Workspace }>(`/api/workspaces/${workspaceId}`);
}

export type AuthoringConnectionStatusResponse = components["schemas"]["ExternalConnectionStatusResponse"];
export type AuthoringConnectionCreateResponse = components["schemas"]["ExternalConnectionCreateResponse"];

export function getAuthoringConnection(workspaceId: string) {
  return apiFetch<AuthoringConnectionStatusResponse>(`/api/workspaces/${workspaceId}/authoring-connection`);
}

export function createAuthoringConnection(workspaceId: string, clientName = "本地 Agent") {
  return apiFetch<AuthoringConnectionCreateResponse>(`/api/workspaces/${workspaceId}/authoring-connections`, {
    method: "POST",
    body: JSON.stringify({ client_name: clientName }),
  });
}

export function revokeAuthoringConnection(workspaceId: string, connectionId: string) {
  return apiFetch<AuthoringConnectionStatusResponse>(
    `/api/workspaces/${workspaceId}/authoring-connections/${connectionId}`,
    { method: "DELETE" },
  );
}
