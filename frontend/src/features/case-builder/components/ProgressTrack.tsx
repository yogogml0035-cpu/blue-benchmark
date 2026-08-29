import {
  STATE_META,
  type CaseState,
  type Step,
  type StepStatus,
  trackFor,
} from "@/src/features/case-builder/lib/caseState";

import styles from "./caseBuilder.module.css";

const DOT: Record<StepStatus, string> = {
  done: styles.dotDone,
  active: styles.dotActive,
  pending: styles.dotPending,
  failed: styles.dotFailed,
  skipped: styles.dotSkipped,
};

const LABEL_STYLE: Record<StepStatus, React.CSSProperties> = {
  done: { color: "var(--ink-secondary)" },
  active: { color: "var(--ink)", fontWeight: 600 },
  pending: { color: "var(--ink-faint)" },
  failed: { color: "var(--seal)", fontWeight: 600 },
  skipped: { color: "var(--ink-faint)" },
};

const TONE_INK: Record<string, string> = {
  neutral: "var(--ink-secondary)",
  ai: "var(--prov-ai)",
  gap: "var(--prov-gap)",
  teacher: "var(--prov-teacher)",
  cleared: "var(--prov-cleared)",
  fail: "var(--seal)",
};

/**
 * 校样流程条。当前步用状态自身的语义色着色，已完成用中性墨色，
 * 避免把六个步骤染成六种颜色而稀释掉“来源墨色”的语义。
 */
export function ProgressTrack({
  state,
  answered,
  hasDraft,
}: {
  state: CaseState;
  answered: boolean;
  hasDraft: boolean;
}) {
  const steps = trackFor(state, { answered, hasDraft });
  const ink = TONE_INK[STATE_META[state].tone] ?? "var(--ink)";
  return (
    <div className="stack-sm">
      <ol className={styles.track}>
        {steps.map((step: Step) => (
          <li className={styles.step} key={step.key}>
            <span className={styles.stepMark} style={{ color: ink }}>
              <span aria-hidden="true" className={DOT[step.status]} />
            </span>
            <span className={styles.stepLabel} style={LABEL_STYLE[step.status]}>
              {step.label}
            </span>
          </li>
        ))}
      </ol>
      <p className="secondary" style={{ fontSize: "var(--t-13)" }}>
        {STATE_META[state].next}
      </p>
    </div>
  );
}
