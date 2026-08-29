import type { Case, DraftContent } from "@/src/features/case-builder/services/caseBuilderService";

export type CaseState = Case["state"];

type Tone = "neutral" | "ai" | "gap" | "teacher" | "cleared" | "fail";

export const TONE_CLASS: Record<Tone, string> = {
  neutral: "state-neutral",
  ai: "state-ai",
  gap: "state-gap",
  teacher: "state-teacher",
  cleared: "state-cleared",
  fail: "state-fail",
};

/**
 * 八个对外状态各自的名字、色调和“页面允许的下一步”。
 * 状态语义来自 case-builder 技术合同 §5，前端不再自行推断可执行动作。
 */
export const STATE_META: Record<CaseState, { label: string; tone: Tone; next: string }> = {
  parsing: { label: "解析中", tone: "neutral", next: "等待服务端读完并解析这份原件。" },
  parse_failed: {
    label: "解析失败",
    tone: "fail",
    next: "这份原件无法进入 AI。修正文件后重新收件，不提供无意义的重试。",
  },
  ready_for_ai: { label: "输入已就绪", tone: "neutral", next: "自动请 AI 起草一次。" },
  generating: { label: "AI 起草中", tone: "ai", next: "同一时刻只允许一次运行，请稍候。" },
  waiting_for_input: {
    label: "等待补充证据",
    tone: "gap",
    next: "回答当前这一个问题，AI 会用同一个会话继续。",
  },
  waiting_for_confirmation: {
    label: "等待人工确认",
    tone: "teacher",
    next: "逐条审阅、按需修改，然后确认落章。",
  },
  ai_failed: { label: "AI 失败", tone: "fail", next: "按清洗后的原因决定是否重试同一个会话。" },
  confirmed: { label: "已确认", tone: "cleared", next: "候选用例已保存，本页转为只读。" },
};

export type StepStatus = "done" | "active" | "pending" | "failed" | "skipped";

export type Step = { key: string; label: string; status: StepStatus };

/**
 * 刷新或换标签页之后页面不再记得本次是否回答过追问，但 `teacher_answer` 引注
 * 只可能来自一次真实回答（合同 §4.1），所以可以据此还原追问那一步是否走过。
 */
export function hasTeacherAnswer(draft: DraftContent | null | undefined): boolean {
  if (!draft) return false;
  const groups = [
    draft.scenario.evidence_refs,
    draft.reference_outcome?.evidence_refs,
    ...(draft.facts ?? []).map((item) => item.evidence_refs),
    ...(draft.teacher_judgments ?? []).map((item) => item.evidence_refs),
    ...(draft.proposed_standards ?? []).map((item) => item.evidence_refs),
    ...draft.dimensions.map((item) => item.evidence_refs),
  ];
  return groups.some((refs) => (refs ?? []).some((ref) => ref.kind === "teacher_answer"));
}

/**
 * 进程条：把状态机画成一条校样流程。本闭环只有四条路由，
 * 所以“当前处在流程哪一步”本身就承担了导航职责。
 */
export function trackFor(
  state: CaseState,
  options: { answered: boolean; hasDraft: boolean },
): Step[] {
  const { answered, hasDraft } = options;
  const step = (key: string, label: string, status: StepStatus): Step => ({ key, label, status });

  switch (state) {
    case "parsing":
      return [
        step("intake", "收件", "done"),
        step("parse", "解析", "active"),
        step("draft", "起草", "pending"),
        step("query", "追问", "pending"),
        step("review", "校订", "pending"),
        step("seal", "落章", "pending"),
      ];
    case "parse_failed":
      return [
        step("intake", "收件", "done"),
        step("parse", "解析", "failed"),
        step("draft", "起草", "skipped"),
        step("query", "追问", "skipped"),
        step("review", "校订", "skipped"),
        step("seal", "落章", "skipped"),
      ];
    case "ready_for_ai":
    case "generating":
      return [
        step("intake", "收件", "done"),
        step("parse", "解析", "done"),
        step("draft", "起草", "active"),
        step("query", "追问", "pending"),
        step("review", "校订", "pending"),
        step("seal", "落章", "pending"),
      ];
    case "ai_failed":
      return [
        step("intake", "收件", "done"),
        step("parse", "解析", "done"),
        step("draft", "起草", "failed"),
        step("query", "追问", "pending"),
        step("review", "校订", "pending"),
        step("seal", "落章", "pending"),
      ];
    case "waiting_for_input":
      return [
        step("intake", "收件", "done"),
        step("parse", "解析", "done"),
        step("draft", "起草", "done"),
        step("query", "追问", "active"),
        step("review", "校订", "pending"),
        step("seal", "落章", "pending"),
      ];
    case "waiting_for_confirmation":
      return [
        step("intake", "收件", "done"),
        step("parse", "解析", "done"),
        step("draft", "起草", "done"),
        step("query", "追问", answered ? "done" : "skipped"),
        step("review", "校订", "active"),
        step("seal", "落章", "pending"),
      ];
    case "confirmed":
      return [
        step("intake", "收件", "done"),
        step("parse", "解析", "done"),
        step("draft", "起草", "done"),
        step("query", "追问", answered || hasDraft ? "done" : "skipped"),
        step("review", "校订", "done"),
        step("seal", "落章", "done"),
      ];
  }
}
