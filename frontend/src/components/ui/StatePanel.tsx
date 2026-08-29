import type { ReactNode } from "react";

import { Lock, RejectMark, SealMark } from "@/src/components/ui/Glyph";

type Tone = "empty" | "fault" | "locked";

const toneStyle: Record<Tone, { rule: string; tint: string; ink: string }> = {
  empty: { rule: "var(--rule-strong)", tint: "var(--paper-sunken)", ink: "var(--ink-muted)" },
  fault: { rule: "var(--seal)", tint: "var(--tint-seal)", ink: "var(--seal)" },
  locked: { rule: "var(--prov-gap)", tint: "var(--tint-gap)", ink: "var(--prov-gap)" },
};

/**
 * 空 / 报错 / 未授权 共用一张纸：一条色边、一个标记、一句原因、机器码和唯一的下一步。
 * 四个页面复用同一块，是为了让“下一步该做什么”在任何失败下都出现在同一个位置。
 */
export function StatePanel({
  tone = "empty",
  title,
  description,
  code,
  glyph,
  actions,
  children,
}: {
  tone?: Tone;
  title: string;
  description?: ReactNode;
  code?: string;
  glyph?: ReactNode;
  actions?: ReactNode;
  children?: ReactNode;
}) {
  const style = toneStyle[tone];
  const mark =
    glyph ??
    (tone === "locked" ? <Lock size={18} /> : tone === "fault" ? <RejectMark size={18} /> : <SealMark size={18} />);
  return (
    <section
      className="sheet enter"
      style={{ borderTop: `2px solid ${style.rule}`, overflow: "hidden" }}
    >
      <div
        className="stack"
        style={{ padding: "var(--s-8) var(--s-6)", justifyItems: "center", textAlign: "center" }}
      >
        <span
          aria-hidden="true"
          style={{
            display: "grid",
            placeItems: "center",
            width: 40,
            height: 40,
            borderRadius: "var(--r-sm)",
            background: style.tint,
            color: style.ink,
          }}
        >
          {mark}
        </span>
        <div className="stack-sm" style={{ maxWidth: 460 }}>
          <h2 className="doc-title-sm">{title}</h2>
          {description && <p className="secondary">{description}</p>}
          {code && <p className="mono faint">{code}</p>}
        </div>
        {children}
        {actions && <div className="row" style={{ justifyContent: "center" }}>{actions}</div>}
      </div>
    </section>
  );
}
