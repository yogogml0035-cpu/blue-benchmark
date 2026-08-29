/**
 * 全站只保留三个功能性线性图标：1.5px 描边、16px 画布、currentColor。
 * 苹果极简方向下，图标只承担「展开/收起」「删除」「满足」这三种动作语义，
 * 不再有任何隐喻性标记（印章、锁、批注圈一律不出现）。
 */
type GlyphProps = { size?: number; className?: string };

function svg(size: number, className: string | undefined, children: React.ReactNode) {
  return (
    <svg
      aria-hidden="true"
      className={className}
      fill="none"
      height={size}
      stroke="currentColor"
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth="1.5"
      viewBox="0 0 16 16"
      width={size}
    >
      {children}
    </svg>
  );
}

export function Chevron({ size = 14, className }: GlyphProps) {
  return svg(size, className, <path d="M5 6.5L8 9.5l3-3" />);
}

export function Cross({ size = 14, className }: GlyphProps) {
  return svg(size, className, <path d="M4 4l8 8M12 4l-8 8" />);
}

export function Check({ size = 14, className }: GlyphProps) {
  return svg(size, className, <path d="M3 8.5l3.2 3.2L13 4.8" />);
}
