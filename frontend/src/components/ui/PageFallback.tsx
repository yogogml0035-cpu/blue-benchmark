import { SkeletonLine } from "@/src/components/ui/Skeleton";

/**
 * Suspense 兜底：`useSearchParams` 会把页面推到客户端边界，
 * 这一层保证边界解析期间就已经是最终版面的骨架，而不是白屏。
 */
export function PageFallback({ width = "page-mid" }: { width?: "page-narrow" | "page-mid" | "page-wide" }) {
  return (
    <main aria-busy="true" className={`page ${width} stack-lg`}>
      <div className="stack-sm">
        <SkeletonLine height={11} width="72px" />
        <SkeletonLine height={30} width="46%" />
        <SkeletonLine height={14} width="68%" />
      </div>
      <section className="sheet sheet-pad stack">
        <SkeletonLine height={38} />
        <SkeletonLine height={38} />
        <SkeletonLine height={96} />
      </section>
    </main>
  );
}
