"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";

/**
 * 原型状态预演：用 `?preview=` 把页面钉在某一个状态上，方便逐个验收
 * loading / empty / success / error / unauthorized。生产构建下整块失效，
 * 预演数据只用 OpenAPI 生成的类型构造，不引入第二套数据结构。
 */
export const PREVIEW_STATES = [
  "loading",
  "empty",
  "success",
  "error",
  "unauthorized",
  "forbidden",
  "not_found",
  "question",
  "review",
] as const;

export type PreviewState = (typeof PREVIEW_STATES)[number];

export const PREVIEW_ENABLED = process.env.NODE_ENV !== "production";

const LABELS: Record<PreviewState, string> = {
  loading: "loading",
  empty: "empty",
  success: "success",
  error: "error",
  unauthorized: "unauthorized",
  forbidden: "forbidden",
  not_found: "not-found",
  question: "提问",
  review: "审改",
};

export function usePreviewState(): PreviewState | null {
  const params = useSearchParams();
  if (!PREVIEW_ENABLED) return null;
  const value = params.get("preview");
  return PREVIEW_STATES.find((state) => state === value) ?? null;
}

export function PreviewBar({ states }: { states: readonly PreviewState[] }) {
  const pathname = usePathname();
  const active = usePreviewState();
  if (!PREVIEW_ENABLED) return null;
  return (
    <div className="preview-bar">
      <span>状态预演</span>
      <Link data-active={active === null} href={pathname}>
        实况
      </Link>
      {states.map((state) => (
        <Link
          data-active={active === state}
          href={`${pathname}?preview=${state}`}
          key={state}
        >
          {LABELS[state]}
        </Link>
      ))}
    </div>
  );
}
