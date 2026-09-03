import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import styles from "./empty-state.module.css";

export interface EmptyStateProps {
  icon?: LucideIcon;
  title: string;
  description?: string;
  action?: ReactNode;
}

export function EmptyState({ icon: Icon, title, description, action }: EmptyStateProps): React.JSX.Element {
  return (
    <div className={styles.empty}>
      {Icon ? (
        <div className={styles.icon}>
          <Icon size={26} aria-hidden="true" />
        </div>
      ) : null}
      <h3 className={styles.title}>{title}</h3>
      {description ? <p className={styles.description}>{description}</p> : null}
      {action ? <div className={styles.action}>{action}</div> : null}
    </div>
  );
}
