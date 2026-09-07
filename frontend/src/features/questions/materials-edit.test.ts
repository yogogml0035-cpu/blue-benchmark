import { describe, expect, it } from "vitest";
import type { QuestionDetailResponse } from "./api";
import {
  buildModulePatch,
  moduleBuffer,
  type BadCaseBuffer,
  type MemoryMaterialBuffer,
  type ReferenceExampleBuffer,
} from "./materials-edit";

function detail(overrides: Partial<QuestionDetailResponse> = {}): QuestionDetailResponse {
  return {
    id: "q1",
    scene_id: "s1",
    scene_name: "场景",
    client_case_id: "case-1",
    title: "标题",
    task_prompt: "题目原文。",
    reference_examples: [
      { client_ref_id: "ref-1", source_name: "素材", content_text: "参考文本一。" },
    ],
    bad_cases: [
      {
        content_text: "被否定的初稿。",
        teacher_feedback_texts: ["语气不对。"],
        reason_summary: "语体不符。",
      },
    ],
    reference_answer: "标准答案。",
    memory_materials: [
      { client_ref_id: "mem-1", source_label: "记忆", content_text: "记忆原文。" },
    ],
    criteria: null,
    criteria_confirmed: false,
    criteria_basis_stale: false,
    status: "pending_review",
    next_action: "review_criteria",
    content_revision: 3,
    active_operation_id: null,
    last_operation_id: null,
    last_error: null,
    deletion: null,
    delete_confirmation_required: false,
    created_at: "2026-09-07T00:00:00Z",
    updated_at: "2026-09-07T00:00:00Z",
    published_at: null,
    ...overrides,
  } as QuestionDetailResponse;
}

describe("moduleBuffer", () => {
  it("deep-copies list modules so edits stay local", () => {
    const d = detail();
    const buffer = moduleBuffer(d, "reference_examples") as ReferenceExampleBuffer[];
    buffer[0].content_text = "改过的文本。";
    expect(d.reference_examples[0].content_text).toBe("参考文本一。");
  });
});

describe("buildModulePatch", () => {
  it("returns null for an unchanged scalar module (no-op autosave)", () => {
    const d = detail();
    expect(buildModulePatch(d, "task_prompt", moduleBuffer(d, "task_prompt"))).toBeNull();
  });

  it("builds a single-field scalar patch", () => {
    const d = detail();
    expect(buildModulePatch(d, "reference_answer", "新的标准答案。")).toEqual({
      reference_answer: "新的标准答案。",
    });
  });

  it("returns null when a list module is value-identical", () => {
    const d = detail();
    const buffer = moduleBuffer(d, "bad_cases");
    expect(buildModulePatch(d, "bad_cases", buffer)).toBeNull();
  });

  it("detects a list change by value, not reference", () => {
    const d = detail();
    const buffer = moduleBuffer(d, "memory_materials") as MemoryMaterialBuffer[];
    buffer[0] = { ...buffer[0], content_text: "改过的记忆。" };
    const patch = buildModulePatch(d, "memory_materials", buffer);
    expect(patch).toEqual({
      memory_materials: [
        { client_ref_id: "mem-1", source_label: "记忆", content_text: "改过的记忆。" },
      ],
    });
  });

  it("preserves feedback arrays and null summaries in bad case patches", () => {
    const d = detail();
    const buffer = moduleBuffer(d, "bad_cases") as BadCaseBuffer[];
    buffer[0].teacher_feedback_texts = [...buffer[0].teacher_feedback_texts, "补充反馈。"];
    const patch = buildModulePatch(d, "bad_cases", buffer);
    expect(patch).toEqual({
      bad_cases: [
        {
          content_text: "被否定的初稿。",
          teacher_feedback_texts: ["语气不对。", "补充反馈。"],
          reason_summary: "语体不符。",
        },
      ],
    });
  });
});
