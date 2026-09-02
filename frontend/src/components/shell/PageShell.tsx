import type { ReactNode } from "react";

import { PreviewBar, type PreviewBarState } from "@/src/lib/preview/preview";

import type { Crumb } from "./DeskRail";
import { DeskRail } from "./DeskRail";

/**
 * 页面壳：顶栏 + 状态预演条 + 版面容器。除登录页外全站复用，
 * 版面宽度只从这里给（page-narrow / page-mid / page-wide / page-max）。
 * 工作台这类自带全宽布局（侧栏 + 画布）的页面用 chromeOnly 只复用顶栏与预演条。
 */
export function PageShell({
  crumbs,
  right,
  previewStates,
  mainClassName,
  chromeOnly = false,
  children,
}: {
  crumbs?: Crumb[];
  right?: ReactNode;
  previewStates?: readonly PreviewBarState[];
  mainClassName?: string;
  chromeOnly?: boolean;
  children: ReactNode;
}) {
  return (
    <>
      <DeskRail crumbs={crumbs} right={right} />
      {previewStates && <PreviewBar states={previewStates} />}
      {chromeOnly ? (
        children
      ) : (
        <main className={mainClassName ? `page ${mainClassName}` : "page"}>{children}</main>
      )}
    </>
  );
}
