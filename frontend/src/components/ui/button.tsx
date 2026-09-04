"use client";

import { Loader2 } from "lucide-react";
import type { ButtonHTMLAttributes } from "react";
import styles from "./button.module.css";

type Variant = "primary" | "secondary" | "ghost" | "danger";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  /** Shows a spinner and blocks re-submission while keeping the size stable. */
  loading?: boolean;
}

const VARIANT_CLASS: Record<Variant, string> = {
  primary: styles.primary,
  secondary: styles.secondary,
  ghost: styles.ghost,
  danger: styles.danger,
};

/**
 * BenchMark button.
 *
 * Async actions pass `loading`; the control keeps its dimensions and becomes
 * non-interactive so layouts never jump during submission.
 */
export function Button({
  variant = "primary",
  loading = false,
  disabled,
  className,
  children,
  type = "button",
  ...rest
}: ButtonProps): React.JSX.Element {
  const classes = [styles.button, VARIANT_CLASS[variant], className]
    .filter(Boolean)
    .join(" ");
  return (
    <button
      type={type}
      className={classes}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...rest}
    >
      {loading ? <Loader2 className={styles.spinner} aria-hidden="true" /> : null}
      <span>{children}</span>
    </button>
  );
}
