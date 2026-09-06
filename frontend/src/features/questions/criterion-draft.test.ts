import { describe, expect, it } from "vitest";
import type { CriterionView, QuestionDetailResponse } from "./api";
import {
  draftsFromDetail,
  hasStaleExplanation,
  newManualDraft,
  selectedToPayload,
  validateSelected,
  type CriterionDraft,
} from "./criterion-draft";

function criterionView(partial: Partial<CriterionView> = {}): CriterionView {
  return {
    id: "a",
    criterion: "标准一。",
    pass_score: 6,
    score_anchors: [
      { score: 4, description: "多处偏差。" },
      { score: 6, description: "达到最低要求。" },
    ],
    criterion_basis: {
      explanation: "材料基准。",
      claims: [
        {
          claim: "老师明确要求书面化表达。",
          kind: "teacher_explicit",
          citation: { locator: "bad_cases[0].feedback[0]", quote: "不要用口语化表达" },
        },
      ],
    },
    pass_score_basis: {
      explained_score: 6,
      explanation: "建议 6 分：达到最低要求即可。",
      claims: [{ claim: "由材料推断的最低门槛。", kind: "ai_inferred", citation: null }],
    },
    ...partial,
  };
}

function detail(partial: Partial<QuestionDetailResponse>): QuestionDetailResponse {
  return {
    id: "q1",
    scene_id: "s1",
    scene_name: "场景",
    client_case_id: "c1",
    title: "题目",
    task_prompt: "任务",
    reference_examples: [],
    bad_cases: [],
    reference_answer: "答案",
    memory_materials: [],
    criteria: null,
    criteria_confirmed: false,
    status: "pending_review",
    next_action: "review_criteria",
    content_revision: 1,
    active_operation_id: null,
    last_operation_id: null,
    last_error: null,
    deletion: null,
    delete_confirmation_required: false,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    published_at: null,
    ...partial,
  };
}

function draft(partial: Partial<CriterionDraft> = {}): CriterionDraft {
  return {
    id: "c1",
    criterion: "标准内容足够长。",
    pass_score: 5,
    score_anchors: [{ score: 5, description: "达到最低要求的表现。" }],
    criterion_basis: null,
    pass_score_basis: null,
    selected: true,
    source: "ai",
    ...partial,
  };
}

describe("draftsFromDetail", () => {
  it("marks AI candidates unselected when not confirmed and copies auxiliaries", () => {
    const d = detail({
      criteria_confirmed: false,
      criteria: [criterionView(), criterionView({ id: "b", criterion: "标准二。", pass_score: 7 })],
    });
    const drafts = draftsFromDetail(d);
    expect(drafts).toHaveLength(2);
    expect(drafts.every((x) => x.selected === false)).toBe(true);
    expect(drafts.every((x) => x.source === "ai")).toBe(true);
    expect(drafts[0].score_anchors).toEqual(criterionView().score_anchors);
    expect(drafts[0].criterion_basis?.claims[0].kind).toBe("teacher_explicit");
    expect(drafts[0].pass_score_basis?.explained_score).toBe(6);
  });

  it("marks authoritative criteria selected when confirmed", () => {
    const d = detail({ criteria_confirmed: true, criteria: [criterionView()] });
    expect(draftsFromDetail(d)[0].selected).toBe(true);
  });

  it("returns empty for null criteria", () => {
    expect(draftsFromDetail(detail({ criteria: null }))).toEqual([]);
  });
});

describe("selectedToPayload", () => {
  it("projects only selected drafts with the FULL contract shape", () => {
    const payload = selectedToPayload([
      draft({ id: "a", selected: true }),
      draft({ id: "b", selected: false }),
    ]);
    expect(payload).toHaveLength(1);
    expect(Object.keys(payload[0]).sort()).toEqual(
      ["criterion", "criterion_basis", "id", "pass_score", "pass_score_basis", "score_anchors"].sort(),
    );
    expect(payload[0].score_anchors).toEqual([{ score: 5, description: "达到最低要求的表现。" }]);
  });

  it("keeps explicitly empty auxiliaries for manual criteria", () => {
    const manual = newManualDraft(new Set());
    manual.criterion = "老师手工新增的完整标准。";
    const payload = selectedToPayload([manual]);
    expect(payload[0].score_anchors).toEqual([]);
    expect(payload[0].criterion_basis).toBeNull();
    expect(payload[0].pass_score_basis).toBeNull();
  });
});

describe("newManualDraft", () => {
  it("creates a selected manual draft with empty auxiliaries", () => {
    const d = newManualDraft(new Set());
    expect(d.source).toBe("manual");
    expect(d.selected).toBe(true);
    expect(d.id.startsWith("manual-")).toBe(true);
    expect(d.score_anchors).toEqual([]);
    expect(d.criterion_basis).toBeNull();
    expect(d.pass_score_basis).toBeNull();
  });
});

describe("unanchored integer editing", () => {
  it("allows saving a score that no anchor describes (anchors are not a whitelist)", () => {
    const d = draft({
      pass_score: 5,
      score_anchors: [
        { score: 4, description: "偏差较多。" },
        { score: 6, description: "达到要求。" },
      ],
    });
    expect(validateSelected([d])).toBeNull();
  });

  it("flags — never rewrites — a basis explaining a different score", () => {
    const stale = draft({
      pass_score: 5,
      pass_score_basis: {
        explained_score: 4,
        explanation: "建议 4 分的理由。",
        claims: [{ claim: "推断。", kind: "ai_inferred", citation: null }],
      },
    });
    expect(hasStaleExplanation(stale)).toBe(true);
    expect(validateSelected([stale])).toBeNull();
    expect(stale.pass_score_basis?.explained_score).toBe(4);
  });

  it("does not flag when the basis matches the current score", () => {
    const fresh = draft({
      pass_score: 5,
      pass_score_basis: {
        explained_score: 5,
        explanation: "建议 5 分的理由。",
        claims: [{ claim: "推断。", kind: "ai_inferred", citation: null }],
      },
    });
    expect(hasStaleExplanation(fresh)).toBe(false);
  });
});

describe("validateSelected", () => {
  it("passes a valid single selection", () => {
    expect(validateSelected([draft()])).toBeNull();
  });

  it("rejects zero selected", () => {
    expect(validateSelected([draft({ selected: false })])?.code).toBe("TOO_FEW");
  });

  it("rejects more than 20 selected", () => {
    const many = Array.from({ length: 21 }, (_, i) => draft({ id: `c${i}` }));
    expect(validateSelected(many)?.code).toBe("TOO_MANY");
  });

  it("rejects duplicate ids", () => {
    expect(validateSelected([draft({ id: "x" }), draft({ id: "x", criterion: "另一条标准。" })])?.code).toBe(
      "DUPLICATE_ID",
    );
  });

  it("rejects empty criterion", () => {
    expect(validateSelected([draft({ criterion: "   " })])?.code).toBe("EMPTY_CRITERION");
  });

  it("rejects out-of-range or non-integer scores", () => {
    expect(validateSelected([draft({ pass_score: 11 })])?.code).toBe("BAD_SCORE");
    expect(validateSelected([draft({ pass_score: -1 })])?.code).toBe("BAD_SCORE");
    expect(validateSelected([draft({ pass_score: 5.5 })])?.code).toBe("BAD_SCORE");
  });

  it("rejects more than 6 anchors, duplicate anchor scores and blank descriptions", () => {
    const tooMany = Array.from({ length: 7 }, (_, i) => ({ score: i, description: "说明。" }));
    expect(validateSelected([draft({ score_anchors: tooMany })])?.code).toBe("TOO_MANY_ANCHORS");
    expect(
      validateSelected([
        draft({
          score_anchors: [
            { score: 4, description: "甲。" },
            { score: 4, description: "乙。" },
          ],
        }),
      ])?.code,
    ).toBe("DUPLICATE_ANCHOR");
    expect(
      validateSelected([draft({ score_anchors: [{ score: 4, description: "  " }] })])?.code,
    ).toBe("EMPTY_ANCHOR_DESCRIPTION");
    expect(
      validateSelected([draft({ score_anchors: [{ score: 11, description: "越界。" }] })])?.code,
    ).toBe("BAD_ANCHOR_SCORE");
  });
});
