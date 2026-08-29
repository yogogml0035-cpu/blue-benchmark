import type { CSSProperties, ReactNode } from "react";

import type { components } from "@/src/lib/api/generated";

import styles from "./caseBuilder.module.css";

type EvidenceRef = components["schemas"]["EvidenceRef"];

/**
 * 来源墨色是本产品的签名：每一条主张左侧的那条墨线颜色说明“是谁说的”。
 * 墨=输入材料中的事实，朱=老师的判断，蓝=AI 推断的候选，琥珀=未知缺口，
 * 中性=草案的结构字段。颜色在这里承担证据链职责，不是装饰。
 */
export type ClaimSource = "fact" | "teacher" | "ai" | "gap" | "draft";

const SOURCE: Record<ClaimSource, { ink: string; label: string }> = {
  fact: { ink: "var(--prov-fact)", label: "输入事实" },
  teacher: { ink: "var(--prov-teacher)", label: "老师判断" },
  ai: { ink: "var(--prov-ai)", label: "AI 候选" },
  gap: { ink: "var(--prov-gap)", label: "未知缺口" },
  draft: { ink: "var(--rule-strong)", label: "草案字段" },
};

const KIND_LABEL: Record<EvidenceRef["kind"], string> = {
  attachment_excerpt: "附件",
  task_description: "说明",
  teacher_answer: "回答",
};

/**
 * 引注边栏。`expect` 为真表示这一条本应带出处，缺失时明确写出「无引注」；
 * 结构字段不承载证据，边栏留白即可，避免一列重复的「无引注」变成噪声。
 */
export function CitationGutter({ refs, expect }: { refs: EvidenceRef[]; expect: boolean }) {
  if (refs.length === 0) {
    return (
      <aside className={styles.gutter}>
        {expect && <span className={styles.gutterEmpty}>无引注</span>}
      </aside>
    );
  }
  return (
    <aside className={styles.gutter}>
      {refs.map((ref, index) => (
        <div className={styles.cite} key={`${ref.source_id}-${index}`}>
          <span className={styles.citeHead}>
            <span className={styles.citeKind}>{KIND_LABEL[ref.kind]}</span>
            <span>{ref.locator ?? ref.source_id.slice(0, 8)}</span>
          </span>
          {ref.quote && (
            <p className={styles.citeQuote} title={ref.quote}>
              「{ref.quote}」
            </p>
          )}
        </div>
      ))}
    </aside>
  );
}

/** 一条主张：左侧来源墨线、字段名、正文（或编辑控件）、右侧引注边栏。 */
export function ClaimBlock({
  source,
  field,
  refs = [],
  badge,
  actions,
  children,
}: {
  source: ClaimSource;
  field: string;
  refs?: EvidenceRef[];
  badge?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
}) {
  const meta = SOURCE[source];
  return (
    <div className={styles.claim} style={{ "--claim-ink": meta.ink } as CSSProperties}>
      <div className={styles.claimBody}>
        <div className={styles.claimHead}>
          <span className={styles.claimField}>{field}</span>
          <span className={styles.claimMeta}>
            {badge}
            <span className={styles.claimLabel}>{meta.label}</span>
            {actions}
          </span>
        </div>
        {children}
      </div>
      <CitationGutter expect={source !== "draft"} refs={refs} />
    </div>
  );
}

export function ClaimText({ children }: { children: ReactNode }) {
  return <p className={styles.claimText}>{children}</p>;
}

/** 来源图例：进入校订时先说明四种墨色分别代表什么。 */
export function ProvenanceLegend() {
  const order: ClaimSource[] = ["fact", "teacher", "ai", "gap"];
  return (
    <div className="row" style={{ gap: "var(--s-4)" }}>
      {order.map((key) => (
        <span
          className="row"
          key={key}
          style={{ gap: 6, fontSize: "var(--t-11)", color: "var(--ink-muted)" }}
        >
          <span
            aria-hidden="true"
            style={{ width: 3, height: 12, background: SOURCE[key].ink, borderRadius: 1 }}
          />
          {SOURCE[key].label}
        </span>
      ))}
    </div>
  );
}
