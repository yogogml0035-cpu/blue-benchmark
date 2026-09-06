/**
 * Material draft model for the workbench edit mode.
 *
 * On entering edit mode the six material groups are deep-copied into a mutable
 * draft; cancel discards it, and "save & regenerate" projects it into the
 * save-regenerate payload (which overwrites the stored materials).
 */

import type { QuestionDetailResponse, QuestionSaveRegenerateRequest } from "./api";

export interface MemoryMaterialDraft {
  client_ref_id: string;
  source_label: string | null;
  content_text: string;
}

export interface ReferenceExampleDraft {
  client_ref_id: string;
  source_name: string | null;
  content_text: string;
}

export interface BadCaseDraft {
  content_text: string;
  teacher_feedback_texts: string[];
  reason_summary: string | null;
}

export interface MaterialDraft {
  title: string;
  task_prompt: string;
  reference_answer: string;
  reference_examples: ReferenceExampleDraft[];
  bad_cases: BadCaseDraft[];
  memory_materials: MemoryMaterialDraft[];
}

/** Deep-copy the detail's materials into a mutable draft. */
export function draftFromDetail(detail: QuestionDetailResponse): MaterialDraft {
  return {
    title: detail.title,
    task_prompt: detail.task_prompt,
    reference_answer: detail.reference_answer,
    reference_examples: detail.reference_examples.map((e) => ({
      client_ref_id: e.client_ref_id,
      source_name: e.source_name,
      content_text: e.content_text,
    })),
    bad_cases: detail.bad_cases.map((b) => ({
      content_text: b.content_text,
      teacher_feedback_texts: [...b.teacher_feedback_texts],
      reason_summary: b.reason_summary,
    })),
    memory_materials: detail.memory_materials.map((m) => ({
      client_ref_id: m.client_ref_id,
      source_label: m.source_label,
      content_text: m.content_text,
    })),
  };
}

/**
 * Build the save-regenerate payload from the draft. Sends the full current
 * material state so the backend overwrites everything consistently.
 */
export function draftToPayload(
  draft: MaterialDraft,
  base: { command_id: string; content_revision: number },
): QuestionSaveRegenerateRequest {
  return {
    command_id: base.command_id,
    content_revision: base.content_revision,
    title: draft.title,
    task_prompt: draft.task_prompt,
    reference_answer: draft.reference_answer,
    reference_examples: draft.reference_examples.map((e) => ({
      client_ref_id: e.client_ref_id,
      source_name: e.source_name,
      content_text: e.content_text,
    })),
    bad_cases: draft.bad_cases.map((b) => ({
      content_text: b.content_text,
      teacher_feedback_texts: b.teacher_feedback_texts,
      reason_summary: b.reason_summary,
    })),
    memory_materials: draft.memory_materials.map((m) => ({
      client_ref_id: m.client_ref_id,
      source_label: m.source_label,
      content_text: m.content_text,
    })),
  };
}

/**
 * True when the only difference between the draft and the stored detail is the
 * title. A title-only change must use the title endpoint (no regeneration),
 * per the contract that title edits do not burn an AI call.
 */
export function isOnlyTitleChanged(detail: QuestionDetailResponse, draft: MaterialDraft): boolean {
  // FULL-field comparison: if any non-title material differs (including
  // feedback texts, summaries and source labels), this is a material change
  // that must go through the confirmed replace-everything regeneration —
  // never a silent title-only patch that drops the other edits.
  const sameExamples =
    detail.reference_examples.length === draft.reference_examples.length &&
    detail.reference_examples.every(
      (e, i) =>
        e.content_text === draft.reference_examples[i].content_text &&
        e.source_name === draft.reference_examples[i].source_name &&
        e.client_ref_id === draft.reference_examples[i].client_ref_id,
    );
  const sameBadCases =
    detail.bad_cases.length === draft.bad_cases.length &&
    detail.bad_cases.every(
      (b, i) =>
        b.content_text === draft.bad_cases[i].content_text &&
        b.reason_summary === draft.bad_cases[i].reason_summary &&
        b.teacher_feedback_texts.length === draft.bad_cases[i].teacher_feedback_texts.length &&
        b.teacher_feedback_texts.every((t, j) => t === draft.bad_cases[i].teacher_feedback_texts[j]),
    );
  const sameMemory =
    detail.memory_materials.length === draft.memory_materials.length &&
    detail.memory_materials.every(
      (m, i) =>
        m.content_text === draft.memory_materials[i].content_text &&
        m.source_label === draft.memory_materials[i].source_label &&
        m.client_ref_id === draft.memory_materials[i].client_ref_id,
    );
  return (
    draft.title !== detail.title &&
    draft.task_prompt === detail.task_prompt &&
    draft.reference_answer === detail.reference_answer &&
    sameExamples &&
    sameBadCases &&
    sameMemory
  );
}
