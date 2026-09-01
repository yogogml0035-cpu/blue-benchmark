import { apiFetch } from "@/src/lib/api/client";
import type { components } from "@/src/lib/api/generated";

type Schemas = components["schemas"];

export type HumanSubmissionResponse = Schemas["HumanSubmissionResponse"];
export type HumanSubmission = Schemas["SubmissionView"];
export type QuestionRevision = Schemas["QuestionRevisionView"];
export type HumanScore = Schemas["HumanScoreView"];
export type ScoreCreateRequest = Schemas["ScoreCreateRequest"];
export type SubmissionCreateRequest = Schemas["SubmissionCreateRequest"];

function base(workspaceId: string) {
  return `/api/workspaces/${workspaceId}`;
}
export function createPastedSubmission(
  workspaceId: string,
  questionRevisionId: string,
  input: SubmissionCreateRequest,
) {
  return apiFetch<HumanSubmissionResponse>(
    `${base(workspaceId)}/question-revisions/${questionRevisionId}/submissions`,
    { method: "POST", body: JSON.stringify(input) },
  );
}

export function createUploadedSubmission(
  workspaceId: string,
  questionRevisionId: string,
  commandId: string,
  file: File,
) {
  const body = new FormData();
  body.set("command_id", commandId);
  body.set("file", file);
  return apiFetch<HumanSubmissionResponse>(
    `${base(workspaceId)}/question-revisions/${questionRevisionId}/submissions/upload`,
    { method: "POST", body },
  );
}

export function getSubmission(workspaceId: string, submissionId: string) {
  return apiFetch<HumanSubmissionResponse>(
    `${base(workspaceId)}/submissions/${submissionId}`,
  );
}

export function submitScore(
  workspaceId: string,
  submissionId: string,
  input: ScoreCreateRequest,
) {
  return apiFetch<Schemas["HumanScoreResponse"]>(
    `${base(workspaceId)}/submissions/${submissionId}/scores`,
    { method: "POST", body: JSON.stringify(input) },
  );
}
