"use client";

import { useCallback, useEffect, useRef, type TextareaHTMLAttributes } from "react";

/**
 * 草稿里的文本长度差异很大：一句话的任务目标和一整段参考结果共用同一个控件。
 * 固定高度会把长文截成半行，所以编辑器里的文本框一律按内容自动增高。
 */
export function AutoTextarea({
  minRows = 2,
  className,
  value,
  ...rest
}: TextareaHTMLAttributes<HTMLTextAreaElement> & { minRows?: number }) {
  const ref = useRef<HTMLTextAreaElement>(null);

  const fit = useCallback(() => {
    const node = ref.current;
    if (!node) return;
    node.style.height = "auto";
    node.style.height = `${node.scrollHeight}px`;
  }, []);

  useEffect(() => {
    fit();
  }, [fit, value]);

  useEffect(() => {
    window.addEventListener("resize", fit);
    return () => window.removeEventListener("resize", fit);
  }, [fit]);

  return (
    <textarea
      className={`${className ?? ""} control-auto`.trim()}
      onInput={fit}
      ref={ref}
      rows={minRows}
      value={value}
      {...rest}
    />
  );
}
