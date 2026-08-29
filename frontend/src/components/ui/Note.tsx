import type { ReactNode } from "react";

type Tone = "fail" | "amber" | "green" | "info";

/** 提示块：安静的弱底色 + 语义色圆点 + 一句原因。机器码原样展示，便于验收对照。 */
export function Note({
  tone = "info",
  title,
  code,
  children,
}: {
  tone?: Tone;
  title?: string;
  /** 机器可读错误码，以等宽字呈现，便于验收时对照合同。 */
  code?: string;
  children?: ReactNode;
}) {
  return (
    <div className={`note note-${tone}`} role={tone === "fail" ? "alert" : undefined}>
      <span aria-hidden="true" className="note-mark">
        <span className="dot" />
      </span>
      <div className="stack-sm">
        {title && <div className="note-title">{title}</div>}
        {children && <div>{children}</div>}
        {code && (
          <div className="mono" style={{ opacity: 0.72 }}>
            {code}
          </div>
        )}
      </div>
    </div>
  );
}
