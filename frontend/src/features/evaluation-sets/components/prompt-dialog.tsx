"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import styles from "./prompt-dialog.module.css";

export interface AgentPromptDialogProps {
  open: boolean;
  /**
   * The one-time binding prompt. Lives only in transient parent state; the
   * parent passes null again after the dialog closes so nothing persists.
   */
  prompt: string | null;
  onClose: () => void;
}

/**
 * Shows the Agent binding prompt exactly once.
 *
 * The token is only ever present in this component's props/state and the
 * clipboard. Copy prefers navigator.clipboard; when that is unavailable or
 * fails (e.g. Safari), the user is told to select and copy manually — the
 * textarea is always selectable, so the fallback never dead-ends. Closing
 * before a successful copy asks for confirmation because the prompt cannot be
 * recovered.
 */
export function AgentPromptDialog({ open, prompt, onClose }: AgentPromptDialogProps): React.JSX.Element | null {
  const [copied, setCopied] = useState(false);
  const [copyFailed, setCopyFailed] = useState(false);
  const [confirmingClose, setConfirmingClose] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  // Reset transient state whenever the dialog opens with a fresh prompt.
  useEffect(() => {
    if (open) {
      setCopied(false);
      setCopyFailed(false);
      setConfirmingClose(false);
    }
  }, [open, prompt]);

  if (!open || prompt === null) return null;

  async function handleCopy(): Promise<void> {
    try {
      if (!navigator.clipboard) throw new Error("clipboard unavailable");
      await navigator.clipboard.writeText(prompt ?? "");
      setCopied(true);
      setCopyFailed(false);
    } catch {
      // Safari (or non-secure contexts): fall back to manual selection.
      setCopyFailed(true);
      textareaRef.current?.focus();
      textareaRef.current?.select();
    }
  }

  function requestClose(): void {
    if (copied) {
      onClose();
      return;
    }
    setConfirmingClose(true);
  }

  return (
    <Dialog
      open
      title="发给 Agent 的绑定提示词"
      onClose={requestClose}
      footer={
        confirmingClose ? (
          <>
            <Button variant="secondary" onClick={() => setConfirmingClose(false)}>
              继续复制
            </Button>
            <Button variant="danger" onClick={onClose}>
              不复制并关闭
            </Button>
          </>
        ) : (
          <>
            <Button variant="secondary" onClick={requestClose}>
              关闭
            </Button>
            <Button onClick={handleCopy} disabled={copied}>
              {copied ? "已复制" : "复制提示词"}
            </Button>
          </>
        )
      }
    >
      {confirmingClose ? (
        <p className={styles.notice}>
          还没有成功复制。关闭后此提示词无法找回，凭证只能通过轮换重新生成。确定要关闭吗？
        </p>
      ) : (
        <div className={styles.body}>
          <p className={styles.hint}>
            此提示词只显示一次，包含长期凭证。请复制后交给目标 Agent，勿提交到仓库。
          </p>
          {copyFailed ? (
            <p className={styles.copyFailed} role="alert">
              自动复制不可用。请在下方文本框中全选并手动复制。
            </p>
          ) : null}
          <textarea
            ref={textareaRef}
            className={styles.prompt}
            readOnly
            value={prompt}
            aria-label="绑定提示词"
            onFocus={(e) => e.currentTarget.select()}
          />
        </div>
      )}
    </Dialog>
  );
}
