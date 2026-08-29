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
 * 沉淀流程条：上传 → 解析 → AI 整理 → 需要补充 → 审改 → 收录。
 * 当前步用状态自身的语义色着色，已完成用中性灰，
 * 本闭环只有四条路由且流程线性，这条进程条本身就是导航。
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
    <div className="stack-sm">
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
      <p className="secondary" style={{ fontSize: "var(--t-13)" }}>
        {STATE_META[state].next}
      </p>
    </div>
  );
}
