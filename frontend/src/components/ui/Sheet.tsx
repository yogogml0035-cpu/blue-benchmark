"use client";

import { useRouter } from "next/navigation";
import { type ReactNode, useEffect, useRef, useState } from "react";

/**
 * 按需浮层：标准与依据、确认后果、技术详情等只在老师主动打开时出现。
 * 桌面右侧滑入，窄屏全屏；打开时锁定背景滚动并把焦点移入，关闭后返回触发器。
 */
export function Sheet({
  title,
  onClose,
  children,
  wide,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  /** 宽屏时仍使用右侧抽屉，但允许更宽的阅读宽度。 */
  wide?: boolean;
}) {
  const router = useRouter();
  const panelRef = useRef<HTMLDivElement>(null);
  const restoreFocusRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    restoreFocusRef.current = document.activeElement as HTMLElement | null;
    const panel = panelRef.current;
    if (!panel) return;

    const previouslyFocused = document.activeElement as HTMLElement | null;
    const focusables = panel.querySelectorAll<HTMLElement>(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
    );
    const first = focusables[0] ?? panel;
    const last = focusables[focusables.length - 1] ?? panel;
    first.focus();

    const panelElement = panel;
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key !== "Tab") return;
      if (focusables.length === 0) {
        event.preventDefault();
        panelElement.focus();
        return;
      }
      if (event.shiftKey) {
        if (document.activeElement === first) {
          event.preventDefault();
          last.focus();
        }
      } else if (document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      (restoreFocusRef.current ?? previouslyFocused)?.focus();
    };
  }, [onClose]);

  return (
    <div
      aria-modal="true"
      className="sheet-overlay"
      role="dialog"
      aria-label={title}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          event.preventDefault();
          onClose();
        }
      }}
    >
      <div
        className={`sheet-panel${wide ? " sheet-panel-wide" : ""}`}
        ref={panelRef}
        tabIndex={-1}
      >
        <div className="sheet-panel-head">
          <h2 className="doc-title-sm">{title}</h2>
          <button
            aria-label="关闭"
            className="btn btn-quiet btn-icon"
            onClick={onClose}
            type="button"
          >
            <span aria-hidden="true">×</span>
          </button>
        </div>
        <div className="sheet-panel-body">{children}</div>
      </div>
    </div>
  );
}

/** 确认对话框：不可逆动作或高后果选择前的二次确认。 */
export function ConfirmSheet({
  title,
  description,
  confirmLabel,
  cancelLabel = "取消",
  busy,
  onConfirm,
  onCancel,
  children,
}: {
  title: string;
  description?: string;
  confirmLabel: string;
  cancelLabel?: string;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
  children?: ReactNode;
}) {
  return (
    <Sheet title={title} onClose={onCancel}>
      <div className="stack" style={{ gap: "var(--s-5)" }}>
        {description && <p className="secondary">{description}</p>}
        {children}
        <div className="row" style={{ justifyContent: "flex-end", gap: "var(--s-3)" }}>
          <button className="btn btn-quiet" onClick={onCancel} type="button">
            {cancelLabel}
          </button>
          <button
            className="btn btn-primary"
            disabled={busy}
            onClick={onConfirm}
            type="button"
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </Sheet>
  );
}

/** 技术详情折叠：hash、Manifest、错误码等机器可读信息默认隐藏。 */
export function TechnicalDisclosure({ label = "技术详情", children }: { label?: string; children: ReactNode }) {
  return (
    <details className="tech-disclosure">
      <summary>{label}</summary>
      <div className="tech-disclosure-body">{children}</div>
    </details>
  );
}
