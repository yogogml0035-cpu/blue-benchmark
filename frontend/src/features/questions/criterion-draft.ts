/**
 * Criterion draft model for the review workbench.
 *
 * A draft adds two non-persistent fields on top of the backend criterion:
 *   - selected: whether the teacher keeps this criterion in the final list
 *   - source: "ai" (server-generated candidate) or "manual" (teacher-added)
 *
 * Projection rules (from the backend contract):
 *   - criteria_confirmed=false  -> server criteria are AI candidates, all unselected
 *   - criteria_confirmed=true   -> server criteria are the authoritative list, all selected
 * Saving projects only the selected drafts to {id, criterion, pass_score}.
 */

import type { CriterionView, QuestionDetailResponse } from "./api";

export type CriterionSource = "ai" | "manual";

export interface CriterionDraft {
  id: string;
  criterion: string;
  pass_score: number;
  selected: boolean;
  source: CriterionSource;
}

export const MIN_CRITERIA = 1;
export const MAX_CRITERIA = 20;
export const MAX_PASS_SCORE = 10;

/** Build the initial drafts from a question detail response. */
export function draftsFromDetail(detail: QuestionDetailResponse): CriterionDraft[] {
  const criteria = detail.criteria ?? [];
  const selected = detail.criteria_confirmed;
  return criteria.map((c) => ({
    id: c.id,
    criterion: c.criterion,
    pass_score: c.pass_score,
    selected,
    source: "ai",
  }));
}

/** Project the selected drafts into the PATCH /criteria payload items. */
export function selectedToPayload(drafts: CriterionDraft[]): CriterionView[] {
  return drafts
    .filter((d) => d.selected)
    .map((d) => ({ id: d.id, criterion: d.criterion, pass_score: d.pass_score }));
}

/** Create a fresh manual draft with a unique id. */
export function newManualDraft(existingIds: Set<string>): CriterionDraft {
  let id = `manual-${crypto.randomUUID()}`;
  // crypto.randomUUID is already unique; guard defensively against collisions.
  while (existingIds.has(id)) {
    id = `manual-${crypto.randomUUID()}`;
  }
  return { id, criterion: "", pass_score: 5, selected: true, source: "manual" };
}

export interface CriterionValidationError {
  code: "TOO_FEW" | "TOO_MANY" | "DUPLICATE_ID" | "EMPTY_CRITERION" | "BAD_SCORE";
  message: string;
}

/** Validate the selected drafts against the 1–20 / id / criterion / score rules. */
export function validateSelected(drafts: CriterionDraft[]): CriterionValidationError | null {
  const selected = drafts.filter((d) => d.selected);
  if (selected.length < MIN_CRITERIA) {
    return { code: "TOO_FEW", message: `至少选择 ${MIN_CRITERIA} 个评分维度。` };
  }
  if (selected.length > MAX_CRITERIA) {
    return { code: "TOO_MANY", message: `最多选择 ${MAX_CRITERIA} 个评分维度。` };
  }
  const ids = new Set<string>();
  for (const d of selected) {
    if (ids.has(d.id)) {
      return { code: "DUPLICATE_ID", message: "评分维度 id 必须唯一。" };
    }
    ids.add(d.id);
    if (!d.criterion.trim()) {
      return { code: "EMPTY_CRITERION", message: "评分标准不能为空白。" };
    }
    if (!Number.isInteger(d.pass_score) || d.pass_score < 0 || d.pass_score > MAX_PASS_SCORE) {
      return { code: "BAD_SCORE", message: "通过分必须是 0–10 的整数。" };
    }
  }
  return null;
}
