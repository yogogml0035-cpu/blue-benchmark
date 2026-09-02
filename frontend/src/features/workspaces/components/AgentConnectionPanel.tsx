"use client";

import { useCallback, useEffect, useState } from "react";

import { Button } from "@/src/components/ui/Button";
import { ConfirmSheet, Sheet } from "@/src/components/ui/Sheet";
import { Note } from "@/src/components/ui/Note";
import type { SessionResult } from "@/src/features/auth/hooks/useSession";
import {
  createAuthoringConnection,
  getAuthoringConnection,
  revokeAuthoringConnection,
  type AuthoringConnectionStatusResponse,
} from "@/src/features/workspaces/services/workspaceService";
import { toPageFault, type PageFault } from "@/src/lib/api/pageFault";
import { usePreviewState } from "@/src/lib/preview/preview";

import styles from "./studio.module.css";

type Connection = NonNullable<AuthoringConnectionStatusResponse["connection"]>;

type Load =
  | { status: "loading" }
  | { status: "ready"; connection: Connection | null }
  | { status: "failed"; fault: PageFault };

type Setup = {
  code: string;
  expiresAt: string;
  exchangeUrl: string;
};

const STATUS_LABEL: Record<Connection["status"], string> = {
  pending_exchange: "等待本地兑换",
  active: "已连接",
  expired: "连接码已过期",
  revoked: "已撤销",
};

export function AgentConnectionPanel({ workspaceId, session }: { workspaceId: string; session: SessionResult }) {
  const preview = usePreviewState();
  const [load, setLoad] = useState<Load>({ status: "loading" });
  const [busy, setBusy] = useState<"create" | "revoke" | null>(null);
  const [fault, setFault] = useState<PageFault | null>(null);
  const [setup, setSetup] = useState<Setup | null>(null);
  const [copied, setCopied] = useState(false);
  const [confirmRevoke, setConfirmRevoke] = useState(false);

  const read = useCallback(async () => {
    if (preview) {
      setLoad({ status: "ready", connection: null });
      return;
    }
    if (session.status !== "authenticated") return;
    setLoad({ status: "loading" });
    try {
      const result = await getAuthoringConnection(workspaceId);
      setLoad({ status: "ready", connection: result.connection ?? null });
      setFault(null);
    } catch (cause: unknown) {
      setLoad({ status: "failed", fault: toPageFault(cause) });
    }
  }, [preview, session.status, workspaceId]);

  useEffect(() => {
    void read();
  }, [read]);

  async function create() {
    if (busy || preview) return;
    setBusy("create");
    setFault(null);
    setCopied(false);
    try {
      const result = await createAuthoringConnection(workspaceId);
      setLoad({ status: "ready", connection: result.connection });
      setSetup({ code: result.connection_code, expiresAt: result.expires_at, exchangeUrl: result.exchange_url });
    } catch (cause: unknown) {
      setFault(toPageFault(cause));
    } finally {
      setBusy(null);
    }
  }

  async function revoke() {
    if (busy || load.status !== "ready" || !load.connection) return;
    setBusy("revoke");
    setFault(null);
    try {
      const result = await revokeAuthoringConnection(workspaceId, load.connection.id);
      setLoad({ status: "ready", connection: result.connection ?? null });
      setSetup(null);
      setConfirmRevoke(false);
    } catch (cause: unknown) {
      setFault(toPageFault(cause));
    } finally {
      setBusy(null);
    }
  }

  const connection = load.status === "ready" ? load.connection : null;
  const status = connection?.status ?? null;

  return (
    <>
      <section className={`${styles.agentConnection} sheet sheet-pad stack`} aria-label="连接本地 Agent" data-testid="agent-connection">
        <div className="row-between">
          <div className="stack-sm">
            <span className="section-label">场景连接</span>
            <h2 className="doc-title-sm">连接本地 Agent</h2>
          </div>
          {status && (
            <span className={`state ${status === "active" ? "state-green" : status === "revoked" || status === "expired" ? "state-amber" : "state-active"}`}>
              <span className="dot" />{STATUS_LABEL[status]}
            </span>
          )}
        </div>
        <p className="secondary">
          连接只允许本地 Agent 读取当前场景名称并创建单题草稿。题目审阅、打分规则和发布仍只在这个网站里完成。
        </p>
        {load.status === "loading" && <p className="secondary" aria-busy="true">正在读取连接状态…</p>}
        {load.status === "failed" && (
          <Note code={load.fault.code} title="连接状态读取失败" tone="fail">{load.fault.message}</Note>
        )}
        {fault && <Note code={fault.code} title="操作没有完成" tone="fail">{fault.message}</Note>}
        {status === "active" && connection ? (
          <div className={styles.agentConnectionDetails}>
            <div className="stack-sm">
              <span className="section-label">当前客户端</span>
              <span>{connection.client_name}</span>
              <span className="mono faint">最近使用：{connection.last_used_at ? new Date(connection.last_used_at).toLocaleString("zh-CN") : "尚未使用"}</span>
            </div>
            <Button disabled={busy !== null} onClick={() => setConfirmRevoke(true)} variant="quiet">撤销连接</Button>
          </div>
        ) : (
          <div className="row">
            <Button busy={busy === "create"} busyLabel="正在创建…" onClick={() => void create()} variant="primary">
              {status === "pending_exchange" ? "重新创建连接码" : "创建连接码"}
            </Button>
            {status === "pending_exchange" && <span className="secondary">上一次连接码还没有被本地兑换。</span>}
          </div>
        )}
        {preview && <p className="mono faint">开发预演不会创建真实连接。</p>}
      </section>

      {setup && (
        <Sheet title="把连接交给本地 Agent" onClose={() => setSetup(null)}>
          <div className="stack-lg">
            <div className="stack-sm">
              <span className="section-label">一步性连接码</span>
              <p className="secondary">只把下面的连接码交给你明确启动的本地 Agent。它只能兑换一次，关闭这个窗口后网站不会再次显示。</p>
            </div>
            <label className="field">
              <span className="field-label">连接码</span>
              <input aria-label="一次性连接码" className="control mono" readOnly value={setup.code} />
            </label>
            <div className="row">
              <Button
                onClick={() => {
                  const clipboard = navigator.clipboard;
                  if (!clipboard) return;
                  void clipboard.writeText(setup.code).then(() => setCopied(true));
                }}
                variant="secondary"
              >
                {copied ? "已复制" : "复制连接码"}
              </Button>
              <span className="mono faint">{new Date(setup.expiresAt).toLocaleString("zh-CN")} 前有效</span>
            </div>
            <div className="inset stack-sm">
              <span className="section-label">兑换地址</span>
              <code className="mono" style={{ overflowWrap: "anywhere" }}>{setup.exchangeUrl}</code>
            </div>
            <Note title="安全边界" tone="info">连接码不在 URL 中；兑换后的 token 也不会由网站展示或保存到浏览器。</Note>
          </div>
        </Sheet>
      )}

      {confirmRevoke && (
        <ConfirmSheet
          busy={busy === "revoke"}
          confirmLabel="撤销连接"
          description="撤销后旧 token 立即不能再创建草稿；已创建的题稿仍保留在网站里。重新绑定会产生新的连接码。"
          onCancel={() => setConfirmRevoke(false)}
          onConfirm={() => void revoke()}
          title="确认撤销本地 Agent 连接"
        />
      )}
    </>
  );
}
