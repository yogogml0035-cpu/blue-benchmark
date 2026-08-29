/**
 * 全站只用这一组线性图标：1.5px 描边、16px 画布、currentColor。
 * 没有引入图标库，因为原型只需要不到十个标记。
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

/** 印章：产品标记，也用在落章区 */
export function SealMark({ size = 18, className }: GlyphProps) {
  return (
    <svg
      aria-hidden="true"
      className={className}
      height={size}
      viewBox="0 0 20 20"
      width={size}
    >
      <rect
        fill="none"
        height="16"
        rx="3.5"
        stroke="currentColor"
        strokeWidth="1.6"
        width="16"
        x="2"
        y="2"
      />
      <path
        d="M6.2 10.4l2.5 2.5 5-5.6"
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.7"
      />
    </svg>
  );
}

/** 退件章：和印章同一个外框，里面换成叉，用于失败与退回。 */
export function RejectMark({ size = 18, className }: GlyphProps) {
  return (
    <svg
      aria-hidden="true"
      className={className}
      height={size}
      viewBox="0 0 20 20"
      width={size}
    >
      <rect
        fill="none"
        height="16"
        rx="3.5"
        stroke="currentColor"
        strokeWidth="1.6"
        width="16"
        x="2"
        y="2"
      />
      <path
        d="M7.2 7.2l5.6 5.6M12.8 7.2l-5.6 5.6"
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeWidth="1.7"
      />
    </svg>
  );
}

/**
 * 校注标记：一套同族的圆形编辑标记，用在 `Note` 的标记列。
 * 用画出来的圆形标记而不是裸标点——裸标点看着像误入的字符，不像刻意的批注。
 */
function markSvg(size: number, className: string | undefined, children: React.ReactNode) {
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
      <circle cx="8" cy="8" r="6.15" />
      {children}
    </svg>
  );
}

/** 感叹标记：失败、退件、被拒的提交 */
export function AlertMark({ size = 15, className }: GlyphProps) {
  return markSvg(
    size,
    className,
    <>
      <path d="M8 4.7v4.05" />
      <path d="M8 11.35h.01" strokeWidth="1.8" />
    </>,
  );
}

/** 疑问标记：证据缺口、需要老师补答的地方 */
export function QueryMark({ size = 15, className }: GlyphProps) {
  return markSvg(
    size,
    className,
    <>
      <path d="M6.15 6.35a1.9 1.9 0 013.75.4c0 1.25-1.9 1.5-1.9 2.7" />
      <path d="M8 11.5h.01" strokeWidth="1.8" />
    </>,
  );
}

/** 核验标记：已确认、已通过 */
export function CheckMark({ size = 15, className }: GlyphProps) {
  return markSvg(size, className, <path d="M5.4 8.2l1.9 1.9 3.4-4" />);
}

/** 说明标记：中性提示 */
export function InfoMark({ size = 15, className }: GlyphProps) {
  return markSvg(
    size,
    className,
    <>
      <path d="M8 4.9h.01" strokeWidth="1.8" />
      <path d="M8 7.4v3.85" />
    </>,
  );
}

export function ArrowRight({ size = 14, className }: GlyphProps) {
  return svg(size, className, <path d="M3 8h10M9.5 4.5L13 8l-3.5 3.5" />);
}

export function ArrowLeft({ size = 14, className }: GlyphProps) {
  return svg(size, className, <path d="M13 8H3M6.5 4.5L3 8l3.5 3.5" />);
}

export function Check({ size = 14, className }: GlyphProps) {
  return svg(size, className, <path d="M3 8.5l3.2 3.2L13 4.8" />);
}

export function Cross({ size = 14, className }: GlyphProps) {
  return svg(size, className, <path d="M4 4l8 8M12 4l-8 8" />);
}

export function Plus({ size = 14, className }: GlyphProps) {
  return svg(size, className, <path d="M8 3.5v9M3.5 8h9" />);
}

export function Refresh({ size = 14, className }: GlyphProps) {
  return svg(
    size,
    className,
    <>
      <path d="M13.2 7A5.2 5.2 0 003.4 5.6" />
      <path d="M2.8 9A5.2 5.2 0 0012.6 10.4" />
      <path d="M3.3 2.6v3h3M12.7 13.4v-3h-3" />
    </>,
  );
}

export function FileMark({ size = 14, className }: GlyphProps) {
  return svg(
    size,
    className,
    <>
      <path d="M9 1.8H4.2a1 1 0 00-1 1v10.4a1 1 0 001 1h7.6a1 1 0 001-1V5.6z" />
      <path d="M9 1.8v3.8h3.8" />
    </>,
  );
}

export function Upload({ size = 14, className }: GlyphProps) {
  return svg(
    size,
    className,
    <>
      <path d="M8 10.5V2.8M5 5.8L8 2.8l3 3" />
      <path d="M2.8 10v2.4a1 1 0 001 1h8.4a1 1 0 001-1V10" />
    </>,
  );
}

export function Lock({ size = 14, className }: GlyphProps) {
  return svg(
    size,
    className,
    <>
      <rect height="7" rx="1" width="10" x="3" y="7" />
      <path d="M5.5 7V5.2a2.5 2.5 0 015 0V7" />
    </>,
  );
}

export function Chevron({ size = 14, className }: GlyphProps) {
  return svg(size, className, <path d="M5 6.5L8 9.5l3-3" />);
}
