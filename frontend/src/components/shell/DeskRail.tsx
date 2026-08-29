import Link from "next/link";
import type { ReactNode } from "react";

import { SealMark } from "@/src/components/ui/Glyph";

export type Crumb = { label: string; href?: string };

/**
 * 桌沿：全站唯一的持久化导航。本闭环只有四条路由且流程是线性的，
 * 侧边栏在这里只会是假的脚手架，所以导航由“卷宗面包屑 + 状态进程条”承担。
 */
export function DeskRail({ crumbs = [], right }: { crumbs?: Crumb[]; right?: ReactNode }) {
  return (
    <header className="rail">
      <div className="rail-group" style={{ overflow: "hidden" }}>
        <Link
          className="rail-group"
          href="/workspaces"
          style={{
            color: "var(--ink)",
            textDecoration: "none",
            gap: "var(--s-2)",
            whiteSpace: "nowrap",
            flex: "none",
          }}
        >
          <span style={{ color: "var(--seal)", display: "flex" }}>
            <SealMark size={17} />
          </span>
          <span style={{ fontWeight: 600, letterSpacing: "-0.01em" }}>审校台</span>
        </Link>
        {crumbs.length > 0 && (
          <nav
            aria-label="卷宗位置"
            className="rail-group"
            style={{ gap: "var(--s-2)", overflow: "hidden" }}
          >
            {crumbs.map((crumb, index) => (
              <span
                className="rail-group"
                key={`${crumb.label}-${index}`}
                style={{ gap: "var(--s-2)", minWidth: 0 }}
              >
                <span aria-hidden="true" className="faint">
                  ›
                </span>
                {crumb.href ? (
                  <Link
                    href={crumb.href}
                    style={{
                      color: "var(--ink-secondary)",
                      fontSize: "var(--t-13)",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {crumb.label}
                  </Link>
                ) : (
                  <span
                    style={{
                      color: "var(--ink-secondary)",
                      fontSize: "var(--t-13)",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                      maxWidth: "38ch",
                    }}
                    title={crumb.label}
                  >
                    {crumb.label}
                  </span>
                )}
              </span>
            ))}
          </nav>
        )}
      </div>
      {right && <div className="rail-group">{right}</div>}
    </header>
  );
}
