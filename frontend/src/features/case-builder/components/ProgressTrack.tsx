import type { CSSProperties } from "react";

import {
  STATE_META,
  TONE_COLOR,
  type CaseState,
  type Step,
  type StepStatus,
  trackFor,
} from "@/src/features/case-builder/lib/caseState";

import styles from "./caseDetail.module.css";

const DOT: Record<StepStatus, string> = {
  done: styles.dotDone,
  active: styles.dotActive,
  pending: styles.dotPending,
  failed: styles.dotFailed,
  skipped: styles.dotSkipped,
};

const LABEL_STYLE: Record<StepStatus, CSSProperties> = {
  done: { color: "var(--text-2)" },
  active: { color: "var(--text)", fontWeight: 600 },
  pending: { color: "var(--text-3)" },
  failed: { color: "var(--red)", fontWeight: 600 },
  skipped: { color: "var(--text-3)" },
};

/**
 * 沉淀流程条：上传 → 解析 → AI 整理 → 需要补充 → 审改 → 定稿。
 * 只在等待态出现（解析中、整理中、需要补充），作为安静的方向提示；
 * 进入审改后由题卡自己的刻度接管，不再重复表达。
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
  const color = TONE_COLOR[STATE_META[state].tone];
  return (
    <ol className={styles.track}>
      {steps.map((step: Step) => (
        <li className={styles.step} key={step.key}>
          <span className={styles.stepMark} style={{ color }}>
            <span aria-hidden="true" className={DOT[step.status]} />
          </span>
          <span className={styles.stepLabel} style={LABEL_STYLE[step.status]}>
            {step.label}
          </span>
        </li>
      ))}
    </ol>
  );
}
