"use client";

import { Eye, EyeOff, KeyRound, RefreshCw, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorPanel } from "@/components/ui/error-panel";
import { ApiError } from "@/lib/api/client";
import {
  createOrReplaceCredential,
  revealCredential,
  revokeCredential,
  type SceneCredentialIssuedView,
  type SceneCredentialStatusView,
} from "../api";
import { formatDateTime } from "../format";
import styles from "./credential-panel.module.css";

export interface CredentialPanelProps {
  sceneId: string;
  /** The scene's single current credential (1:1 model); null when unsigned. */
  credential: SceneCredentialStatusView | null;
  /** Called with the one-time issued view so the parent shows the prompt once. */
  onIssued: (issued: SceneCredentialIssuedView) => void;
  /** Called after any mutation so the parent refreshes masked status. */
  onChanged: () => void;
}

function describeError(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  return "操作失败，请稍后重试。";
}

export function CredentialPanel({
  sceneId,
  credential,
  onIssued,
  onChanged,
}: CredentialPanelProps): React.JSX.Element {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirmReplace, setConfirmReplace] = useState(false);
  const [confirmRevoke, setConfirmRevoke] = useState(false);
  const [revealedToken, setRevealedToken] = useState<string | null>(null);

  const active = credential !== null && credential.status === "active";
  const canReveal = active && credential.token_preview !== null;

  // A refreshed or replaced credential invalidates whatever was revealed.
  useEffect(() => {
    setRevealedToken(null);
  }, [credential?.credential_id, credential?.status]);

  async function handleCreateOrReplace(): Promise<void> {
    setConfirmReplace(false);
    setBusy("replace");
    setError(null);
    try {
      const issued = await createOrReplaceCredential(sceneId, {});
      onChanged();
      onIssued(issued);
    } catch (err) {
      setError(describeError(err));
    } finally {
      setBusy(null);
    }
  }

  async function handleToggleReveal(): Promise<void> {
    if (revealedToken !== null) {
      setRevealedToken(null);
      return;
    }
    setBusy("reveal");
    setError(null);
    try {
      const revealed = await revealCredential(sceneId);
      setRevealedToken(revealed.token);
    } catch (err) {
      setError(describeError(err));
    } finally {
      setBusy(null);
    }
  }

  async function handleRevoke(): Promise<void> {
    setConfirmRevoke(false);
    if (credential === null) return;
    setBusy("revoke");
    setError(null);
    try {
      await revokeCredential(sceneId, credential.credential_id);
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
          <p className={styles.subtitle}>每个评测集只有一张共享凭证，点小眼睛可查看完整凭证。</p>
        </div>
        <div className={styles.actions}>
          <Button
            variant={active ? "secondary" : "primary"}
            onClick={active ? () => setConfirmReplace(true) : () => void handleCreateOrReplace()}
            loading={busy === "replace"}
            disabled={busy !== null}
          >
            {active ? <RefreshCw size={16} aria-hidden="true" /> : <KeyRound size={16} aria-hidden="true" />}
            {active ? "替换凭证" : "创建凭证"}
          </Button>
        </div>
      </div>

      {error ? <ErrorPanel title="凭证操作未成功" message={error} /> : null}

      {credential === null ? (
        <EmptyState
          icon={KeyRound}
          title="尚未签发凭证"
          description="点击右上角“创建凭证”，把本地上传 Skill 绑定到这个评测集。"
        />
      ) : (
        <ul className={styles.list}>
          <li className={styles.item}>
            <div className={styles.itemMain}>
              <div className={styles.itemLabel}>{credential.label || "未命名凭证"}</div>
              <div className={styles.tokenLine}>
                {canReveal ? (
                  <>
                    <span className={styles.tokenValue}>
                      {revealedToken !== null ? revealedToken : credential.token_preview}
                    </span>
                    <Button
                      variant="ghost"
                      onClick={() => void handleToggleReveal()}
                      loading={busy === "reveal"}
                      disabled={busy !== null && busy !== "reveal"}
                      aria-label={revealedToken !== null ? "隐藏凭证" : "查看完整凭证"}
                    >
                      {revealedToken !== null ? (
                        <EyeOff size={16} aria-hidden="true" />
                      ) : (
                        <Eye size={16} aria-hidden="true" />
                      )}
                    </Button>
                  </>
                ) : (
                  <span className={styles.tokenUnavailable}>
                    签发于旧版本，明文不可查看；替换凭证后恢复可看。
                  </span>
                )}
              </div>
              <div className={styles.itemMeta}>
                <span>签发自 {formatDateTime(credential.created_at)}</span>
                <span>
                  {credential.last_used_at
                    ? `最近使用 ${formatDateTime(credential.last_used_at)}`
                    : "尚未使用"}
                </span>
              </div>
            </div>
            <div className={styles.itemActions}>
              {active ? (
                <Button
                  variant="ghost"
                  onClick={() => setConfirmRevoke(true)}
                  disabled={busy !== null}
                  aria-label={`停用凭证 ${credential.label || credential.credential_id}`}
                >
                  <Trash2 size={16} aria-hidden="true" />
                  停用
                </Button>
              ) : null}
            </div>
          </li>
        </ul>
      )}

      <Dialog
        open={confirmReplace}
        title="替换凭证"
        onClose={() => setConfirmReplace(false)}
        footer={
          <>
            <Button variant="secondary" onClick={() => setConfirmReplace(false)}>
              取消
            </Button>
            <Button onClick={() => void handleCreateOrReplace()}>替换</Button>
          </>
        }
      >
        <p className={styles.dialogText}>
          替换会立即停用当前凭证并生成一张新凭证。已绑定旧凭证的 Agent 将失效，需要用新提示词重新绑定。确定继续吗？
        </p>
      </Dialog>

      <Dialog
        open={confirmRevoke}
        title="停用凭证"
        onClose={() => setConfirmRevoke(false)}
        footer={
          <>
            <Button variant="secondary" onClick={() => setConfirmRevoke(false)}>
              取消
            </Button>
            <Button variant="danger" onClick={() => void handleRevoke()}>
              停用
            </Button>
          </>
        }
      >
        <p className={styles.dialogText}>
          停用后，使用该凭证的 Agent 将无法再连接此评测集；评测集回到未签发状态，可随时重新创建凭证。确定继续吗？
        </p>
      </Dialog>
    </section>
  );
}
