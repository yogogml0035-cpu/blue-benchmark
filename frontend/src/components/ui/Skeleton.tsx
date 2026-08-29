/** 骨架：占位块必须撑住最终版面的高度，刷新时不能让内容跳动。 */
export function SkeletonLine({
  width = "100%",
  height = 12,
}: {
  width?: string | number;
  height?: number;
}) {
  return <div className="skeleton" style={{ width, height }} />;
}

export function SkeletonBlock({ height = 96 }: { height?: number }) {
  return <div className="skeleton" style={{ height, borderRadius: "var(--r-chip)" }} />;
}

/** 一段带首行标题的骨架文本，用来占住草稿正文的位置。 */
export function SkeletonClaim({ lines = 2 }: { lines?: number }) {
  return (
    <div className="stack-sm">
      <SkeletonLine height={11} width="88px" />
      {Array.from({ length: lines }, (_, index) => (
        <SkeletonLine key={index} width={index === lines - 1 ? "62%" : "100%"} />
      ))}
    </div>
  );
}
