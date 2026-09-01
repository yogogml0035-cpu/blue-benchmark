import type { components } from "@/src/lib/api/generated";

type Schemas = components["schemas"];
type HumanSubmissionResponse = Schemas["HumanSubmissionResponse"];
type HumanScore = Schemas["HumanScoreView"];

const now = "2026-09-01T09:00:00.000Z";

const criteriaV1: Schemas["RubricCriterion"][] = [
  {
    id: "fact_accuracy",
    name: "事实准确性",
    purpose: "确保关键事实与确认资料一致。",
    max_score: 60,
    award_points: ["关键事实可以从确认资料中复核。"],
    deduction_points: ["编造或篡改资料未提供的事实。"],
    critical: true,
    critical_mode: "minimum",
    critical_min_score: 36,
    hard_fail_conditions: [],
    reference_expected_score: 58,
    reference_score_reason: "标准答案遵守资料边界。",
    reference_hard_fail_triggered: false,
  },
  {
    id: "deliverable_quality",
    name: "交付可用性",
    purpose: "确保结果满足交付目标并可以直接使用。",
    max_score: 40,
    award_points: ["完整回应任务要求，表达清楚。"],
    deduction_points: ["遗漏必要交付内容。"],
    critical: false,
    critical_mode: "none",
    critical_min_score: null,
    hard_fail_conditions: [],
    reference_expected_score: 40,
    reference_score_reason: "标准答案覆盖了交付目标。",
    reference_hard_fail_triggered: false,
  },
];

const criteriaV2: Schemas["RubricCriterion"][] = [
  {
    id: "source_traceability",
    name: "来源可追溯性",
    purpose: "确保每个关键结论都能回到确认材料中的具体依据。",
    max_score: 50,
    award_points: ["关键结论均有明确来源。"],
    deduction_points: ["出现无法回溯到材料的核心判断。"],
    critical: true,
    critical_mode: "minimum",
    critical_min_score: 30,
    hard_fail_conditions: [],
    reference_expected_score: 48,
    reference_score_reason: "新版标准要求关键结论具备可追溯依据。",
    reference_hard_fail_triggered: false,
  },
  {
    id: "deliverable_quality_v2",
    name: "交付可用性",
    purpose: "确保结果满足当前交付目标并可以直接使用。",
    max_score: 50,
    award_points: ["完整回应任务要求，表达清楚。"],
    deduction_points: ["遗漏必要交付内容。"],
    critical: false,
    critical_mode: "none",
    critical_min_score: null,
    hard_fail_conditions: [],
    reference_expected_score: 48,
    reference_score_reason: "新版标准提高了交付完整性的权重。",
    reference_hard_fail_triggered: false,
  },
];

function questionRevision(
  id: string,
  revisionNumber: number,
  title: string,
  criteria: Schemas["RubricCriterion"][],
): Schemas["QuestionRevisionView"] {
  return {
    id,
    revision_number: revisionNumber,
    title,
    summary: revisionNumber === 1
      ? "根据确认资料形成一份可直接使用的事实准确新闻稿。"
      : "按升级后的来源标准形成一份可直接使用的事实准确新闻稿。",
    question_input: {
      task_instruction: "根据确认资料形成一份事实准确的新闻稿。",
      materials: [],
      must_include: ["事实来源", "关键产品参数"],
      prohibited: ["无来源推断", "把标准答案当作唯一措辞"],
      background: "这是一个真实业务交付形成的题目。",
    },
    reference_answer_text: revisionNumber === 1
      ? "老师明确认可的终版结果，事实可以逐条回到确认资料。"
      : "老师明确认可的新版终版结果，每个关键结论都能回到对应来源。",
    criteria,
    pass_threshold: 60,
  };
}

function submission(): Schemas["SubmissionView"] {
  return {
    id: "preview-submission",
    workspace_id: "preview-workspace",
    question_revision_id: "preview-question-revision",
    source: "paste",
    original_name: null,
    media_type: "text/plain",
    size_bytes: 96,
    sha256: "a".repeat(64),
    content_text: "这是一份待评新闻稿。\n\n产品参数与事实来源已经写在正文中，等待老师逐项核对。",
    submitted_at: now,
  };
}

function scoreV1(id: string, parent_score_id: string | null, fact: number): HumanScore {
  return {
    id,
    submission_id: "preview-submission",
    question_revision_id: "preview-question-revision",
    parent_score_id,
    status: "submitted",
    items: [
      {
        criterion_id: "fact_accuracy",
        score: fact,
        reason: fact < 58 ? "有一条关键参数没有在资料中找到对应依据。" : null,
        hard_fail_triggered: null,
        critical_passed: fact >= 36,
      },
      {
        criterion_id: "deliverable_quality",
        score: 40,
        reason: null,
        hard_fail_triggered: null,
        critical_passed: true,
      },
    ],
    overall_reason: fact < 58 ? "事实项仍有证据缺口。" : "两项均达到标准。",
    total_score: fact + 40,
    critical_passed: fact >= 36,
    passed: fact + 40 >= 60 && fact >= 36,
    submitted_at: now,
  };
}

function scoreV2(id: string, parent_score_id: string | null, sourceScore: number): HumanScore {
  return {
    id,
    submission_id: "preview-submission",
    question_revision_id: "preview-question-revision-v2",
    parent_score_id,
    status: "submitted",
    items: [
      {
        criterion_id: "source_traceability",
        score: sourceScore,
        reason: sourceScore < 48 ? "有一条关键结论没有对应的来源依据。" : null,
        hard_fail_triggered: null,
        critical_passed: sourceScore >= 30,
      },
      {
        criterion_id: "deliverable_quality_v2",
        score: 48,
        reason: null,
        hard_fail_triggered: null,
        critical_passed: true,
      },
    ],
    overall_reason: sourceScore < 48 ? "新版来源标准下仍有一处证据缺口。" : "新版标准下两项均达到要求。",
    total_score: sourceScore + 48,
    critical_passed: sourceScore >= 30,
    passed: sourceScore + 48 >= 60 && sourceScore >= 30,
    submitted_at: now,
  };
}

export function previewSubmission(
  state: "human_draft" | "human_submitted" | "human_rescore" | "human_history",
): HumanSubmissionResponse {
  const original = questionRevision("preview-question-revision", 1, "媒体供稿题", criteriaV1);
  const latest = questionRevision("preview-question-revision-v2", 2, "媒体供稿题 · 升级标准", criteriaV2);
  const scores = state === "human_draft"
    ? []
    : state === "human_rescore"
      ? [scoreV1("preview-score-1", null, 50), scoreV2("preview-score-2", "preview-score-1", 48)]
      : state === "human_history"
        ? [scoreV1("preview-score-1", null, 50), scoreV2("preview-score-2", "preview-score-1", 48)]
        : [scoreV1("preview-score-1", null, 50)];
  return {
    submission: submission(),
    question_revision: original,
    question_revisions: {
      [original.id]: original,
      [latest.id]: latest,
    },
    scores,
  };
}

export const PREVIEW_PUBLISHED_REVISIONS: Schemas["PublishedQuestionRevisionSummary"][] = [
  {
    id: "preview-question-revision",
    question_draft_id: "preview-question-draft",
    revision: 1,
    title: "媒体供稿题",
    pass_threshold: 60,
    content_sha256: "b".repeat(64),
    published_at: now,
  },
  {
    id: "preview-question-revision-v2",
    question_draft_id: "preview-question-draft",
    revision: 2,
    title: "媒体供稿题 · 升级标准",
    pass_threshold: 60,
    content_sha256: "c".repeat(64),
    published_at: now,
  },
];
