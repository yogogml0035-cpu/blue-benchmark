import type { ReactNode } from "react";
import styles from "./status-badge.module.css";

export type StatusTone = "neutral" | "info" | "success" | "warning" | "danger" | "purple";

export interface StatusBadgeProps {
  tone?: StatusTone;
  children: ReactNode;
}

const TONE_CLASS: Record<StatusTone, string> = {
  neutral: styles.neutral,
  info: styles.info,
  success: styles.success,
  warning: styles.warning,
  danger: styles.danger,
  purple: styles.purple,
};

export function StatusBadge({ tone = "neutral", children }: StatusBadgeProps): React.JSX.Element {
  return <span className={[styles.badge, TONE_CLASS[tone]].join(" ")}>{children}</span>;
}
