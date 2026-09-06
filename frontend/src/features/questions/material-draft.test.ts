import { describe, expect, it } from "vitest";
import type { QuestionDetailResponse } from "./api";
import { draftFromDetail, draftToPayload, isOnlyTitleChanged } from "./material-draft";

function detail(partial: Partial<QuestionDetailResponse>): QuestionDetailResponse {
  return {
    id: "q1",
    scene_id: "s1",
    scene_name: "场景",
    client_case_id: "c1",
    title: "原标题",
    task_prompt: "原任务",
    reference_examples: [{ client_ref_id: "r1", source_name: "来源", content_text: "样例正文" }],
    bad_cases: [
      { content_text: "坏例子", teacher_feedback_texts: ["反馈"], reason_summary: "原因" },
    ],
    reference_answer: "原答案",
    memory_materials: [{ client_ref_id: "m1", source_label: "标签", content_text: "记忆正文" }],
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

describe("draftFromDetail", () => {
  it("deep-copies the six material groups", () => {
    const d = detail({});
    const draft = draftFromDetail(d);
    expect(draft.title).toBe("原标题");
    expect(draft.reference_examples).toHaveLength(1);
    expect(draft.bad_cases[0].teacher_feedback_texts).toEqual(["反馈"]);
    // Mutation of the draft does not leak into the source detail.
    draft.bad_cases[0].teacher_feedback_texts.push("新增");
    expect(d.bad_cases[0].teacher_feedback_texts).toEqual(["反馈"]);
  });
});

describe("draftToPayload", () => {
  it("projects the full material state with command id and revision", () => {
    const draft = draftFromDetail(detail({}));
    const payload = draftToPayload(draft, { command_id: "cmd", content_revision: 3 });
    expect(payload.command_id).toBe("cmd");
    expect(payload.content_revision).toBe(3);
    expect(payload.title).toBe("原标题");
    expect(payload.reference_examples).toHaveLength(1);
    expect(payload.memory_materials![0].content_text).toBe("记忆正文");
  });
});

describe("isOnlyTitleChanged", () => {
  const base = detail({});

  it("is true when only the title changed", () => {
    const draft = draftFromDetail(base);
    draft.title = "新标题";
    expect(isOnlyTitleChanged(base, draft)).toBe(true);
  });

  it("is false when the title is unchanged", () => {
    const draft = draftFromDetail(base);
    expect(isOnlyTitleChanged(base, draft)).toBe(false);
  });

  it("is false when the task prompt also changed", () => {
    const draft = draftFromDetail(base);
    draft.title = "新标题";
    draft.task_prompt = "改过的任务";
    expect(isOnlyTitleChanged(base, draft)).toBe(false);
  });

  it("is false when a reference example content changed", () => {
    const draft = draftFromDetail(base);
    draft.title = "新标题";
    draft.reference_examples[0].content_text = "改过的样例";
    expect(isOnlyTitleChanged(base, draft)).toBe(false);
  });

  it("is false when a list item was added or removed", () => {
    const draft = draftFromDetail(base);
    draft.title = "新标题";
    draft.memory_materials.pop();
    expect(isOnlyTitleChanged(base, draft)).toBe(false);
  });
});
