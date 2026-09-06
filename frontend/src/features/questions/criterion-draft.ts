/**
 * Criterion draft model for the review workbench (complete contract).
 *
 * A draft mirrors the backend criterion 1:1 — criterion text, ANY integer
 * pass_score 0-10, sparse score anchors, and the two bases (dimension basis
 * and pass-score basis with teacher-explicit / AI-inferred claims) — plus two
 * non-persistent fields:
 *   - selected: whether the teacher keeps this criterion in the final list
 *   - source: "ai" (server-generated candidate) or "manual" (teacher-added)
 *
 * Editing semantics (from the backend contract):
 *   - anchors are explanatory, NEVER a whitelist: the teacher may save any
 *     integer even when no anchor describes it, and nothing auto-fills or
 *     rewrites anchors/bases on a score change;
 *   - when pass_score_basis.explained_score differs from the current
 *     pass_score, the draft is "stale-explained": the UI flags it for review
 *     and the teacher decides, the app never rewrites silently;
 *   - manual criteria carry explicitly empty auxiliaries ([] / null), which
 *     is a first-class saved state, not a missing-field fallback.
 *
 * Projection rules:
 *   - criteria_confirmed=false -> server criteria are AI candidates, all unselected
 *   - criteria_confirmed=true  -> server criteria are the authoritative list, all selected
 * Saving projects only the selected drafts to the full payload shape.
 */

import type {
  CriterionBasisView,
  CriterionView,
  PassScoreBasisView,
  QuestionDetailResponse,
  ScoreAnchorView,
} from "./api";

export type CriterionSource = "ai" | "manual";

export interface CriterionDraft {
  id: string;
  criterion: string;
  pass_score: number;
  score_anchors: ScoreAnchorView[];
  criterion_basis: CriterionBasisView | null;
  pass_score_basis: PassScoreBasisView | null;
  selected: boolean;
  source: CriterionSource;
}

export const MIN_CRITERIA = 1;
export const MAX_CRITERIA = 20;
export const MAX_PASS_SCORE = 10;
export const MAX_ANCHORS = 6;
// Mirrors the backend rubric_rules.MIN_CRITERION_LENGTH so obviously-too-short
// criteria are caught before a round trip.
export const MIN_CRITERION_LENGTH = 8;

function cloneAnchors(anchors: ScoreAnchorView[] | undefined | null): ScoreAnchorView[] {
  return (anchors ?? []).map((a) => ({ score: a.score, description: a.description }));
}

function cloneBasis(basis: CriterionBasisView | null | undefined): CriterionBasisView | null {
  if (!basis) return null;
  return {
    explanation: basis.explanation,
    claims: basis.claims.map((c) => ({
      claim: c.claim,
      kind: c.kind === "teacher_explicit" ? ("teacher_explicit" as const) : ("ai_inferred" as const),
      citation: c.citation ? { ...c.citation } : null,
    })),
  };
}

function clonePassBasis(basis: PassScoreBasisView | null | undefined): PassScoreBasisView | null {
  if (!basis) return null;
  return {
    explained_score: basis.explained_score,
    explanation: basis.explanation,
    claims: basis.claims.map((c) => ({
      claim: c.claim,
      kind: c.kind === "teacher_explicit" ? ("teacher_explicit" as const) : ("ai_inferred" as const),
      citation: c.citation ? { ...c.citation } : null,
    })),
  };
}

/** Build the initial drafts from a question detail response. */
export function draftsFromDetail(detail: QuestionDetailResponse): CriterionDraft[] {
  const criteria = detail.criteria ?? [];
  const selected = detail.criteria_confirmed;
  return criteria.map((c) => ({
    id: c.id,
    criterion: c.criterion,
    pass_score: c.pass_score,
    score_anchors: cloneAnchors(c.score_anchors),
    criterion_basis: cloneBasis(c.criterion_basis),
    pass_score_basis: clonePassBasis(c.pass_score_basis),
    selected,
    source: "ai" as CriterionSource,
  }));
}

/** Project the selected drafts into the PATCH /criteria payload items. */
export function selectedToPayload(drafts: CriterionDraft[]): CriterionView[] {
  return drafts
    .filter((d) => d.selected)
    .map((d) => ({
      id: d.id,
      criterion: d.criterion,
      pass_score: d.pass_score,
      score_anchors: cloneAnchors(d.score_anchors),
      criterion_basis: cloneBasis(d.criterion_basis),
      pass_score_basis: clonePassBasis(d.pass_score_basis),
    }));
}

/** Create a fresh manual draft with explicitly empty auxiliary content. */
export function newManualDraft(existingIds: Set<string>): CriterionDraft {
  let id = `manual-${crypto.randomUUID()}`;
  // crypto.randomUUID is already unique; guard defensively against collisions.
  while (existingIds.has(id)) {
    id = `manual-${crypto.randomUUID()}`;
  }
  return {
    id,
    criterion: "",
    pass_score: 5,
    score_anchors: [],
    criterion_basis: null,
    pass_score_basis: null,
    selected: true,
    source: "manual",
  };
}

/**
 * A draft whose pass-score basis explains a DIFFERENT integer than the
 * current pass score. The content is kept as-is; the teacher gets a visible
 * review prompt instead of a silent rewrite.
 */
export function hasStaleExplanation(draft: CriterionDraft): boolean {
  return (
    draft.pass_score_basis !== null &&
    draft.pass_score_basis.explained_score !== draft.pass_score
  );
}

export interface CriterionValidationError {
  code:
    | "TOO_FEW"
    | "TOO_MANY"
    | "DUPLICATE_ID"
    | "EMPTY_CRITERION"
    | "SHORT_CRITERION"
    | "BAD_SCORE"
    | "TOO_MANY_ANCHORS"
    | "DUPLICATE_ANCHOR"
    | "BAD_ANCHOR_SCORE"
    | "EMPTY_ANCHOR_DESCRIPTION";
  message: string;
}

/** Validate the selected drafts against the edit contract. */
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
    const trimmed = d.criterion.trim();
    if (!trimmed) {
      return { code: "EMPTY_CRITERION", message: "评分标准不能为空白。" };
    }
    if (trimmed.length < MIN_CRITERION_LENGTH) {
      return {
        code: "SHORT_CRITERION",
        message: `评分标准过短（至少 ${MIN_CRITERION_LENGTH} 个字符），请写明判断对象与合格表现。`,
      };
    }
    if (!Number.isInteger(d.pass_score) || d.pass_score < 0 || d.pass_score > MAX_PASS_SCORE) {
      return { code: "BAD_SCORE", message: "通过分必须是 0–10 的整数。" };
    }
    // NOTE: deliberately NO check that pass_score appears in score_anchors —
    // anchors are explanations, not a whitelist.
    if (d.score_anchors.length > MAX_ANCHORS) {
      return { code: "TOO_MANY_ANCHORS", message: `每个维度最多 ${MAX_ANCHORS} 个分数锚点。` };
    }
    const anchorScores = new Set<number>();
    for (const anchor of d.score_anchors) {
      if (!Number.isInteger(anchor.score) || anchor.score < 0 || anchor.score > MAX_PASS_SCORE) {
        return { code: "BAD_ANCHOR_SCORE", message: "锚点分数必须是 0–10 的整数。" };
      }
      if (anchorScores.has(anchor.score)) {
        return { code: "DUPLICATE_ANCHOR", message: "同一维度的锚点分数不能重复。" };
      }
      anchorScores.add(anchor.score);
      if (!anchor.description.trim()) {
        return { code: "EMPTY_ANCHOR_DESCRIPTION", message: "锚点表现描述不能为空白。" };
      }
    }
  }
  return null;
}
