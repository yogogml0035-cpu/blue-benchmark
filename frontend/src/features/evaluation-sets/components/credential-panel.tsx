"use client";

import { KeyRound, RefreshCw, Trash2 } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorPanel } from "@/components/ui/error-panel";
import { StatusBadge, type StatusTone } from "@/components/ui/status-badge";
import { ApiError } from "@/lib/api/client";
import {
  issueCredential,
  revokeCredential,
  rotateCredentials,
  type SceneCredentialIssuedView,
  type SceneCredentialStatusView,
} from "../api";
import { formatDateTime } from "../format";
import styles from "./credential-panel.module.css";

export interface CredentialPanelProps {
  sceneId: string;
  credentials: SceneCredentialStatusView[];
  /** Called with the one-time issued view so the parent shows the prompt once. */
  onIssued: (issued: SceneCredentialIssuedView) => void;
  /** Called after any mutation so the parent refreshes masked status. */
  onChanged: () => void;
}

function statusTone(status: "active" | "revoked"): StatusTone {
  return status === "active" ? "success" : "neutral";
}

export function CredentialPanel({
  sceneId,
  credentials,
  onIssued,
  onChanged,
}: CredentialPanelProps): React.JSX.Element {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirmRotate, setConfirmRotate] = useState(false);
  const [confirmRevokeId, setConfirmRevokeId] = useState<string | null>(null);

  function describeError(err: unknown): string {
    if (err instanceof ApiError) return err.message;
    return "操作失败，请稍后重试。";
  }

  async function handleIssue(): Promise<void> {
    setBusy("issue");
    setError(null);
    try {
      const issued = await issueCredential(sceneId, {});
      onChanged();
      onIssued(issued);
    } catch (err) {
      setError(describeError(err));
    } finally {
      setBusy(null);
    }
  }

  async function handleRotate(): Promise<void> {
    setConfirmRotate(false);
    setBusy("rotate");
    setError(null);
    try {
      const issued = await rotateCredentials(sceneId, {});
      onChanged();
      onIssued(issued);
    } catch (err) {
      setError(describeError(err));
    } finally {
      setBusy(null);
    }
  }

  async function handleRevoke(credentialId: string): Promise<void> {
    setConfirmRevokeId(null);
    setBusy(`revoke:${credentialId}`);
    setError(null);
    try {
      await revokeCredential(sceneId, credentialId);
      onChanged();
    } catch (err) {
      setError(describeError(err));
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className={styles.panel}>
      <div className={styles.header}>
        <div>
          <h2 className={styles.title}>上传凭证</h2>
          <p className={styles.subtitle}>凭证只在显式签发时生成，明文仅显示一次。</p>
        </div>
        <div className={styles.actions}>
          <Button variant="secondary" onClick={() => setConfirmRotate(true)} disabled={busy !== null}>
            <RefreshCw size={16} aria-hidden="true" />
            轮换凭证
          </Button>
          <Button onClick={handleIssue} loading={busy === "issue"}>
            <KeyRound size={16} aria-hidden="true" />
            生成上传凭证
          </Button>
        </div>
      </div>

      {error ? <ErrorPanel title="凭证操作未成功" message={error} /> : null}

      {credentials.length === 0 ? (
        <EmptyState
          icon={KeyRound}
          title="尚未签发凭证"
          description="点击右上角“生成上传凭证”，把本地上传 Skill 绑定到这个评测集。"
        />
      ) : (
        <ul className={styles.list}>
          {credentials.map((credential) => (
            <li key={credential.credential_id} className={styles.item}>
              <div className={styles.itemMain}>
                <div className={styles.itemLabel}>
                  {credential.label || "未命名凭证"}
                  <StatusBadge tone={statusTone(credential.status)}>
                    {credential.status === "active" ? "有效" : "已撤销"}
                  </StatusBadge>
                </div>
                <div className={styles.itemMeta}>
                  <span>签发自 {formatDateTime(credential.created_at)}</span>
                  <span>
                    {credential.last_used_at
                      ? `最近使用 ${formatDateTime(credential.last_used_at)}`
                      : "尚未使用"}
                  </span>
                  {credential.revoked_at ? (
                    <span>
                      撤销于 {formatDateTime(credential.revoked_at)}
                      {credential.revoked_reason ? `（${credential.revoked_reason}）` : ""}
                    </span>
                  ) : null}
                </div>
              </div>
              {credential.status === "active" ? (
                <Button
                  variant="ghost"
                  onClick={() => setConfirmRevokeId(credential.credential_id)}
                  disabled={busy !== null}
                  aria-label={`撤销凭证 ${credential.label || credential.credential_id}`}
                >
                  <Trash2 size={16} aria-hidden="true" />
                  撤销
                </Button>
              ) : null}
            </li>
          ))}
        </ul>
      )}

      <Dialog
        open={confirmRotate}
        title="轮换凭证"
        onClose={() => setConfirmRotate(false)}
        footer={
          <>
            <Button variant="secondary" onClick={() => setConfirmRotate(false)}>
              取消
            </Button>
            <Button onClick={handleRotate}>轮换</Button>
          </>
        }
      >
        <p className={styles.dialogText}>
          轮换会立即撤销当前全部有效凭证，并生成一个新凭证。已绑定旧凭证的 Agent 将失效，需要用新提示词重新绑定。确定继续吗？
        </p>
      </Dialog>

      <Dialog
        open={confirmRevokeId !== null}
        title="撤销凭证"
        onClose={() => setConfirmRevokeId(null)}
        footer={
          <>
            <Button variant="secondary" onClick={() => setConfirmRevokeId(null)}>
              取消
            </Button>
            <Button
              variant="danger"
              onClick={() => confirmRevokeId !== null && handleRevoke(confirmRevokeId)}
            >
              撤销
            </Button>
          </>
        }
      >
        <p className={styles.dialogText}>
          撤销后，使用该凭证的 Agent 将无法再连接此评测集。此操作不可撤销（可重新签发新凭证）。确定继续吗？
        </p>
      </Dialog>
    </section>
  );
}
