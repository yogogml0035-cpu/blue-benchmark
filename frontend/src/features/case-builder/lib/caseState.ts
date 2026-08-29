import type { Case, DraftContent } from "@/src/features/case-builder/services/caseBuilderService";

export type CaseState = Case["state"];

type Tone = "neutral" | "active" | "amber" | "red" | "green";

export const TONE_CLASS: Record<Tone, string> = {
  neutral: "state-neutral",
  active: "state-active",
  amber: "state-amber",
  red: "state-red",
  green: "state-green",
};

/** 进程条上当前步的着色：跟随状态自身的语义色。 */
export const TONE_COLOR: Record<Tone, string> = {
  neutral: "var(--text-2)",
  active: "var(--accent)",
  amber: "var(--amber)",
  red: "var(--red)",
  green: "var(--green)",
};

/**
 * 八个对外状态各自的名字、色调和“页面允许的下一步”。
 * 状态语义来自 case-builder 技术合同 §5，前端不再自行推断可执行动作。
 */
export const STATE_META: Record<CaseState, { label: string; tone: Tone; next: string }> = {
  parsing: { label: "解析中", tone: "neutral", next: "正在读取并解析这份材料。" },
  parse_failed: {
    label: "解析失败",
    tone: "red",
    next: "这份材料无法进入 AI 整理。修正后重新上传，不提供无意义的重试。",
  },
  ready_for_ai: { label: "待整理", tone: "neutral", next: "材料已就绪，即将自动整理一版题稿。" },
  generating: { label: "AI 整理中", tone: "active", next: "同一时刻只允许一次运行，请稍候。" },
  waiting_for_input: {
    label: "需要补充",
    tone: "amber",
    next: "回答当前这一个问题，AI 会带着回答继续整理。",
  },
  waiting_for_confirmation: {
    label: "待你定稿",
    tone: "active",
    next: "分节读完、按需修改，然后定稿。",
  },
  ai_failed: { label: "整理失败", tone: "red", next: "按提示的原因决定是否重试同一个会话。" },
  confirmed: { label: "已定稿", tone: "green", next: "题已保存，本页转为只读。" },
};

export type StepStatus = "done" | "active" | "pending" | "failed" | "skipped";

export type Step = { key: string; label: string; status: StepStatus };

/**
 * 刷新或换标签页之后页面不再记得本次是否回答过提问，但 `teacher_answer` 证据
 * 只可能来自一次真实回答（合同 §4.1），所以可以据此还原提问那一步是否走过。
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
 * 进程条：把状态机画成一条沉淀流程。本闭环只有四条路由，
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
        step("upload", "上传", "done"),
        step("parse", "解析", "active"),
        step("draft", "AI 整理", "pending"),
        step("ask", "需要补充", "pending"),
        step("review", "审改", "pending"),
        step("confirm", "定稿", "pending"),
      ];
    case "parse_failed":
      return [
        step("upload", "上传", "done"),
        step("parse", "解析", "failed"),
        step("draft", "AI 整理", "skipped"),
        step("ask", "需要补充", "skipped"),
        step("review", "审改", "skipped"),
        step("confirm", "定稿", "skipped"),
      ];
    case "ready_for_ai":
    case "generating":
      return [
        step("upload", "上传", "done"),
        step("parse", "解析", "done"),
        step("draft", "AI 整理", "active"),
        step("ask", "需要补充", "pending"),
        step("review", "审改", "pending"),
        step("confirm", "定稿", "pending"),
      ];
    case "ai_failed":
      return [
        step("upload", "上传", "done"),
        step("parse", "解析", "done"),
        step("draft", "AI 整理", "failed"),
        step("ask", "需要补充", "pending"),
        step("review", "审改", "pending"),
        step("confirm", "定稿", "pending"),
      ];
    case "waiting_for_input":
      return [
        step("upload", "上传", "done"),
        step("parse", "解析", "done"),
        step("draft", "AI 整理", "done"),
        step("ask", "需要补充", "active"),
        step("review", "审改", "pending"),
        step("confirm", "定稿", "pending"),
      ];
    case "waiting_for_confirmation":
      return [
        step("upload", "上传", "done"),
        step("parse", "解析", "done"),
        step("draft", "AI 整理", "done"),
        step("ask", "需要补充", answered ? "done" : "skipped"),
        step("review", "审改", "active"),
        step("confirm", "定稿", "pending"),
      ];
    case "confirmed":
      return [
        step("upload", "上传", "done"),
        step("parse", "解析", "done"),
        step("draft", "AI 整理", "done"),
        step("ask", "需要补充", answered || hasDraft ? "done" : "skipped"),
        step("review", "审改", "done"),
        step("confirm", "定稿", "done"),
      ];
  }
}
