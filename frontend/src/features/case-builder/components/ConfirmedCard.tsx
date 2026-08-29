import type { components } from "@/src/lib/api/generated";
import { stamp } from "@/src/lib/format";
import { PREVIEW_ENABLED } from "@/src/lib/preview/preview";

import styles from "./caseDetail.module.css";

type CandidateCase = components["schemas"]["CandidateCase"];

/**
 * 已定稿的题卡收尾：版本 + 签名行。加入评测集、版本发布属于后续阶段，
 * 不在这张卡里声明——卡只说「它定了」。
 */
export function ConfirmedCard({ candidate }: { candidate: CandidateCase }) {
  return (
    <section className={`${styles.confirmCard} enter`}>
      <div className={styles.confirmLead}>
        <span aria-hidden="true" className="dot" style={{ background: "var(--green)" }} />
        题 v{candidate.draft_revision} · 已定稿
      </div>
      <div className={styles.confirmSign}>
        <strong>{candidate.confirmed_by_username}</strong>
        <span>{stamp(candidate.confirmed_at)}</span>
        {PREVIEW_ENABLED && <span className="mono faint">{candidate.id.slice(0, 8)}</span>}
      </div>
    </section>
  );
}
