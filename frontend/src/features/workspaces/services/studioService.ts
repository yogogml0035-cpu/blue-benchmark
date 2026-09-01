import { apiFetch } from "@/src/lib/api/client";
import type { components } from "@/src/lib/api/generated";

export type StudioProjection = components["schemas"]["StudioProjection"];
export type UploadBatch = components["schemas"]["UploadBatch"];
export type UploadBatchResponse = components["schemas"]["UploadBatchResponse"];
export type EvidenceFileSummary = components["schemas"]["EvidenceFileSummary"];
export type VersionSummary = components["schemas"]["VersionSummary"];
export type VersionListResponse = components["schemas"]["VersionListResponse"];
export type ManifestResponse = components["schemas"]["ManifestResponse"];
export type FileDispositionRequest = components["schemas"]["FileDispositionRequest"];

function studioBase(workspaceId: string) {
  return `/api/workspaces/${workspaceId}`;
}

export function getStudioProjection(workspaceId: string, batchId?: string | null) {
  const query = batchId ? `?batch_id=${encodeURIComponent(batchId)}` : "";
  return apiFetch<StudioProjection>(`${studioBase(workspaceId)}/upload-batches/studio${query}`);
}

export function createUploadBatch(
  workspaceId: string,
  input: { title: string; taskDescription?: string | null; files: File[]; commandId: string },
) {
  const form = new FormData();
  form.set("title", input.title);
  if (input.taskDescription) form.set("task_description", input.taskDescription);
  form.set("command_id", input.commandId);
  for (const file of input.files) {
    form.append("files", file);
  }
  return apiFetch<UploadBatchResponse>(`${studioBase(workspaceId)}/upload-batches`, {
    method: "POST",
    body: form,
  });
}

export function getUploadBatch(workspaceId: string, batchId: string) {
  return apiFetch<{ batch: UploadBatch }>(`${studioBase(workspaceId)}/upload-batches/${batchId}`);
}

export function retryBatchAnalysis(workspaceId: string, batchId: string, input: { commandId: string; batchRevision: number }) {
  return apiFetch<UploadBatchResponse>(`${studioBase(workspaceId)}/upload-batches/${batchId}/retry`, {
    method: "POST",
    body: JSON.stringify({ command_id: input.commandId, batch_revision: input.batchRevision }),
  });
}

export function updateFileDisposition(
  workspaceId: string,
  batchId: string,
  fileId: string,
  input: FileDispositionRequest,
) {
  return apiFetch<UploadBatchResponse>(
    `${studioBase(workspaceId)}/upload-batches/${batchId}/files/${fileId}/disposition`,
    {
      method: "PATCH",
      body: JSON.stringify(input),
    },
  );
}

export function listVersions(workspaceId: string) {
  return apiFetch<VersionListResponse>(`${studioBase(workspaceId)}/evaluation-sets/versions`);
}

export function getManifest(workspaceId: string, versionId: string) {
  return apiFetch<ManifestResponse>(
    `${studioBase(workspaceId)}/evaluation-sets/versions/${versionId}/manifest`,
  );
}

export function getDownloadUrl(workspaceId: string, versionId: string) {
  return `${studioBase(workspaceId)}/evaluation-sets/versions/${versionId}/download`;
}
