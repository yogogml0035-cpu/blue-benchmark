import { apiFetch } from "@/src/lib/api/client";
import type { components } from "@/src/lib/api/generated";

type Schemas = components["schemas"];

export type RubricDraft = Schemas["RubricDraftView"];
export type RubricContent = Schemas["RubricContent"];
export type RubricCriterion = Schemas["RubricCriterion"];
export type RubricDraftResponse = Schemas["RubricDraftResponse"];
export type RubricRevisionListResponse = Schemas["RubricRevisionListResponse"];

function base(workspaceId: string) {
  return `/api/workspaces/${workspaceId}/authoring`;
}

export function getRubricForQuestion(workspaceId: string, questionDraftId: string) {
  return apiFetch<RubricDraftResponse>(`${base(workspaceId)}/question-drafts/${questionDraftId}/rubric`);
}

export function startRubric(
  workspaceId: string,
  questionDraftId: string,
  input: Schemas["RubricGenerateRequest"],
) {
  return apiFetch<RubricDraftResponse>(`${base(workspaceId)}/question-drafts/${questionDraftId}/rubric`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function patchRubric(workspaceId: string, rubricId: string, input: Schemas["RubricPatchRequest"]) {
  return apiFetch<RubricDraftResponse>(`${base(workspaceId)}/rubrics/${rubricId}`, {
    method: "PATCH",
    body: JSON.stringify(input),
  });
}

export function confirmRubric(workspaceId: string, rubricId: string, input: Schemas["RubricConfirmationRequest"]) {
  return apiFetch<RubricDraftResponse>(`${base(workspaceId)}/rubrics/${rubricId}/confirmation`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function publishRubric(workspaceId: string, rubricId: string, input: Schemas["RubricPublishRequest"]) {
  return apiFetch<RubricDraftResponse>(`${base(workspaceId)}/rubrics/${rubricId}/publish`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function listRubricRevisions(workspaceId: string, questionDraftId: string) {
  return apiFetch<RubricRevisionListResponse>(`${base(workspaceId)}/question-drafts/${questionDraftId}/revisions`);
}

export function deriveRubricDraft(
  workspaceId: string,
  questionDraftId: string,
  revisionId: string,
  input: Schemas["RubricDeriveRequest"],
) {
  return apiFetch<RubricDraftResponse>(
    `${base(workspaceId)}/question-drafts/${questionDraftId}/revisions/${revisionId}/derive-draft`,
    { method: "POST", body: JSON.stringify(input) },
  );
}
