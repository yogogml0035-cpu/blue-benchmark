"use client";

import { FolderKanban, LogOut, PanelLeftClose, PanelLeftOpen } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import styles from "./app-shell.module.css";

export interface AppShellProps {
  username: string;
  onLogout: () => void;
  loggingOut?: boolean;
  children: React.ReactNode;
}

/**
 * Desktop application chrome: a collapsible navigation rail plus a content
 * region. The rail keeps the BenchMark 232px / 80px collapsed widths and pins
 * the single admin identity with a logout action at the bottom.
 */
export function AppShell({ username, onLogout, loggingOut = false, children }: AppShellProps): React.JSX.Element {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);

  const navItems = [
    { href: "/evaluation-sets", label: "评测集", icon: FolderKanban },
  ];

  return (
    <div className={styles.shell}>
      <aside className={[styles.sidebar, collapsed ? styles.collapsed : null].join(" ")}>
        <div className={styles.brandRow}>
          <span className={styles.wordmark} aria-label="汽车事业 BenchMark 平台">
            <span className={styles.wordmarkFull} aria-hidden="true">
              汽车事业 BenchMark 平台
            </span>
            <span className={styles.wordmarkMark} aria-hidden="true">
              汽
            </span>
          </span>
          <button
            type="button"
            className={styles.collapseToggle}
            aria-label={collapsed ? "展开侧栏" : "折叠侧栏"}
            aria-pressed={collapsed}
            onClick={() => setCollapsed((value) => !value)}
          >
            {collapsed ? <PanelLeftOpen size={18} aria-hidden="true" /> : <PanelLeftClose size={18} aria-hidden="true" />}
          </button>
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
                {/* Keep a programmatically readable label even when collapsed;
                    a title attribute alone is unreliable for screen readers. */}
                <span className={collapsed ? styles.navLabelHidden : undefined}>
                  {item.label}
                </span>
              </Link>
            );
          })}
        </nav>

        <div className={styles.identity}>
          <div className={styles.avatar} aria-hidden="true">
            {username.slice(0, 1).toUpperCase()}
          </div>
          {!collapsed ? <span className={styles.username}>{username}</span> : null}
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
