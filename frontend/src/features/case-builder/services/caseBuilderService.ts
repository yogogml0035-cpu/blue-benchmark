import { apiFetch } from "@/src/lib/api/client";
import type { components } from "@/src/lib/api/generated";

export type CaseDetail = components["schemas"]["CaseDetail"];
export type Case = components["schemas"]["Case"];
export type DraftContent = components["schemas"]["DraftContent"];
type AnswerRequest = components["schemas"]["AnswerRequest"];
type ConfirmationRequest = components["schemas"]["ConfirmationRequest"];

function casePath(workspaceId: string, caseId?: string) {
  const base = `/api/workspaces/${workspaceId}/cases`;
  return caseId ? `${base}/${caseId}` : base;
}

export function createCase(
  workspaceId: string,
  input: { title: string; taskDescription?: string; file: File },
) {
  const form = new FormData();
  form.set("title", input.title);
  if (input.taskDescription) form.set("task_description", input.taskDescription);
  form.set("file", input.file);
  return apiFetch<CaseDetail>(casePath(workspaceId), { method: "POST", body: form });
}

export function getCase(workspaceId: string, caseId: string) {
  return apiFetch<CaseDetail>(casePath(workspaceId, caseId));
}

export function generateDraft(workspaceId: string, caseId: string) {
  return apiFetch<CaseDetail>(`${casePath(workspaceId, caseId)}/draft-generation`, {
    method: "POST",
  });
}

export function answerQuestion(
  workspaceId: string,
  caseId: string,
  input: AnswerRequest,
) {
  return apiFetch<CaseDetail>(`${casePath(workspaceId, caseId)}/answers`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function confirmCase(
  workspaceId: string,
  caseId: string,
  input: ConfirmationRequest,
) {
  return apiFetch<CaseDetail>(`${casePath(workspaceId, caseId)}/confirmation`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

