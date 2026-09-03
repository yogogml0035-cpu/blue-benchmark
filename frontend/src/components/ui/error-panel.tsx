import { AlertTriangle } from "lucide-react";
import type { ReactNode } from "react";
import styles from "./error-panel.module.css";

export interface ErrorPanelProps {
  title?: string;
  message: string;
  /** A secondary action, e.g. a retry button. */
  action?: ReactNode;
}

/**
 * Inline, context-bound error surface.
 *
 * Recoverable business errors stay in the panel where the action happened
 * instead of disappearing into a transient toast.
 */
export function ErrorPanel({ title = "操作未成功", message, action }: ErrorPanelProps): React.JSX.Element {
  return (
    <div className={styles.panel} role="alert">
      <div className={styles.icon}>
        <AlertTriangle size={18} aria-hidden="true" />
      </div>
      <div className={styles.content}>
        <p className={styles.title}>{title}</p>
        <p className={styles.message}>{message}</p>
      </div>
      {action ? <div className={styles.action}>{action}</div> : null}
    </div>
  );
}
