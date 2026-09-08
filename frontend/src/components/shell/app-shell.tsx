"use client";

import { FolderKanban, LogOut } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import styles from "./app-shell.module.css";

export interface AppShellProps {
  username: string;
  onLogout: () => void;
  loggingOut?: boolean;
  children: React.ReactNode;
}

/**
 * Desktop application chrome: a fixed navigation sidebar plus a content
 * region. The sidebar keeps the BenchMark 240px width and pins the single
 * admin identity with a logout action at the bottom.
 */
export function AppShell({ username, onLogout, loggingOut = false, children }: AppShellProps): React.JSX.Element {
  const pathname = usePathname();

  const navItems = [
    { href: "/evaluation-sets", label: "评测集", icon: FolderKanban },
  ];

  return (
    <div className={styles.shell}>
      <aside className={styles.sidebar}>
        <div className={styles.brandRow}>
          <span className={styles.wordmark} aria-label="蓝标汽车事业 BenchMark 平台">
            蓝标汽车事业 BenchMark 平台
          </span>
        </div>

        <nav className={styles.nav} aria-label="主导航">
          {navItems.map((item) => {
            const active = pathname?.startsWith(item.href) ?? false;
            return (
              <Link
                key={item.href}
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={[styles.navItem, active ? styles.navItemActive : null].join(" ")}
              >
                <item.icon size={18} aria-hidden="true" />
                <span>{item.label}</span>
              </Link>
            );
          })}
        </nav>

        <div className={styles.identity}>
          <div className={styles.avatar} aria-hidden="true">
            {username.slice(0, 1).toUpperCase()}
          </div>
          <span className={styles.username}>{username}</span>
          <button
            type="button"
            className={styles.logout}
            aria-label="退出登录"
            title="退出登录"
            onClick={onLogout}
            disabled={loggingOut}
          >
            <LogOut size={17} aria-hidden="true" />
          </button>
        </div>
      </aside>

      <main className={styles.content}>{children}</main>
    </div>
  );
}
