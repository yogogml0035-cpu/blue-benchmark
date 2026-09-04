import type { ReactNode } from "react";
import styles from "./layout.module.css";

/**
 * Authentication surface: the approved particle-artwork backdrop with the
 * 汽车事业 BenchMark 平台 wordmark pinned top-left. The panel itself is
 * rendered by the login/register pages so each page controls its own
 * geometry — the login panel is fixed to the artwork's reserved area, the
 * register panel flows centered.
 */
export default function AuthLayout({ children }: { children: ReactNode }): React.JSX.Element {
  return (
    <div className={styles.surface}>
      <header className={styles.brand}>汽车事业 BenchMark 平台</header>
      <main className={styles.stage}>{children}</main>
    </div>
  );
}
