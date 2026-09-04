"use client";

import { ArrowLeft, RefreshCw, RotateCcw, Send, Trash2 } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { ErrorPanel } from "@/components/ui/error-panel";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusBadge } from "@/components/ui/status-badge";
import { TextField } from "@/components/ui/text-field";
import {
  deleteQuestion,
  getQuestion,
  patchCriteria,
  publishQuestion,
  retryGeneration,
  reviewReopen,
  saveRegenerate,
  updateTitle,
  type QuestionDetailResponse,
} from "@/features/questions/api";
import { CriteriaEditor } from "@/features/questions/components/criteria-editor";
import { MaterialsPanel } from "@/features/questions/components/materials-panel";
import {
  draftsFromDetail,
  selectedToPayload,
  validateSelected,
  type CriterionDraft,
} from "@/features/questions/criterion-draft";
import {
  draftFromDetail,
  draftToPayload,
  isOnlyTitleChanged,
  type MaterialDraft,
} from "@/features/questions/material-draft";
import { STATUS_LABEL, STATUS_TONE } from "@/features/questions/state";
import { ApiError } from "@/lib/api/client";
import styles from "./page.module.css";

const POLL_INTERVAL_MS = 2500;

export default function QuestionWorkbenchPage(): React.JSX.Element {
  const params = useParams<{ questionId: string }>();
  const router = useRouter();
  const questionId = params.questionId;

  const [detail, setDetail] = useState<QuestionDetailResponse | null>(null);
  const [loadError, setLoadError] = useState<{ code: string; message: string } | null>(null);

  // Materials editing.
  const [editingMaterials, setEditingMaterials] = useState(false);
  const [materialDraft, setMaterialDraft] = useState<MaterialDraft | null>(null);
  const [savingMaterials, setSavingMaterials] = useState(false);

  // Criteria drafts.
  const [criterionDrafts, setCriterionDrafts] = useState<CriterionDraft[]>([]);
  const [criteriaDirty, setCriteriaDirty] = useState(false);
  const [savingCriteria, setSavingCriteria] = useState(false);
  const [criteriaError, setCriteriaError] = useState<string | null>(null);
  const [saveConfirmOpen, setSaveConfirmOpen] = useState(false);

  // Actions.
  const [acting, setActing] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [staleMessage, setStaleMessage] = useState<string | null>(null);

  // Delete.
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleteTitle, setDeleteTitle] = useState("");
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const loadAbortRef = useRef<AbortController | null>(null);
  const hasDetailRef = useRef(false);
  const dirty = (editingMaterials && materialDraft !== null) || criteriaDirty;

  const applyDetail = useCallback((d: QuestionDetailResponse) => {
    setDetail(d);
    hasDetailRef.current = true;
    setCriterionDrafts(draftsFromDetail(d));
    setCriteriaDirty(false);
    setCriteriaError(null);
  }, []);

  const load = useCallback(async () => {
    loadAbortRef.current?.abort();
    const controller = new AbortController();
    loadAbortRef.current = controller;
    setLoadError(null);
    try {
      const d = await getQuestion(questionId, controller.signal);
      if (controller.signal.aborted) return;
      applyDetail(d);
    } catch (err) {
      if (controller.signal.aborted) return;
      // Keep the last good detail so an in-flight poll survives a transient
      // failure instead of permanently killing the page; only a first-load
      // failure (no detail yet) shows the full error state.
      if (hasDetailRef.current) return;
      setDetail(null);
      if (err instanceof ApiError) setLoadError({ code: err.code, message: err.message });
      else setLoadError({ code: "UNKNOWN", message: "加载题目失败，请稍后重试。" });
    }
  }, [questionId, applyDetail]);

  useEffect(() => {
    void load();
  }, [load]);

  // Poll while generating (only when the tab is visible).
  useEffect(() => {
    if (!detail || detail.status !== "generating") return;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const tick = async () => {
      if (document.visibilityState === "visible") {
        await load();
      }
      timer = setTimeout(tick, POLL_INTERVAL_MS);
    };
    timer = setTimeout(tick, POLL_INTERVAL_MS);
    return () => {
      if (timer) clearTimeout(timer);
    };
  }, [detail, load]);

  // Warn before leaving with unsaved changes.
  useEffect(() => {
    if (!dirty) return;
    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [dirty]);

  function describe(err: unknown, fallback: string): string {
    return err instanceof ApiError ? err.message : fallback;
  }

  // --- Materials ---
  function startEditMaterials(): void {
    if (!detail) return;
    setMaterialDraft(draftFromDetail(detail));
    setEditingMaterials(true);
  }

  function cancelEditMaterials(): void {
    setMaterialDraft(null);
    setEditingMaterials(false);
  }

  async function handleSaveMaterials(): Promise<void> {
    if (!detail || !materialDraft) return;
    setSavingMaterials(true);
    setStaleMessage(null);
    try {
      if (isOnlyTitleChanged(detail, materialDraft)) {
        const updated = await updateTitle(detail.id, {
          command_id: crypto.randomUUID(),
          content_revision: detail.content_revision,
          title: materialDraft.title,
        });
        setEditingMaterials(false);
        setMaterialDraft(null);
        applyDetail(updated);
      } else {
        await saveRegenerate(
          detail.id,
          draftToPayload(materialDraft, {
            command_id: crypto.randomUUID(),
            content_revision: detail.content_revision,
          }),
        );
        setEditingMaterials(false);
        setMaterialDraft(null);
        await load();
      }
    } catch (err) {
      if (err instanceof ApiError && err.code === "STALE_REVISION") {
        setStaleMessage("题目内容已被更新，你的草稿已保留。请查看最新内容后决定如何继续。");
      } else {
        setStaleMessage(null);
        setActionError(describe(err, "保存失败，请稍后重试。"));
      }
    } finally {
      setSavingMaterials(false);
    }
  }

  // --- Criteria ---
  async function handleSaveCriteria(): Promise<void> {
    if (!detail) return;
    const validation = validateSelected(criterionDrafts);
    if (validation) {
      setCriteriaError(validation.message);
      return;
    }
    setSaveConfirmOpen(false);
    setSavingCriteria(true);
    setCriteriaError(null);
    setStaleMessage(null);
    try {
      const updated = await patchCriteria(detail.id, {
        command_id: crypto.randomUUID(),
        content_revision: detail.content_revision,
        criteria: selectedToPayload(criterionDrafts),
      });
      applyDetail(updated);
    } catch (err) {
      if (err instanceof ApiError && err.code === "STALE_REVISION") {
        setStaleMessage("题目内容已被更新，你的草稿已保留。请重新载入后再保存。");
      } else {
        setCriteriaError(describe(err, "保存维度失败，请稍后重试。"));
      }
    } finally {
      setSavingCriteria(false);
    }
  }

  // --- Status actions ---
  async function runAction(kind: "retry" | "publish" | "reopen", fn: () => Promise<unknown>): Promise<void> {
    setActing(kind);
    setActionError(null);
    try {
      await fn();
      await load();
    } catch (err) {
      setActionError(describe(err, "操作失败，请稍后重试。"));
    } finally {
      setActing(null);
    }
  }

  // --- Delete ---
  async function handleDelete(): Promise<void> {
    if (!detail) return;
    setDeleting(true);
    setDeleteError(null);
    try {
      await deleteQuestion(detail.id, {
        content_revision: detail.content_revision,
        confirmation_title: detail.delete_confirmation_required ? deleteTitle : null,
      });
      loadAbortRef.current?.abort();
      router.replace(`/evaluation-sets/${detail.scene_id}`);
    } catch (err) {
      setDeleteOpen(false);
      setDeleteError(describe(err, "删除失败，请稍后重试。"));
    } finally {
      setDeleting(false);
    }
  }

  if (loadError) {
    return (
      <div className={styles.page}>
        <Link className={styles.back} href="#" onClick={(e) => { e.preventDefault(); router.back(); }}>
          <ArrowLeft size={16} aria-hidden="true" />
          返回
        </Link>
        <ErrorPanel
          title={loadError.code === "RESOURCE_NOT_FOUND" ? "题目不存在" : "加载未成功"}
          message={loadError.message}
          action={
            loadError.code === "RESOURCE_NOT_FOUND" ? undefined : (
              <Button variant="secondary" onClick={() => void load()}>
                重试
              </Button>
            )
          }
        />
      </div>
    );
  }

  if (!detail) {
    return (
      <div className={styles.page} aria-busy="true">
        <Skeleton width={200} height={20} />
        <div className={styles.columns}>
          <Skeleton variant="block" height={400} />
          <Skeleton variant="block" height={300} />
        </div>
      </div>
    );
  }

  const materialsDraftForView = editingMaterials && materialDraft ? materialDraft : draftFromDetail(detail);
  const generating = detail.status === "generating";
  const published = detail.status === "published";

  return (
    <div className={styles.page}>
      <Link
        className={styles.back}
        href={`/evaluation-sets/${detail.scene_id}`}
      >
        <ArrowLeft size={16} aria-hidden="true" />
        返回「{detail.scene_name}」
      </Link>

      <div className={styles.header}>
        <div className={styles.headerMain}>
          <h1 className={styles.title}>{detail.title}</h1>
          <StatusBadge tone={STATUS_TONE[detail.status]}>{STATUS_LABEL[detail.status]}</StatusBadge>
          {!published && !generating ? (
            <Button
              variant="danger"
              onClick={() => {
                setDeleteTitle("");
                setDeleteOpen(true);
              }}
            >
              <Trash2 size={15} aria-hidden="true" />
              删除题目
            </Button>
          ) : null}
        </div>
        {!editingMaterials && !published ? (
          <Button variant="secondary" onClick={startEditMaterials}>
            编辑材料
          </Button>
        ) : null}
      </div>

      {staleMessage ? <ErrorPanel title="内容版本冲突" message={staleMessage} action={
        <Button variant="secondary" onClick={() => void load()}>查看最新内容</Button>
      } /> : null}
      {actionError ? <ErrorPanel title="操作未成功" message={actionError} /> : null}
      {deleteError ? <ErrorPanel title="删除未成功" message={deleteError} /> : null}

      <div className={styles.columns}>
        <div className={styles.materialsCol}>
          {editingMaterials ? (
            <div className={styles.materialsEditBar}>
              <Button variant="secondary" onClick={cancelEditMaterials} disabled={savingMaterials}>
                取消
              </Button>
              <Button onClick={() => void handleSaveMaterials()} loading={savingMaterials}>
                保存并重新生成
              </Button>
            </div>
          ) : null}
          <MaterialsPanel
            draft={materialsDraftForView}
            editing={editingMaterials}
            onChange={(updater) => setMaterialDraft((d) => (d ? updater(d) : d))}
          />
        </div>

        <div className={styles.reviewCol}>
          <div className={styles.reviewInner}>
            <h2 className={styles.reviewTitle}>评分维度</h2>

            {generating ? (
              <div className={styles.statusBox}>
                <p className={styles.statusNote}>正在生成评分维度…（页面可见时自动刷新）</p>
                <Button variant="secondary" onClick={() => void load()}>
                  <RefreshCw size={15} aria-hidden="true" />
                  手动刷新
                </Button>
              </div>
            ) : null}

            {detail.status === "generation_failed" ? (
              <div className={styles.statusBox}>
                <ErrorPanel
                  title="生成失败"
                  message={detail.last_error?.message || "评分维度生成失败。"}
                  action={
                    <Button
                      onClick={() =>
                        runAction("retry", () =>
                          retryGeneration(detail.id, {
                            command_id: crypto.randomUUID(),
                            content_revision: detail.content_revision,
                          }),
                        )
                      }
                      loading={acting === "retry"}
                    >
                      重试生成
                    </Button>
                  }
                />
              </div>
            ) : null}

            {!generating && detail.status !== "generation_failed" ? (
              <>
                <CriteriaEditor
                  drafts={criterionDrafts}
                  readOnly={published}
                  onChange={(updater) => {
                    setCriterionDrafts(updater);
                    setCriteriaDirty(true);
                  }}
                />
                {criteriaError ? <ErrorPanel title="保存未成功" message={criteriaError} /> : null}

                <div className={styles.actionBar}>
                  {!published ? (
                    <Button
                      onClick={() => {
                        const v = validateSelected(criterionDrafts);
                        if (v) {
                          setCriteriaError(v.message);
                          return;
                        }
                        setCriteriaError(null);
                        setSaveConfirmOpen(true);
                      }}
                      loading={savingCriteria}
                    >
                      保存维度
                    </Button>
                  ) : null}
                  {published ? (
                    <Button
                      variant="secondary"
                      onClick={() =>
                        runAction("reopen", () =>
                          reviewReopen(detail.id, {
                            command_id: crypto.randomUUID(),
                            content_revision: detail.content_revision,
                          }),
                        )
                      }
                      loading={acting === "reopen"}
                    >
                      <RotateCcw size={15} aria-hidden="true" />
                      重新打开审改
                    </Button>
                  ) : null}
                  {detail.criteria_confirmed && !published && !criteriaDirty ? (
                    <Button
                      onClick={() =>
                        runAction("publish", () =>
                          publishQuestion(detail.id, {
                            command_id: crypto.randomUUID(),
                            content_revision: detail.content_revision,
                          }),
                        )
                      }
                      loading={acting === "publish"}
                    >
                      <Send size={15} aria-hidden="true" />
                      发布
                    </Button>
                  ) : null}
                </div>
              </>
            ) : null}
          </div>
        </div>
      </div>

      <Dialog
        open={saveConfirmOpen}
        title="保存评分维度"
        onClose={() => setSaveConfirmOpen(false)}
        footer={
          <>
            <Button variant="secondary" onClick={() => setSaveConfirmOpen(false)}>
              取消
            </Button>
            <Button onClick={() => void handleSaveCriteria()} loading={savingCriteria}>
              确认保存
            </Button>
          </>
        }
      >
        <p className={styles.dialogText}>
          保存后，未入选的候选维度将被永久丢弃，无法恢复。已选的
          {" "}{criterionDrafts.filter((d) => d.selected).length}{" "}
          个维度将成为最终评分标准。确定继续吗？
        </p>
      </Dialog>

      <Dialog
        open={deleteOpen}
        title="删除题目"
        onClose={() => setDeleteOpen(false)}
        footer={
          <>
            <Button variant="secondary" onClick={() => setDeleteOpen(false)} disabled={deleting}>
              取消
            </Button>
            <Button variant="danger" onClick={() => void handleDelete()} loading={deleting}>
              删除
            </Button>
          </>
        }
      >
        {detail.delete_confirmation_required ? (
          <div className={styles.dialogText}>
            <p>该题目曾经发布过。请输入当前完整题目标题以确认删除：</p>
            <TextField
              label="题目标题"
              value={deleteTitle}
              onChange={(e) => setDeleteTitle(e.target.value)}
              disabled={deleting}
            />
          </div>
        ) : (
          <p className={styles.dialogText}>确定删除题目「{detail.title}」吗？此操作不可撤销。</p>
        )}
      </Dialog>
    </div>
  );
}
