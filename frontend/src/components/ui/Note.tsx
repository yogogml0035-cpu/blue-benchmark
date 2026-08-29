import type { ReactNode } from "react";

import { AlertMark, CheckMark, InfoMark, QueryMark } from "@/src/components/ui/Glyph";

type Tone = "fail" | "gap" | "cleared" | "info";

const TONE: Record<Tone, { className: string; mark: ReactNode }> = {
  fail: { className: "note-fail", mark: <AlertMark /> },
  gap: { className: "note-gap", mark: <QueryMark /> },
  cleared: { className: "note-cleared", mark: <CheckMark /> },
  info: { className: "note-info", mark: <InfoMark /> },
};

/** 校注：纸面上的编辑批注，用来表达错误、缺口、已核验和普通提示。 */
export function Note({
  tone = "info",
  title,
  code,
  children,
}: {
  tone?: Tone;
  title?: string;
  /** 机器可读错误码，按合同以等宽字呈现，便于验收时对照。 */
  code?: string;
  children?: ReactNode;
}) {
  const meta = TONE[tone];
  return (
    <div className={`note ${meta.className}`} role={tone === "fail" ? "alert" : undefined}>
      <span className="note-mark">{meta.mark}</span>
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
