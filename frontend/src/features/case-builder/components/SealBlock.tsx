import type { components } from "@/src/lib/api/generated";
import { stamp } from "@/src/lib/format";

import styles from "./caseBuilder.module.css";

type CandidateCase = components["schemas"]["CandidateCase"];

/**
 * 落章：确认之后的签署块。只陈述数据库里真实存在的事实，
 * 并按合同明确声明候选用例还没有进入回归集、也没有触发评测。
 */
export function SealBlock({ candidate }: { candidate: CandidateCase }) {
  return (
    <div className={`${styles.seal} enter`}>
      <div aria-hidden="true" className={styles.sealRing}>
        已
        <br />
        确认
      </div>
      <div className={styles.sealFacts}>
        <div className={styles.sealRow}>
          <span className={styles.sealKey}>候选用例</span>
          <span className={styles.sealValue}>{candidate.id}</span>
        </div>
        <div className={styles.sealRow}>
          <span className={styles.sealKey}>草案修订</span>
          <span className={styles.sealValue}>第 {candidate.draft_revision} 校</span>
        </div>
        <div className={styles.sealRow}>
          <span className={styles.sealKey}>确认人</span>
          <span className={styles.sealValue}>{candidate.confirmed_by}</span>
        </div>
        <div className={styles.sealRow}>
          <span className={styles.sealKey}>确认时间</span>
          <span className={styles.sealValue}>{stamp(candidate.confirmed_at)}</span>
        </div>
      </div>
    </div>
  );
}
