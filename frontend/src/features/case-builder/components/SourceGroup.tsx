import type { ReactNode } from "react";

import { Chevron } from "@/src/components/ui/Glyph";
import type { components } from "@/src/lib/api/generated";

import styles from "./caseDetail.module.css";

type EvidenceRef = components["schemas"]["EvidenceRef"];

const KIND_LABEL: Record<EvidenceRef["kind"], string> = {
  attachment_excerpt: "材料",
  task_description: "任务说明",
  teacher_answer: "你的回答",
};

/**
 * 查看原文：证据细节收进内联展开层，只在老师想核对时展开。
 * 证据引用在界面上永远只读——人工不能伪造出处。
 */
export function RefsDetail({ refs }: { refs: EvidenceRef[] }) {
  if (refs.length === 0) return null;
  return (
    <details className={styles.refs}>
      <summary className={styles.refsSummary}>
        <Chevron size={11} className={styles.refsChevron} />
        查看原文（{refs.length}）
      </summary>
      <div className={styles.refsList}>
        {refs.map((ref, index) => (
          <div className={styles.refItem} key={`${ref.source_id}-${index}`}>
            <span className={styles.refHead}>
              <span className={styles.refKind}>{KIND_LABEL[ref.kind]}</span>
              {ref.locator && <span>{ref.locator}</span>}
            </span>
            {ref.quote && <span className={styles.refQuote}>「{ref.quote}」</span>}
          </div>
        ))}
      </div>
    </details>
  );
}

/** 结构字段：字段名 + 正文（或编辑控件），可选证据。 */
export function FieldRow({
  label,
  refs,
  children,
}: {
  label: string;
  refs?: EvidenceRef[];
  children: ReactNode;
}) {
  return (
    <div className={styles.fieldRow}>
      <div className={styles.fieldLabelRow}>
        <span className={styles.fieldName}>{label}</span>
        {refs && refs.length > 0 && <RefsDetail refs={refs} />}
      </div>
      {children}
    </div>
  );
}

/** 来源条目：一条正文 + 可选徽标/操作 + 可选证据。 */
export function SourceItem({
  refs,
  badge,
  actions,
  children,
}: {
  refs?: EvidenceRef[];
  badge?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
}) {
  const hasAside = Boolean(badge || actions || (refs && refs.length > 0));
  return (
    <div className={styles.itemRow}>
      {hasAside && (
        <div className={styles.itemHead}>
          <span className={styles.itemMeta}>
            {badge}
            {refs && refs.length > 0 && <RefsDetail refs={refs} />}
          </span>
          {actions}
        </div>
      )}
      {children}
    </div>
  );
}

/** 分组区：灰色小标题 + 可选说明 + 条目列表。分组本身就是来源信号，不再用颜色区分。 */
export function GroupSection({
  title,
  aside,
  children,
}: {
  title: string;
  aside?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className={styles.group}>
      <div className={styles.groupHead}>
        <span className="section-label">{title}</span>
        {aside}
      </div>
      {children}
    </section>
  );
}

export function ItemText({ children }: { children: ReactNode }) {
  return <p className={styles.fieldText}>{children}</p>;
}
