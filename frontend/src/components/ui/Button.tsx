import Link from "next/link";
import type { ButtonHTMLAttributes, ReactNode } from "react";

type Variant = "primary" | "secondary" | "quiet";
type Size = "sm" | "md" | "lg";

const variantClass: Record<Variant, string> = {
  primary: "btn-primary",
  secondary: "btn-secondary",
  quiet: "btn-quiet",
};

const sizeClass: Record<Size, string> = { sm: "btn-sm", md: "", lg: "btn-lg" };

function classes(variant: Variant, size: Size, block?: boolean, extra?: string) {
  return ["btn", variantClass[variant], sizeClass[size], block ? "btn-block" : "", extra ?? ""]
    .filter(Boolean)
    .join(" ");
}

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
  size?: Size;
  block?: boolean;
  /** 提交中的替代文案；给出时按钮自动禁用，避免重复提交。 */
  busyLabel?: string;
  busy?: boolean;
};

export function Button({
  variant = "secondary",
  size = "md",
  block,
  busy,
  busyLabel,
  className,
  children,
  disabled,
  ...rest
}: ButtonProps) {
  return (
    <button
      className={classes(variant, size, block, className)}
      disabled={disabled || busy}
      {...rest}
    >
      {busy && busyLabel ? busyLabel : children}
    </button>
  );
}

export function ButtonLink({
  href,
  variant = "secondary",
  size = "md",
  block,
  className,
  children,
}: {
  href: string;
  variant?: Variant;
  size?: Size;
  block?: boolean;
  className?: string;
  children: ReactNode;
}) {
  return (
    <Link className={classes(variant, size, block, className)} href={href}>
      {children}
    </Link>
  );
}
