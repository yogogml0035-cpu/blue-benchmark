import { apiFetch } from "@/src/lib/api/client";
import type { components } from "@/src/lib/api/generated";

export type StudioProjection = components["schemas"]["StudioProjection"];
export type UploadBatch = components["schemas"]["UploadBatch"];
export type UploadBatchResponse = components["schemas"]["UploadBatchResponse"];
export type EvidenceFileSummary = components["schemas"]["EvidenceFileSummary"];
export type TaskPackageSummary = components["schemas"]["TaskPackageSummary"];
export type TaskPackageListResponse = components["schemas"]["TaskPackageListResponse"];
export type TaskPackageWorkspaceListResponse = components["schemas"]["TaskPackageWorkspaceListResponse"];
export type TaskPackageResponse = components["schemas"]["TaskPackageResponse"];
export type TaskGroupInput = components["schemas"]["TaskGroupInput"];
export type CoCreationSessionView = components["schemas"]["CoCreationSessionView"];
export type CoCreationSessionResponse = components["schemas"]["CoCreationSessionResponse"];
export type WorkingSetDraftView = components["schemas"]["WorkingSetDraftView"];
export type WorkingSetDraftResponse = components["schemas"]["WorkingSetDraftResponse"];
export type VersionSummary = components["schemas"]["VersionSummary"];
export type VersionListResponse = components["schemas"]["VersionListResponse"];
export type ManifestResponse = components["schemas"]["ManifestResponse"];
export type CoverageSnapshotView = components["schemas"]["CoverageSnapshotView"];
export type DraftMemberView = components["schemas"]["DraftMemberView"];
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

export function listTaskPackages(workspaceId: string, batchId: string) {
  return apiFetch<TaskPackageListResponse>(
    `${studioBase(workspaceId)}/upload-batches/${batchId}/task-packages`,
  );
}

export function listWorkspaceTaskPackages(workspaceId: string) {
  return apiFetch<TaskPackageWorkspaceListResponse>(
    `${studioBase(workspaceId)}/task-packages`,
  );
}

export function confirmTaskGroups(
  workspaceId: string,
  batchId: string,
  input: { commandId: string; batchRevision: number; groups: TaskGroupInput[] },
) {
  return apiFetch<TaskPackageListResponse>(
    `${studioBase(workspaceId)}/upload-batches/${batchId}/task-groups/confirmation`,
    {
      method: "POST",
      body: JSON.stringify({
        command_id: input.commandId,
        batch_revision: input.batchRevision,
        groups: input.groups,
      }),
    },
  );
}

export function getTaskPackage(workspaceId: string, taskPackageId: string) {
  return apiFetch<TaskPackageResponse>(`${studioBase(workspaceId)}/task-packages/${taskPackageId}`);
}

export function startCoCreation(
  workspaceId: string,
  taskPackageId: string,
  input: {
    commandId: string;
    kind: "scenario_contract" | "task_judgment";
    taskPackageRevision: number;
    initializationOnly?: boolean;
  },
) {
  return apiFetch<CoCreationSessionResponse>(
    `${studioBase(workspaceId)}/task-packages/${taskPackageId}/co-creation`,
    {
      method: "POST",
      body: JSON.stringify({
        command_id: input.commandId,
        kind: input.kind,
        task_package_revision: input.taskPackageRevision,
        initialization_only: input.initializationOnly ?? false,
      }),
    },
  );
}

export function getCoCreationSession(workspaceId: string, sessionId: string) {
  return apiFetch<CoCreationSessionResponse>(
    `${studioBase(workspaceId)}/co-creation/${sessionId}`,
  );
}

export function answerCoCreation(
  workspaceId: string,
  sessionId: string,
  input: { commandId: string; questionId: string; answer: string; businessRevision: number },
) {
  return apiFetch<CoCreationSessionResponse>(
    `${studioBase(workspaceId)}/co-creation/${sessionId}/answers`,
    {
      method: "POST",
      body: JSON.stringify({
        command_id: input.commandId,
        question_id: input.questionId,
        answer: input.answer,
        business_revision: input.businessRevision,
      }),
    },
  );
}

export function retryCoCreation(
  workspaceId: string,
  sessionId: string,
  input: { commandId: string; businessRevision: number },
) {
  return apiFetch<CoCreationSessionResponse>(
    `${studioBase(workspaceId)}/co-creation/${sessionId}/retry`,
    {
      method: "POST",
      body: JSON.stringify({
        command_id: input.commandId,
        business_revision: input.businessRevision,
      }),
    },
  );
}

export function resetCoCreation(
  workspaceId: string,
  sessionId: string,
  input: { commandId: string; reason: string },
) {
  return apiFetch<CoCreationSessionResponse>(
    `${studioBase(workspaceId)}/co-creation/${sessionId}/continuity-reset`,
    {
      method: "POST",
      body: JSON.stringify({
        command_id: input.commandId,
        reason: input.reason,
      }),
    },
  );
}

export function confirmContract(
  workspaceId: string,
  sessionId: string,
  input: { commandId: string; businessRevision: number },
) {
  return apiFetch<CoCreationSessionResponse>(
    `${studioBase(workspaceId)}/co-creation/${sessionId}/contract-confirmation`,
    {
      method: "POST",
      body: JSON.stringify({
        command_id: input.commandId,
        business_revision: input.businessRevision,
      }),
    },
  );
}

export function confirmJudgment(
  workspaceId: string,
  sessionId: string,
  input: { commandId: string; businessRevision: number },
) {
  return apiFetch<CoCreationSessionResponse>(
    `${studioBase(workspaceId)}/co-creation/${sessionId}/judgment-confirmation`,
    {
      method: "POST",
      body: JSON.stringify({
        command_id: input.commandId,
        business_revision: input.businessRevision,
      }),
    },
  );
}

export function createWorkingDraft(workspaceId: string, input: { commandId: string }) {
  return apiFetch<WorkingSetDraftResponse>(
    `${studioBase(workspaceId)}/evaluation-sets/drafts`,
    {
      method: "POST",
      body: JSON.stringify({ command_id: input.commandId }),
    },
  );
}

export function getWorkingDraft(workspaceId: string, draftId: string) {
  return apiFetch<WorkingSetDraftResponse>(
    `${studioBase(workspaceId)}/evaluation-sets/drafts/${draftId}`,
  );
}

export function discardWorkingDraft(
  workspaceId: string,
  draftId: string,
  input: { commandId: string; draftRevision: number },
) {
  return apiFetch<WorkingSetDraftResponse>(
    `${studioBase(workspaceId)}/evaluation-sets/drafts/${draftId}/discard`,
    {
      method: "POST",
      body: JSON.stringify({
        command_id: input.commandId,
        draft_revision: input.draftRevision,
      }),
    },
  );
}

export function mutateDraftMember(
  workspaceId: string,
  draftId: string,
  input: {
    commandId: string;
    draftRevision: number;
    taskPackageId: string;
    taskPackageRevision: number;
    action: "include" | "remove";
  },
) {
  return apiFetch<WorkingSetDraftResponse>(
    `${studioBase(workspaceId)}/evaluation-sets/drafts/${draftId}/members`,
    {
      method: "POST",
      body: JSON.stringify({
        command_id: input.commandId,
        draft_revision: input.draftRevision,
        task_package_id: input.taskPackageId,
        task_package_revision: input.taskPackageRevision,
        action: input.action,
      }),
    },
  );
}

export function decideImpactReview(
  workspaceId: string,
  draftId: string,
  taskPackageId: string,
  input: { commandId: string; draftRevision: number; decision: "reviewed" | "confirm_no_conflict"; note?: string | null },
) {
  return apiFetch<WorkingSetDraftResponse>(
    `${studioBase(workspaceId)}/evaluation-sets/drafts/${draftId}/impact-reviews/${taskPackageId}`,
    {
      method: "POST",
      body: JSON.stringify({
        command_id: input.commandId,
        draft_revision: input.draftRevision,
        decision: input.decision,
        note: input.note ?? null,
      }),
    },
  );
}

export function confirmImpactBatch(
  workspaceId: string,
  draftId: string,
  input: { commandId: string; draftRevision: number; note?: string | null },
) {
  return apiFetch<WorkingSetDraftResponse>(
    `${studioBase(workspaceId)}/evaluation-sets/drafts/${draftId}/impact-reviews/confirm-no-conflict`,
    {
      method: "POST",
      body: JSON.stringify({
        command_id: input.commandId,
        draft_revision: input.draftRevision,
        note: input.note ?? null,
      }),
    },
  );
}

export function requestCoverageReview(
  workspaceId: string,
  draftId: string,
  input: { commandId: string; draftRevision: number },
) {
  return apiFetch<WorkingSetDraftResponse>(
    `${studioBase(workspaceId)}/evaluation-sets/drafts/${draftId}/coverage-review`,
    {
      method: "POST",
      body: JSON.stringify({
        command_id: input.commandId,
        draft_revision: input.draftRevision,
      }),
    },
  );
}

export function confirmCoverage(
  workspaceId: string,
  draftId: string,
  input: { commandId: string; draftRevision: number; confirmed: boolean; note?: string | null },
) {
  return apiFetch<WorkingSetDraftResponse>(
    `${studioBase(workspaceId)}/evaluation-sets/drafts/${draftId}/coverage-confirmation`,
    {
      method: "POST",
      body: JSON.stringify({
        command_id: input.commandId,
        draft_revision: input.draftRevision,
        confirmed: input.confirmed,
        note: input.note ?? null,
      }),
    },
  );
}

export function freezeDraft(
  workspaceId: string,
  draftId: string,
  input: {
    commandId: string;
    draftRevision: number;
    coverageRiskConfirmed?: boolean;
    riskConfirmationNote?: string | null;
  },
) {
  return apiFetch<{ draft: WorkingSetDraftView; operation_id: string }>(
    `${studioBase(workspaceId)}/evaluation-sets/drafts/${draftId}/freeze`,
    {
      method: "POST",
      body: JSON.stringify({
        command_id: input.commandId,
        draft_revision: input.draftRevision,
        coverage_risk_confirmed: input.coverageRiskConfirmed ?? false,
        risk_confirmation_note: input.riskConfirmationNote ?? null,
      }),
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
