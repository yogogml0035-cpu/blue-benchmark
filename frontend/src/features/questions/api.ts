/**
 * The single API entry point for the question library (list + workbench).
 * All calls go through the shared request() wrapper; components never fetch
 * directly and never parse machine codes themselves.
 */

import { request } from "@/lib/api/client";
import type { components } from "@/lib/api/generated";

export type QuestionListItem = components["schemas"]["QuestionListItem"];
export type QuestionLibraryResponse = components["schemas"]["QuestionLibraryResponse"];
export type QuestionDetailResponse = components["schemas"]["QuestionDetailResponse"];
export type QuestionStatus = components["schemas"]["QuestionStatus"];
export type NextAction = components["schemas"]["NextAction"];
export type CriterionView = components["schemas"]["CriterionView"];
export type ScoreAnchorView = components["schemas"]["ScoreAnchorView"];
export type CriterionBasisView = components["schemas"]["CriterionBasisView"];
export type PassScoreBasisView = components["schemas"]["PassScoreBasisView"];
export type BasisClaimView = components["schemas"]["BasisClaimView"];
export type SourceCitationView = components["schemas"]["SourceCitationView"];
export type CriteriaPatchRequest = components["schemas"]["CriteriaPatchRequest"];
export type QuestionMaterialsPatchRequest = components["schemas"]["QuestionMaterialsPatchRequest"];
export type CriterionPatchRequest = components["schemas"]["CriterionPatchRequest"];
export type QuestionDeleteRequest = components["schemas"]["QuestionDeleteRequest"];
export type QuestionTitleRequest = components["schemas"]["QuestionTitleRequest"];
export type QuestionCommandRequest = components["schemas"]["QuestionCommandRequest"];
export type OperationAcceptedResponse = components["schemas"]["OperationAcceptedResponse"];
export type DeleteAcceptedResponse = components["schemas"]["DeleteAcceptedResponse"];
export type DeleteStateView = components["schemas"]["DeleteStateView"];
export type RunEventView = components["schemas"]["RunEventView"];
export type RunEventsResponse = components["schemas"]["RunEventsResponse"];

export function listQuestions(
  sceneId: string,
  opts: { status?: QuestionStatus; signal?: AbortSignal } = {},
): Promise<QuestionLibraryResponse> {
  const params = new URLSearchParams({ scene_id: sceneId });
  if (opts.status) params.set("status", opts.status);
  return request<QuestionLibraryResponse>(`/api/questions?${params.toString()}`, {
    signal: opts.signal,
  });
}

export function getQuestion(questionId: string, signal?: AbortSignal): Promise<QuestionDetailResponse> {
  return request<QuestionDetailResponse>(`/api/questions/${encodeURIComponent(questionId)}`, { signal });
}

export function updateTitle(
  questionId: string,
  payload: QuestionTitleRequest,
  signal?: AbortSignal,
): Promise<QuestionDetailResponse> {
  return request<QuestionDetailResponse>(
    `/api/questions/${encodeURIComponent(questionId)}/title`,
    { method: "PATCH", body: payload, signal },
  );
}

/**
 * Material autosave: writes text only — never bumps content_revision, never
 * touches criteria, never enqueues generation.
 */
export function updateMaterials(
  questionId: string,
  payload: QuestionMaterialsPatchRequest,
  signal?: AbortSignal,
): Promise<QuestionDetailResponse> {
  return request<QuestionDetailResponse>(
    `/api/questions/${encodeURIComponent(questionId)}/materials`,
    { method: "PATCH", body: payload, signal },
  );
}

/** Field-level criterion autosave; selection/confirmation stay untouched. */
export function patchCriterion(
  questionId: string,
  criterionId: string,
  payload: CriterionPatchRequest,
  signal?: AbortSignal,
): Promise<QuestionDetailResponse> {
  return request<QuestionDetailResponse>(
    `/api/questions/${encodeURIComponent(questionId)}/criteria/${encodeURIComponent(criterionId)}`,
    { method: "PATCH", body: payload, signal },
  );
}

/**
 * Unconditional regeneration of the rubric from the CURRENT saved materials.
 * Wipes all stored criteria (candidates, selection, confirmation).
 */
export function regenerateQuestion(
  questionId: string,
  payload: QuestionCommandRequest,
  signal?: AbortSignal,
): Promise<OperationAcceptedResponse> {
  return request<OperationAcceptedResponse>(
    `/api/questions/${encodeURIComponent(questionId)}/regenerate`,
    { method: "POST", body: payload, signal },
  );
}

export function patchCriteria(
  questionId: string,
  payload: CriteriaPatchRequest,
  signal?: AbortSignal,
): Promise<QuestionDetailResponse> {
  return request<QuestionDetailResponse>(
    `/api/questions/${encodeURIComponent(questionId)}/criteria`,
    { method: "PATCH", body: payload, signal },
  );
}

export function retryGeneration(
  questionId: string,
  payload: QuestionCommandRequest,
  signal?: AbortSignal,
): Promise<OperationAcceptedResponse> {
  return request<OperationAcceptedResponse>(
    `/api/questions/${encodeURIComponent(questionId)}/generation-retry`,
    { method: "POST", body: payload, signal },
  );
}

export function publishQuestion(
  questionId: string,
  payload: QuestionCommandRequest,
  signal?: AbortSignal,
): Promise<QuestionDetailResponse> {
  return request<QuestionDetailResponse>(
    `/api/questions/${encodeURIComponent(questionId)}/publication`,
    { method: "POST", body: payload, signal },
  );
}

export function reviewReopen(
  questionId: string,
  payload: QuestionCommandRequest,
  signal?: AbortSignal,
): Promise<QuestionDetailResponse> {
  return request<QuestionDetailResponse>(
    `/api/questions/${encodeURIComponent(questionId)}/review-reopen`,
    { method: "POST", body: payload, signal },
  );
}

export function deleteQuestion(
  questionId: string,
  payload: QuestionDeleteRequest,
  signal?: AbortSignal,
): Promise<DeleteAcceptedResponse> {
  // 202 = deletion ACCEPTED (freeze + durable cleanup operation), not done.
  // Completion is observed through the detail projection / event stream; the
  // old "response received = deleted" semantics no longer exist.
  return request<DeleteAcceptedResponse>(`/api/questions/${encodeURIComponent(questionId)}`, {
    method: "DELETE",
    body: payload,
    signal,
  });
}

export function getRunEvents(
  questionId: string,
  operationId: string,
  opts: { afterSequence?: number; signal?: AbortSignal } = {},
): Promise<RunEventsResponse> {
  const params = new URLSearchParams();
  if (opts.afterSequence && opts.afterSequence > 0) {
    params.set("after_sequence", String(opts.afterSequence));
  }
  const query = params.toString() ? `?${params.toString()}` : "";
  return request<RunEventsResponse>(
    `/api/questions/${encodeURIComponent(questionId)}/runs/${encodeURIComponent(operationId)}/events${query}`,
    { signal: opts.signal },
  );
}

export function runEventsStreamUrl(questionId: string, operationId: string, afterSequence = 0): string {
  const params = new URLSearchParams();
  if (afterSequence > 0) params.set("after_sequence", String(afterSequence));
  const query = params.toString() ? `?${params.toString()}` : "";
  return `/api/questions/${encodeURIComponent(questionId)}/runs/${encodeURIComponent(operationId)}/events/stream${query}`;
}
