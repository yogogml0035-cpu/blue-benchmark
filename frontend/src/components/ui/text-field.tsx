"use client";

import { Eye, EyeOff } from "lucide-react";
import { useId, useState, type InputHTMLAttributes } from "react";
import styles from "./text-field.module.css";

export interface TextFieldProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string;
  /** Error text rendered beneath the field and associated for screen readers. */
  error?: string | null;
  /** Adds a show/hide control; used for password inputs. */
  revealable?: boolean;
  hint?: string;
}

/**
 * BenchMark text input.
 *
 * The label, control, hint and error are wired together with `aria-describedby`
 * so validation messages stay programmatically associated with the field.
 */
export function TextField({
  label,
  error,
  revealable = false,
  hint,
  id,
  type = "text",
  className,
  ...rest
}: TextFieldProps): React.JSX.Element {
  const autoId = useId();
  const fieldId = id ?? autoId;
  const errorId = `${fieldId}-error`;
  const hintId = `${fieldId}-hint`;
  const [revealed, setRevealed] = useState(false);

  const effectiveType = revealable ? (revealed ? "text" : "password") : type;
  const describedBy =
    [error ? errorId : null, hint ? hintId : null].filter(Boolean).join(" ") || undefined;

  return (
    <div className={styles.field}>
      <label className={styles.label} htmlFor={fieldId}>
        {label}
      </label>
      <div className={styles.control}>
        <input
          id={fieldId}
          type={effectiveType}
          className={[styles.input, error ? styles.invalid : null, className]
            .filter(Boolean)
            .join(" ")}
          aria-invalid={error ? true : undefined}
          aria-describedby={describedBy}
          {...rest}
        />
        {revealable ? (
          <button
            type="button"
            className={styles.reveal}
            aria-label={revealed ? "隐藏密码" : "显示密码"}
            aria-pressed={revealed}
            onClick={() => setRevealed((value) => !value)}
          >
            {revealed ? <EyeOff size={16} aria-hidden="true" /> : <Eye size={16} aria-hidden="true" />}
          </button>
        ) : null}
      </div>
      {hint && !error ? (
        <p className={styles.hint} id={hintId}>
          {hint}
        </p>
      ) : null}
      {error ? (
        <p className={styles.error} id={errorId} role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}
