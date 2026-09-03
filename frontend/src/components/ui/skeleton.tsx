import styles from "./skeleton.module.css";

export interface SkeletonProps {
  /** CSS width; defaults to filling the container. */
  width?: string | number;
  /** CSS height; defaults to one text line. */
  height?: string | number;
  variant?: "text" | "block" | "circle";
}

/** Deterministic loading placeholder that keeps layout dimensions stable. */
export function Skeleton({ width, height, variant = "text" }: SkeletonProps): React.JSX.Element {
  const shape =
    variant === "circle" ? styles.circle : variant === "block" ? styles.block : styles.text;
  return (
    <span
      className={[styles.skeleton, shape].join(" ")}
      style={{ width, height }}
      aria-hidden="true"
    />
  );
}
