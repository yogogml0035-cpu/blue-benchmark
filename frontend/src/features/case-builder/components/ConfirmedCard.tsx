import type { components } from "@/src/lib/api/generated";
import { stamp } from "@/src/lib/format";
import { PREVIEW_ENABLED } from "@/src/lib/preview/preview";

import styles from "./caseDetail.module.css";

type CandidateCase = components["schemas"]["CandidateCase"];

/**
 * 收录卡：确认之后的信息块。只陈述数据库里真实存在的事实，
 * 并按合同明确声明这条候选标准案例还没有进入评测集、也没有触发评测。
 */
export function ConfirmedCard({ candidate }: { candidate: CandidateCase }) {
  return (
    <section className={`${styles.confirmCard} enter`}>
      <span className="state state-green" style={{ justifySelf: "start" }}>
        <span className="dot" />
        已收录
      </span>
      <div className="stack-sm">
        <div className={styles.confirmRow}>
          <span className={styles.confirmKey}>候选标准案例</span>
          <span className={styles.confirmValue}>{candidate.id}</span>
        </div>
        <div className={styles.confirmRow}>
          <span className={styles.confirmKey}>草稿版本</span>
          <span className={styles.confirmValue}>v{candidate.draft_revision}</span>
        </div>
        <div className={styles.confirmRow}>
          <span className={styles.confirmKey}>确认人</span>
          <span className={styles.confirmValue}>{candidate.confirmed_by_username}</span>
        </div>
        {PREVIEW_ENABLED && (
          <div className={styles.confirmRow}>
            <span className={styles.confirmKey}>确认人 ID</span>
            <span className={styles.confirmValue}>{candidate.confirmed_by}</span>
          </div>
        )}
        <div className={styles.confirmRow}>
          <span className={styles.confirmKey}>确认时间</span>
          <span className={styles.confirmValue}>{stamp(candidate.confirmed_at)}</span>
        </div>
      </div>
    </section>
  );
}
