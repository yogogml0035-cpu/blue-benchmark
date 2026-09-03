import type { ReactNode } from "react";
import { ParticleField } from "@/features/auth/particle-field";
import styles from "./layout.module.css";

/**
 * Authentication surface: a full-bleed deterministic particle field behind a
 * right-aligned panel. The panel content is provided by the login/register
 * pages so their forms, copy and submit actions stay distinct.
 */
export default function AuthLayout({ children }: { children: ReactNode }): React.JSX.Element {
  return (
    <div className={styles.surface}>
      <ParticleField />
      <div className={styles.brandArea}>
        <div className={styles.brand}>
          <span className={styles.wordmark} aria-label="AURA">
            {"AURA".split("").map((char, index) => (
              <span key={`${char}-${index}`} aria-hidden="true">
                {char}
              </span>
            ))}
          </span>
          <p className={styles.tagline}>评测管理台</p>
        </div>
      </div>
      <div className={styles.panelWrap}>
        <div className={styles.inner}>
          <section className={styles.panel}>{children}</section>
        </div>
      </div>
    </div>
  );
}
