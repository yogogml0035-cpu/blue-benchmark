import Link from "next/link";
import type { ReactNode } from "react";

export type Crumb = { label: string; href?: string };

/**
 * 顶栏：全站唯一的持久化导航。本闭环只有四条路由且流程是线性的，
 * 侧边栏在这里只会是假的脚手架，所以导航由“场景面包屑 + 状态进程条”承担。
 */
export function DeskRail({ crumbs = [], right }: { crumbs?: Crumb[]; right?: ReactNode }) {
  return (
    <header className="rail">
      <div className="rail-group" style={{ overflow: "hidden" }}>
        <Link
          href="/workspaces"
          style={{
            color: "var(--text)",
            textDecoration: "none",
            whiteSpace: "nowrap",
            flex: "none",
            fontWeight: 650,
            fontSize: "var(--t-15)",
            letterSpacing: "-0.01em",
          }}
        >
          评测集平台
        </Link>
        {crumbs.length > 0 && (
          <nav aria-label="当前位置" className="rail-group" style={{ gap: "var(--s-2)", overflow: "hidden" }}>
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
                      color: "var(--text-2)",
                      fontSize: "var(--t-13)",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {crumb.label}
                  </Link>
                ) : (
                  <span
                    style={{
                      color: "var(--text-2)",
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
