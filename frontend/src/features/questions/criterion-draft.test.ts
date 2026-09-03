import { describe, expect, it } from "vitest";
import type { QuestionDetailResponse } from "./api";
import {
  draftsFromDetail,
  newManualDraft,
  selectedToPayload,
  validateSelected,
  type CriterionDraft,
} from "./criterion-draft";

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
    last_error: null,
    delete_confirmation_required: false,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    published_at: null,
    ...partial,
  };
}

function draft(partial: Partial<CriterionDraft> = {}): CriterionDraft {
  return { id: "c1", criterion: "标准内容足够长。", pass_score: 5, selected: true, source: "ai", ...partial };
}

describe("draftsFromDetail", () => {
  it("marks AI candidates unselected when not confirmed", () => {
    const d = detail({
      criteria_confirmed: false,
      criteria: [
        { id: "a", criterion: "标准一。", pass_score: 6 },
        { id: "b", criterion: "标准二。", pass_score: 7 },
      ],
    });
    const drafts = draftsFromDetail(d);
    expect(drafts).toHaveLength(2);
    expect(drafts.every((x) => x.selected === false)).toBe(true);
    expect(drafts.every((x) => x.source === "ai")).toBe(true);
  });

  it("marks authoritative criteria selected when confirmed", () => {
    const d = detail({
      criteria_confirmed: true,
      criteria: [{ id: "a", criterion: "标准一。", pass_score: 6 }],
    });
    const drafts = draftsFromDetail(d);
    expect(drafts[0].selected).toBe(true);
  });

  it("returns empty for null criteria", () => {
    expect(draftsFromDetail(detail({ criteria: null }))).toEqual([]);
  });
});

describe("selectedToPayload", () => {
  it("projects only selected drafts without selected/source", () => {
    const payload = selectedToPayload([
      draft({ id: "a", selected: true }),
      draft({ id: "b", selected: false }),
    ]);
    expect(payload).toEqual([{ id: "a", criterion: "标准内容足够长。", pass_score: 5 }]);
    expect(Object.keys(payload[0])).toEqual(["id", "criterion", "pass_score"]);
  });
});

describe("newManualDraft", () => {
  it("creates a selected manual draft with a manual- id", () => {
    const d = newManualDraft(new Set());
    expect(d.source).toBe("manual");
    expect(d.selected).toBe(true);
    expect(d.id.startsWith("manual-")).toBe(true);
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
});
