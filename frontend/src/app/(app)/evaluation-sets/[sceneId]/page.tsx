"use client";

import { ArrowLeft, Pencil, Trash2 } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { ErrorPanel } from "@/components/ui/error-panel";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusBadge, type StatusTone } from "@/components/ui/status-badge";
import {
  deleteScene,
  getSceneStatus,
  type SceneCredentialIssuedView,
  type SceneStatusResponse,
} from "@/features/evaluation-sets/api";
import {
  CONNECTION_STATUS_LABEL,
  deriveConnectionStatus,
  type ConnectionStatus,
} from "@/features/evaluation-sets/connection";
import { CredentialPanel } from "@/features/evaluation-sets/components/credential-panel";
import { EvaluationSetFormDialog } from "@/features/evaluation-sets/components/form-dialog";
import { AgentPromptDialog } from "@/features/evaluation-sets/components/prompt-dialog";
import { QuestionListSection } from "@/features/questions/components/question-list-section";
import { buildAgentBindingPrompt, resolveAgentApiBaseUrl } from "@/features/evaluation-sets/prompt";
import { ApiError } from "@/lib/api/client";
import styles from "./page.module.css";

const STATUS_TONE: Record<ConnectionStatus, StatusTone> = {
  unsigned: "neutral",
  issued: "warning",
  connected: "success",
};

export default function EvaluationSetDetailPage(): React.JSX.Element {
  const params = useParams<{ sceneId: string }>();
  const router = useRouter();
  const sceneId = params.sceneId;

  const [status, setStatus] = useState<SceneStatusResponse | null>(null);
  const [loadError, setLoadError] = useState<{ code: string; message: string } | null>(null);
  const [editOpen, setEditOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [prompt, setPrompt] = useState<string | null>(null);
  const [promptOpen, setPromptOpen] = useState(false);
  // Tracks the in-flight load so a delete (which navigates away) can cancel it
  // and avoid a late 404 flashing "not found" over the departing page.
  const loadAbortRef = useRef<AbortController | null>(null);

  const load = useCallback(async () => {
    loadAbortRef.current?.abort();
    const controller = new AbortController();
    loadAbortRef.current = controller;
    setLoadError(null);
    try {
      const response = await getSceneStatus(sceneId, controller.signal);
      if (controller.signal.aborted) return;
      setStatus(response);
    } catch (err) {
      if (controller.signal.aborted) return;
      setStatus(null);
      if (err instanceof ApiError) {
        setLoadError({ code: err.code, message: err.message });
      } else {
        setLoadError({ code: "UNKNOWN", message: "加载评测集失败，请稍后重试。" });
      }
    }
  }, [sceneId]);

  useEffect(() => {
    void load();
  }, [load]);

  function handleIssued(issued: SceneCredentialIssuedView): void {
    if (!status) return;
    const text = buildAgentBindingPrompt({
      agentApiBaseUrl: resolveAgentApiBaseUrl(),
      sceneId: issued.scene_id,
      sceneName: status.scene.name,
      token: issued.token,
    });
    setPrompt(text);
    setPromptOpen(true);
  }

  async function handleDelete(): Promise<void> {
    setDeleting(true);
    setDeleteError(null);
    try {
      await deleteScene(sceneId);
      // Cancel any in-flight load so a late 404 can't flash over the redirect.
      loadAbortRef.current?.abort();
      router.replace("/evaluation-sets");
    } catch (err) {
      setDeleteOpen(false);
      if (err instanceof ApiError) {
        setDeleteError(err.message);
        // The scene changed underneath (e.g. became non-empty); refresh it.
        void load();
      } else {
        setDeleteError("删除失败，请稍后重试。");
      }
    } finally {
      setDeleting(false);
    }
  }

  if (loadError) {
    const notFound = loadError.code === "RESOURCE_NOT_FOUND";
    return (
      <div className={styles.page}>
        <Link href="/evaluation-sets" className={styles.back}>
          <ArrowLeft size={16} aria-hidden="true" />
          返回评测集列表
        </Link>
        <ErrorPanel
          title={notFound ? "评测集不存在" : "加载未成功"}
          message={loadError.message}
          action={
            !notFound ? (
              <Button variant="secondary" onClick={() => void load()}>
                重试
              </Button>
            ) : undefined
          }
        />
      </div>
    );
  }

  if (!status) {
    return (
      <div className={styles.page} aria-busy="true">
        <Skeleton width={200} height={20} />
        <Skeleton width="60%" height={32} />
        <Skeleton variant="block" height={200} />
      </div>
    );
  }

  const scene = status.scene;
  const connection = deriveConnectionStatus(status.credential);
  const canDelete = scene.question_count === 0;

  return (
    <div className={styles.page}>
      <Link href="/evaluation-sets" className={styles.back}>
        <ArrowLeft size={16} aria-hidden="true" />
        返回评测集列表
      </Link>

      <div className={styles.header}>
        <div className={styles.headerMain}>
          <div className={styles.titleRow}>
            <h1 className={styles.title}>{scene.name}</h1>
            <StatusBadge tone={STATUS_TONE[connection]}>
              {CONNECTION_STATUS_LABEL[connection]}
            </StatusBadge>
          </div>
          <p className={styles.description}>{scene.description || "暂无描述"}</p>
          <p className={styles.meta}>
            {scene.question_count} 道题 · {scene.active_credential_count} 个有效凭证
          </p>
        </div>
        <div className={styles.headerActions}>
          <Button variant="secondary" onClick={() => setEditOpen(true)}>
            <Pencil size={16} aria-hidden="true" />
            编辑
          </Button>
          {canDelete ? (
            <Button variant="danger" onClick={() => setDeleteOpen(true)}>
              <Trash2 size={16} aria-hidden="true" />
              删除
            </Button>
          ) : null}
        </div>
      </div>

      {deleteError ? <ErrorPanel title="删除未成功" message={deleteError} /> : null}

      <CredentialPanel
        sceneId={sceneId}
        credential={status.credential}
        onIssued={handleIssued}
        onChanged={() => void load()}
      />

      <QuestionListSection sceneId={sceneId} />

      <EvaluationSetFormDialog
        open={editOpen}
        scene={scene}
        onClose={() => setEditOpen(false)}
        onSaved={() => {
          setEditOpen(false);
          void load();
        }}
      />

      <Dialog
        open={deleteOpen}
        title="删除评测集"
        onClose={() => setDeleteOpen(false)}
        footer={
          <>
            <Button variant="secondary" onClick={() => setDeleteOpen(false)} disabled={deleting}>
              取消
            </Button>
            <Button variant="danger" onClick={handleDelete} loading={deleting}>
              删除
            </Button>
          </>
        }
      >
        <p className={styles.dialogText}>
          确定删除评测集「{scene.name}」吗？该评测集的上传凭证将同时失效，此操作不可撤销。
        </p>
      </Dialog>

      <AgentPromptDialog
        open={promptOpen}
        prompt={prompt}
        onClose={() => {
          setPromptOpen(false);
          // Clear the transient plaintext so nothing lingers after closing.
          setPrompt(null);
        }}
      />
    </div>
  );
}
