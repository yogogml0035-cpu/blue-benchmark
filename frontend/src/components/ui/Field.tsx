import type { ReactNode } from "react";

/** 字段：标签 + 控件 + 字段级校注。错误直接落在对应字段，不堆到表单顶部。 */
export function Field({
  label,
  hint,
  error,
  htmlFor,
  children,
}: {
  label: string;
  hint?: string;
  error?: string;
  htmlFor?: string;
  children: ReactNode;
}) {
  return (
    <div className="field">
      <label className="field-label" htmlFor={htmlFor}>
        <span>{label}</span>
        {hint && <span className="field-hint">{hint}</span>}
      </label>
      {children}
      {error && (
        <p className="field-error">
          <span aria-hidden="true">↳</span>
          <span>{error}</span>
        </p>
      )}
    </div>
  );
}
