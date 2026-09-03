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
export type CriteriaPatchRequest = components["schemas"]["CriteriaPatchRequest"];
export type QuestionSaveRegenerateRequest = components["schemas"]["QuestionSaveRegenerateRequest"];
export type QuestionDeleteRequest = components["schemas"]["QuestionDeleteRequest"];
export type QuestionTitleRequest = components["schemas"]["QuestionTitleRequest"];
export type QuestionCommandRequest = components["schemas"]["QuestionCommandRequest"];
export type OperationAcceptedResponse = components["schemas"]["OperationAcceptedResponse"];

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

export function saveRegenerate(
  questionId: string,
  payload: QuestionSaveRegenerateRequest,
  signal?: AbortSignal,
): Promise<OperationAcceptedResponse> {
  return request<OperationAcceptedResponse>(
    `/api/questions/${encodeURIComponent(questionId)}/save-regenerate`,
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
): Promise<void> {
  return request<void>(`/api/questions/${encodeURIComponent(questionId)}`, {
    method: "DELETE",
    body: payload,
    signal,
  });
}
