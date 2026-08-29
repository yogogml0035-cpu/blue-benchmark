import type { ReactNode } from "react";

type Tone = "empty" | "fault" | "locked";

const toneStyle: Record<Tone, { dot: string; tint: string }> = {
  empty: { dot: "var(--text-3)", tint: "rgb(0 0 0 / 4%)" },
  fault: { dot: "var(--red)", tint: "var(--red-tint)" },
  locked: { dot: "var(--amber)", tint: "var(--amber-tint)" },
};

/**
 * 空 / 报错 / 未授权 共用一张卡片：一个语义色圆点、一句原因、机器码和唯一的下一步。
 * 四个页面复用同一块，是为了让“下一步该做什么”在任何失败下都出现在同一个位置。
 */
export function StatePanel({
  tone = "empty",
  title,
  description,
  code,
  actions,
  children,
}: {
  tone?: Tone;
  title: string;
  description?: ReactNode;
  code?: string;
  actions?: ReactNode;
  children?: ReactNode;
}) {
  const style = toneStyle[tone];
  return (
    <section className="sheet enter">
      <div
        className="stack"
        style={{ padding: "var(--s-10) var(--s-6)", justifyItems: "center", textAlign: "center" }}
      >
        <span
          aria-hidden="true"
          style={{
            display: "grid",
            placeItems: "center",
            width: 36,
            height: 36,
            borderRadius: "50%",
            background: style.tint,
          }}
        >
          <span style={{ width: 8, height: 8, borderRadius: "50%", background: style.dot }} />
        </span>
        <div className="stack-sm" style={{ maxWidth: 460 }}>
          <h2 className="doc-title-sm">{title}</h2>
          {description && <p className="secondary" style={{ fontSize: "var(--t-14)" }}>{description}</p>}
          {code && <p className="mono faint">{code}</p>}
        </div>
        {children}
        {actions && <div className="row" style={{ justifyContent: "center" }}>{actions}</div>}
      </div>
    </section>
  );
}
