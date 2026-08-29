import { useState, type ReactNode } from "react";

import type { components } from "@/src/lib/api/generated";

import styles from "./caseDetail.module.css";

type EvidenceRef = components["schemas"]["EvidenceRef"];

const KIND_LABEL: Record<EvidenceRef["kind"], string> = {
  attachment_excerpt: "材料",
  task_description: "任务说明",
  teacher_answer: "你的回答",
};

/**
 * 原文：证据细节收进条目末尾的行内展开，只在老师想核对时点开。
 * 证据引用在界面上永远只读——人工不能伪造出处。
 */
export function RefsDetail({ refs }: { refs: EvidenceRef[] }) {
  const [open, setOpen] = useState(false);
  if (refs.length === 0) return null;
  return (
    <div className={styles.refs}>
      <button
        aria-expanded={open}
        className={styles.refsLink}
        onClick={() => setOpen((current) => !current)}
        type="button"
      >
        原文
      </button>
      {open && (
        <div className={styles.refsList}>
          {refs.map((ref, index) => (
            <div className={styles.refItem} key={`${ref.source_id}-${index}`}>
              <span className={styles.refHead}>
                {ref.kind ? KIND_LABEL[ref.kind] : ""}
                {ref.locator ? ` · ${ref.locator}` : ""}
              </span>
              {ref.quote && <span className={styles.refQuote}>「{ref.quote}」</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/** 结构字段：字段名 + 正文（或编辑控件），出处跟在正文后面。 */
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
      {label && <span className={styles.fieldName}>{label}</span>}
      {children}
      {refs && refs.length > 0 && <RefsDetail refs={refs} />}
    </div>
  );
}

/** 来源条目：一条正文 + 可选徽标/操作 + 正文末尾的出处。 */
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
  const hasAside = Boolean(badge || actions);
  return (
    <div className={styles.itemRow}>
      {hasAside && (
        <div className={styles.itemHead}>
          <span className={styles.itemMeta}>{badge}</span>
          {actions}
        </div>
      )}
      {children}
      {refs && refs.length > 0 && <RefsDetail refs={refs} />}
    </div>
  );
}

export function ItemText({ children }: { children: ReactNode }) {
  return <p className={styles.fieldText}>{children}</p>;
}
