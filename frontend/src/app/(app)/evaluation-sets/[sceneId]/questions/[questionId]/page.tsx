"use client";

import { ArrowLeft, History, RotateCcw, Send, Trash2 } from "lucide-react";
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
import { GenerationTimeline } from "@/features/questions/components/generation-timeline";
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

const DELETE_POLL_INTERVAL_MS = 2000;

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
  const [regenConfirmOpen, setRegenConfirmOpen] = useState(false);

  // Criteria drafts.
  const [criterionDrafts, setCriterionDrafts] = useState<CriterionDraft[]>([]);
  const [criteriaDirty, setCriteriaDirty] = useState(false);
  const [savingCriteria, setSavingCriteria] = useState(false);
  const [criteriaError, setCriteriaError] = useState<string | null>(null);
  const [saveConfirmOpen, setSaveConfirmOpen] = useState(false);

  // Generation process replay (after completion).
  const [historyOpen, setHistoryOpen] = useState(false);

  // Actions.
  const [acting, setActing] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [staleMessage, setStaleMessage] = useState<string | null>(null);

  // Delete: acceptance -> durable cleanup -> leave only after 404.
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleteTitle, setDeleteTitle] = useState("");
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const deleteCommandRef = useRef<string | null>(null);

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
      return d;
    } catch (err) {
      if (controller.signal.aborted) return undefined;
      // A 404 while a deletion is in flight means cleanup finished: that is
      // the ONLY authoritative delete-success signal (not the 202 accept).
      // Covers both this session's accepted delete and a page reloaded while
      // the question was already frozen for deletion.
      if (
        err instanceof ApiError &&
        err.code === "RESOURCE_NOT_FOUND" &&
        (deleteCommandRef.current || detailRef.current?.status === "deleting")
      ) {
        router.replace(`/evaluation-sets/${detailRef.current?.scene_id ?? ""}`);
        return undefined;
      }
      // Keep the last good detail so a transient failure does not permanently
      // kill the page; only a first-load failure shows the full error state.
      if (hasDetailRef.current) return undefined;
      setDetail(null);
      if (err instanceof ApiError) setLoadError({ code: err.code, message: err.message });
      else setLoadError({ code: "UNKNOWN", message: "加载题目失败，请稍后重试。" });
      return undefined;
    }
  }, [questionId, applyDetail, router]);

  const detailRef = useRef<QuestionDetailResponse | null>(null);
  detailRef.current = detail;

  useEffect(() => {
    void load();
  }, [load]);

  // While the deletion cleanup runs, poll the authoritative detail until the
  // question 404s (handled inside load) — never navigate on the 202 alone.
  useEffect(() => {
    if (!detail || detail.status !== "deleting") return;
    const timer = setInterval(() => void load(), DELETE_POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [detail, load]);

  // Warn before leaving with unsaved changes (not while deleting).
  useEffect(() => {
    if (!dirty || detail?.status === "deleting") return;
    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [dirty, detail]);

  function describe(err: unknown, fallback: string): string {
    return err instanceof ApiError ? err.message : fallback;
  }

  /**
   * Bounded authoritative-detail refetch: if a reload right after a state
   * transition fails (transient network), retry a few times instead of
   * stranding the page on stale detail with no way back.
   */
  async function reloadUntilSettled(attempts = 4): Promise<void> {
    for (let i = 0; i < attempts; i += 1) {
      const d = await load();
      if (d) return;
      await new Promise((resolve) => setTimeout(resolve, 1200 * (i + 1)));
    }
  }

  // --- Materials ---
  function startEditMaterials(): void {
    if (!detail) return;
    setMaterialDraft(draftFromDetail(detail));
    setEditingMaterials(true);
  }

  function cancelEditMaterials(): void {
    // Cancel must not submit anything: no request, draft discarded.
    setMaterialDraft(null);
    setEditingMaterials(false);
    setRegenConfirmOpen(false);
  }

  async function submitMaterials(): Promise<void> {
    if (!detail || !materialDraft) return;
    setSavingMaterials(true);
    setStaleMessage(null);
    try {
      if (isOnlyTitleChanged(detail, materialDraft)) {
        // Title-only edits never trigger regeneration and need no confirm.
        const updated = await updateTitle(detail.id, {
          command_id: crypto.randomUUID(),
          content_revision: detail.content_revision,
          title: materialDraft.title,
        });
        setEditingMaterials(false);
        setMaterialDraft(null);
        applyDetail(updated);
      } else {
        const accepted = await saveRegenerate(
          detail.id,
          draftToPayload(materialDraft, {
            command_id: crypto.randomUUID(),
            content_revision: detail.content_revision,
          }),
        );
        setRegenConfirmOpen(false);
        setEditingMaterials(false);
        setMaterialDraft(null);
        setHistoryOpen(false);
        void accepted;
        await reloadUntilSettled();
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

  function handleSaveMaterials(): void {
    if (!detail || !materialDraft) return;
    if (isOnlyTitleChanged(detail, materialDraft)) {
      void submitMaterials();
      return;
    }
    // Material changes replace the ENTIRE rubric set (anchors, bases and any
    // manual edits included) after an explicit confirmation.
    setRegenConfirmOpen(true);
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
      setHistoryOpen(false);
      await load();
    } catch (err) {
      setActionError(describe(err, "操作失败，请稍后重试。"));
    } finally {
      setActing(null);
    }
  }

  // --- Delete (accepted -> cleanup -> 404 -> leave) ---
  async function handleDelete(): Promise<void> {
    if (!detail) return;
    setDeleting(true);
    setDeleteError(null);
    if (!deleteCommandRef.current) deleteCommandRef.current = crypto.randomUUID();
    try {
      await deleteQuestion(detail.id, {
        command_id: deleteCommandRef.current,
        content_revision: detail.content_revision,
        confirmation_title: detail.delete_confirmation_required ? deleteTitle : null,
      });
      // 202 = accepted, NOT deleted. Close the dialog, show the frozen
      // progress view and let the poll loop wait for the authoritative 404.
      setDeleteOpen(false);
      await load();
    } catch (err) {
      if (err instanceof ApiError && err.code === "RESOURCE_NOT_FOUND") {
        router.replace(`/evaluation-sets/${detail.scene_id}`);
        return;
      }
      setDeleteError(describe(err, "删除受理失败，请稍后重试。"));
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
  const frozenForDelete = detail.status === "deleting";

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
          {!published && !generating && !frozenForDelete ? (
            <Button
              variant="danger"
              onClick={() => {
                setDeleteTitle("");
                setDeleteError(null);
                setDeleteOpen(true);
              }}
            >
              <Trash2 size={15} aria-hidden="true" />
              删除题目
            </Button>
          ) : null}
        </div>
        {!editingMaterials && !published && !frozenForDelete ? (
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

      {frozenForDelete ? (
        <div className={styles.statusBox} data-testid="delete-progress">
          <p className={styles.statusNote}>
            删除已受理，正在清理该题的全部生成过程、运行上下文与在线副本；全部清理完成前不会显示删除成功。
          </p>
          {detail.deletion?.error ? (
            <ErrorPanel
              title="删除清理失败"
              message={detail.deletion.error.message || "清理未完成，可重试。"}
              action={
                <Button variant="danger" onClick={() => void handleDelete()} loading={deleting}>
                  重试删除清理
                </Button>
              }
            />
          ) : (
            <p className={styles.statusNote} data-testid="delete-phase">
              当前阶段：{detail.deletion?.phase === "running" ? "清理执行中" : "清理排队中"}
            </p>
          )}
        </div>
      ) : null}

      {!frozenForDelete ? (
        <div className={styles.columns}>
          <div className={styles.materialsCol}>
            {editingMaterials ? (
              <div className={styles.materialsEditBar}>
                <Button variant="secondary" onClick={cancelEditMaterials} disabled={savingMaterials}>
                  取消
                </Button>
                <Button onClick={handleSaveMaterials} loading={savingMaterials}>
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

              {generating && detail.active_operation_id ? (
                <div className={styles.statusBox} data-testid="generation-progress">
                  <GenerationTimeline
                    key={detail.active_operation_id}
                    questionId={detail.id}
                    operationId={detail.active_operation_id}
                    live
                    onDone={() => void reloadUntilSettled()}
                    onFrozen={() => void load()}
                    onGone={() => router.replace(`/evaluation-sets/${detail.scene_id}`)}
                  />
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
                  {detail.last_operation_id ? (
                    <GenerationTimeline
                      key={detail.last_operation_id}
                      questionId={detail.id}
                      operationId={detail.last_operation_id}
                      live={false}
                      ariaLabel="失败运行的完整过程记录"
                    />
                  ) : null}
                </div>
              ) : null}

              {!generating && detail.status !== "generation_failed" ? (
                <>
                  {detail.last_operation_id ? (
                    <div className={styles.historyBar}>
                      <Button variant="ghost" onClick={() => setHistoryOpen((v) => !v)}>
                        <History size={14} aria-hidden="true" />
                        {historyOpen ? "收起生成过程" : "查看完整生成过程"}
                      </Button>
                    </div>
                  ) : null}
                  {historyOpen && detail.last_operation_id ? (
                    <GenerationTimeline
                      key={detail.last_operation_id}
                      questionId={detail.id}
                      operationId={detail.last_operation_id}
                      live={false}
                    />
                  ) : null}

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
      ) : null}

      <Dialog
        open={regenConfirmOpen}
        title="重新生成将整套替换"
        onClose={() => setRegenConfirmOpen(false)}
        footer={
          <>
            <Button variant="secondary" onClick={() => setRegenConfirmOpen(false)} disabled={savingMaterials}>
              取消
            </Button>
            <Button onClick={() => void submitMaterials()} loading={savingMaterials} data-testid="regen-confirm">
              确认替换并重新生成
            </Button>
          </>
        }
      >
        <p className={styles.dialogText} data-testid="regen-confirm-text">
          材料修改后将启动整套重新生成：当前全部评分维度、分数说明、依据以及你做过的人工修改都会被新结果替换，且不可恢复。
          取消不会提交任何材料修改，也不会启动生成。确定继续吗？
        </p>
      </Dialog>

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
          个维度（含分数说明与依据的当前内容）将成为最终评分标准。确定继续吗？
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
            <Button variant="danger" onClick={() => void handleDelete()} loading={deleting} data-testid="delete-confirm">
              删除
            </Button>
          </>
        }
      >
        {detail.delete_confirmation_required ? (
          <div className={styles.dialogText}>
            <p>
              该题目曾经发布过。删除将一并清除该题的全部材料、历次生成过程、运行上下文与在线副本，且不可恢复。
              请输入当前完整题目标题以确认：
            </p>
            <TextField
              label="题目标题"
              value={deleteTitle}
              onChange={(e) => setDeleteTitle(e.target.value)}
              disabled={deleting}
            />
            {deleteError ? <p>{deleteError}</p> : null}
          </div>
        ) : (
          <p className={styles.dialogText}>
            确定删除题目「{detail.title}」吗？该题的全部生成过程与运行上下文将一并清除，此操作不可撤销。
          </p>
        )}
      </Dialog>
    </div>
  );
}
