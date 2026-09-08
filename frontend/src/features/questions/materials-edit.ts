/**
 * Per-module material autosave model for the workbench.
 *
 * Each material module (题目/标准答案/参考文本/Bad case/业务记忆) keeps a local
 * buffer while its edit state is open; leaving the module builds a PATCH
 * /materials payload for that single field. Absent fields keep their stored
 * values server-side, so a module commit never overwrites concurrent edits
 * made through other modules. Autosave writes text only: the backend never
 * bumps content_revision, touches criteria, or enqueues generation here.
 */

import type { QuestionDetailResponse, QuestionMaterialsPatchRequest } from "./api";

export type MaterialModuleKey =
  | "task_prompt"
  | "reference_answer"
  | "reference_examples"
  | "bad_cases"
  | "memory_materials";

export interface ReferenceExampleBuffer {
  client_ref_id: string;
  source_name: string | null;
  content_text: string;
}

export interface BadCaseBuffer {
  content_text: string;
  teacher_feedback_texts: string[];
  reason_summary: string | null;
}

export interface MemoryMaterialBuffer {
  client_ref_id: string;
  source_label: string | null;
  content_text: string;
}

export type MaterialModuleBuffer =
  | string
  | ReferenceExampleBuffer[]
  | BadCaseBuffer[]
  | MemoryMaterialBuffer[];

/** Deep-copy the module's stored value into an editable buffer. */
export function moduleBuffer(
  detail: QuestionDetailResponse,
  key: MaterialModuleKey,
): MaterialModuleBuffer {
  switch (key) {
    case "task_prompt":
      return detail.task_prompt;
    case "reference_answer":
      return detail.reference_answer;
    case "reference_examples":
      return detail.reference_examples.map((e) => ({ ...e }));
    case "bad_cases":
      return detail.bad_cases.map((b) => ({
        content_text: b.content_text,
        teacher_feedback_texts: [...b.teacher_feedback_texts],
        reason_summary: b.reason_summary,
      }));
    case "memory_materials":
      return detail.memory_materials.map((m) => ({ ...m }));
  }
}

function sameExamples(
  a: readonly ReferenceExampleBuffer[],
  b: readonly ReferenceExampleBuffer[],
): boolean {
  return (
    a.length === b.length &&
    a.every(
      (item, i) =>
        item.client_ref_id === b[i].client_ref_id &&
        item.source_name === b[i].source_name &&
        item.content_text === b[i].content_text,
    )
  );
}

function sameBadCases(a: readonly BadCaseBuffer[], b: readonly BadCaseBuffer[]): boolean {
  return (
    a.length === b.length &&
    a.every(
      (item, i) =>
        item.content_text === b[i].content_text &&
        item.reason_summary === b[i].reason_summary &&
        item.teacher_feedback_texts.length === b[i].teacher_feedback_texts.length &&
        item.teacher_feedback_texts.every((t, j) => t === b[i].teacher_feedback_texts[j]),
    )
  );
}

function sameMemory(a: readonly MemoryMaterialBuffer[], b: readonly MemoryMaterialBuffer[]): boolean {
  return (
    a.length === b.length &&
    a.every(
      (item, i) =>
        item.client_ref_id === b[i].client_ref_id &&
        item.source_label === b[i].source_label &&
        item.content_text === b[i].content_text,
    )
  );
}

/**
 * Build the single-field PATCH payload for a module commit; `null` when the
 * buffer is unchanged from the stored detail (a no-op autosave skips the
 * request entirely).
 */
export function buildModulePatch(
  detail: QuestionDetailResponse,
  key: MaterialModuleKey,
  buffer: MaterialModuleBuffer,
): Omit<QuestionMaterialsPatchRequest, "content_revision"> | null {
  switch (key) {
    case "task_prompt":
      return buffer !== detail.task_prompt ? { task_prompt: buffer as string } : null;
    case "reference_answer":
      return buffer !== detail.reference_answer ? { reference_answer: buffer as string } : null;
    case "reference_examples":
      return sameExamples(buffer as ReferenceExampleBuffer[], detail.reference_examples)
        ? null
        : {
            reference_examples: (buffer as ReferenceExampleBuffer[]).map((e) => ({
              client_ref_id: e.client_ref_id,
              source_name: e.source_name,
              content_text: e.content_text,
            })),
          };
    case "bad_cases":
      return sameBadCases(buffer as BadCaseBuffer[], detail.bad_cases)
        ? null
        : {
            bad_cases: (buffer as BadCaseBuffer[]).map((b) => ({
              content_text: b.content_text,
              teacher_feedback_texts: b.teacher_feedback_texts,
              reason_summary: b.reason_summary,
            })),
          };
    case "memory_materials":
      return sameMemory(buffer as MemoryMaterialBuffer[], detail.memory_materials)
        ? null
        : {
            memory_materials: (buffer as MemoryMaterialBuffer[]).map((m) => ({
              client_ref_id: m.client_ref_id,
              source_label: m.source_label,
              content_text: m.content_text,
            })),
          };
  }
}
