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

