import type { Case, DraftContent } from "@/src/features/case-builder/services/caseBuilderService";

/**
 * 状态预演用的案例快照，全部用 OpenAPI 生成的 Case / DraftContent 类型构造。
 * 证据只指向本快照自己的附件 id、案例 id 和问题 id，与确认接口的证据校验规则一致。
 */
const CASE_ID = "6d2f1a84-91cc-4d0b-8c33-51a7e9b4c210";
const ATTACHMENT_ID = "8a41c7e2-5b39-4f61-9d02-7c5e3b1f8a44";
const QUESTION_ID = "c93b7f16-2a84-4d59-bf10-6e2d8a4c5b71";
const WORKSPACE_ID = "0f3a9c21-7c14-4e0a-9a0b-2f6b8d5a1e01";
const USER_ID = "9c1d2e3f-4a5b-6c7d-8e9f-0a1b2c3d4e5f";

const base: Omit<Case, "state" | "builder" | "candidate_case"> = {
  id: CASE_ID,
  workspace_id: WORKSPACE_ID,
  title: "客户 A 春季新品新闻稿终稿",
  task_description:
    "客户 Brief 要求突出续航与充电速度，全文不超过 900 字，不得出现未经确认的参数与竞品对比。",
  attachment: {
    id: ATTACHMENT_ID,
    original_name: "客户A-新品稿-终稿.md",
    media_type: "text/markdown",
    size_bytes: 7412,
  },
  created_at: "2026-08-29T01:20:00Z",
  updated_at: "2026-08-29T01:24:00Z",
};

const attachmentRef = (locator: string, quote: string) => ({
  kind: "attachment_excerpt" as const,
  source_id: ATTACHMENT_ID,
  locator,
  quote,
});

const DRAFT: DraftContent = {
  scenario: {
    summary:
      "单一客户的产品新闻稿撰写与审核：依据客户 Brief 与素材包完成可交付终稿，事实必须能在素材中找到出处。",
    evidence_refs: [
      {
        kind: "task_description",
        source_id: CASE_ID,
        locator: null,
        quote: "客户 Brief 要求突出续航与充电速度",
      },
    ],
  },
  task_goal: "完成一篇满足客户 Brief、可直接对外发布的中文新闻稿终稿。",
  input_summary: "客户 Brief、产品素材包中的参数表，以及老师认可的终稿全文。",
  output_requirements: ["交付 Markdown 正文", "全文不超过 900 字", "首段出现产品正式名称"],
  prohibited_errors: ["不得编造素材包以外的产品参数", "不得出现未经确认的竞品对比"],
  reference_outcome: {
    accepted_result:
      "以「续航 22 小时、30 分钟充至 60%」为核心卖点的 860 字终稿，参数全部来自素材包参数表。",
    rationale: "事实可逐条回溯到参数表，且满足字数与品牌禁用项要求。",
    evidence_refs: [attachmentRef("lines 118-164", "续航 22 小时；30 分钟充至 60%")],
  },
  facts: [
    {
      id: "fact-1",
      text: "素材包参数表给出续航 22 小时、30 分钟充至 60%。",
      evidence_refs: [attachmentRef("lines 24-31", "标称续航 22h / 快充 30min→60%")],
    },
    {
      id: "fact-2",
      text: "客户 Brief 把字数上限定为 900 字。",
      evidence_refs: [
        { kind: "task_description", source_id: CASE_ID, locator: null, quote: "全文不超过 900 字" },
      ],
    },
  ],
  teacher_judgments: [
    {
      id: "judgment-1",
      text: "终稿之所以通过，是因为每一个参数都能在参数表里找到同样的数字，没有四舍五入。",
      evidence_refs: [
        {
          kind: "teacher_answer",
          source_id: QUESTION_ID,
          locator: null,
          quote: "每个参数都能和参数表对上，没有四舍五入",
        },
      ],
    },
  ],
  proposed_standards: [
    {
      id: "proposal-1",
      text: "所有数字型卖点都应逐一对应素材包中的原始数值，禁止取整或换算后直接陈述。",
      evidence_refs: [attachmentRef("lines 24-31", "标称续航 22h / 快充 30min→60%")],
    },
  ],
  unknowns: [
    { id: "gap-1", text: "客户对副标题风格的长期偏好仍未固化，本次以终稿为准。", blocking: false },
  ],
  primary_capability: "在有素材约束的新闻稿写作中保持参数级事实准确。",
  dimensions: [
    {
      id: "dimension-1",
      name: "事实准确性",
      kind: "hard_gate",
      criterion: "文中每个产品参数都能在素材包参数表中找到完全一致的数值。",
      evidence_refs: [attachmentRef("lines 24-31", "标称续航 22h / 快充 30min→60%")],
    },
    {
      id: "dimension-2",
      name: "Brief 合规",
      kind: "required_quality",
      criterion: "全文不超过 900 字，且首段出现产品正式名称。",
      evidence_refs: [
        { kind: "task_description", source_id: CASE_ID, locator: null, quote: "全文不超过 900 字" },
      ],
    },
    {
      id: "dimension-3",
      name: "可读性",
      kind: "diagnostic",
      criterion: "段落不超过四句，无连续两段以同一句式开头。",
      evidence_refs: [attachmentRef("lines 118-164", "终稿段落结构")],
    },
  ],
  tags: ["新闻稿", "客户 A", "参数准确性"],
};

export const PREVIEW_CASE_PARSE_EMPTY: Case = {
  ...base,
  attachment: { ...base.attachment, original_name: "空白稿.txt", media_type: "text/plain", size_bytes: 3 },
  state: "parse_failed",
  builder: {
    draft_revision: 0,
    pending_question: null,
    draft: null,
    last_error: {
      stage: "parse",
      code: "PARSED_CONTENT_EMPTY",
      message: "文件内容为空，不能进入 AI 整理。",
      retryable: false,
    },
  },
  candidate_case: null,
};

export const PREVIEW_CASE_AI_FAILED: Case = {
  ...base,
  state: "ai_failed",
  builder: {
    draft_revision: 0,
    pending_question: null,
    draft: null,
    last_error: {
      stage: "ai",
      code: "MODEL_OUTPUT_INVALID",
      message: "AI 返回的草稿结构不完整，请重试。",
      retryable: true,
    },
  },
  candidate_case: null,
};

export const PREVIEW_CASE_WAITING_INPUT: Case = {
  ...base,
  state: "waiting_for_input",
  builder: {
    draft_revision: 0,
    pending_question: {
      id: QUESTION_ID,
      text: "这份案例里，哪一个结果是你最终认可的？",
      reason: "缺少参考结果，无法形成可验证的通过条件。",
    },
    draft: null,
    last_error: null,
  },
  candidate_case: null,
};

export const PREVIEW_CASE_WAITING_CONFIRMATION: Case = {
  ...base,
  state: "waiting_for_confirmation",
  builder: { draft_revision: 1, pending_question: null, draft: DRAFT, last_error: null },
  candidate_case: null,
};

export const PREVIEW_CASE_CONFIRMED: Case = {
  ...base,
  state: "confirmed",
  updated_at: "2026-08-29T01:31:00Z",
  builder: { draft_revision: 1, pending_question: null, draft: DRAFT, last_error: null },
  candidate_case: {
    id: "b7e1d940-3c62-4a85-9f27-1d8c4b6e0a53",
    source_case_id: CASE_ID,
    draft_revision: 1,
    content: DRAFT,
    confirmed_by: USER_ID,
    confirmed_at: "2026-08-29T01:31:00Z",
  },
};
