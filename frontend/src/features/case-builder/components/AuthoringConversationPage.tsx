"use client";

import { useRouter } from "next/navigation";
import { type FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { DeskRail } from "@/src/components/shell/DeskRail";
import { AutoTextarea } from "@/src/components/ui/AutoTextarea";
import { Button, ButtonLink } from "@/src/components/ui/Button";
import { Field } from "@/src/components/ui/Field";
import { Note } from "@/src/components/ui/Note";
import { ConfirmSheet, Sheet } from "@/src/components/ui/Sheet";
import { SkeletonLine } from "@/src/components/ui/Skeleton";
import { StatePanel } from "@/src/components/ui/StatePanel";
import { UserChip } from "@/src/features/auth/components/UserChip";
import { useSession } from "@/src/features/auth/hooks/useSession";
import {
  confirmQuestionInputAnswer,
  getAuthoringConversation,
  mutateQuestionBoundaries,
  patchQuestionInputAnswer,
  postAuthoringMessage,
  readAuthoringEvents,
  resetAuthoringContinuity,
  retryAuthoringConversation,
  type AuthoringConversation,
  type AuthoringStreamEvent,
} from "@/src/features/case-builder/services/authoringService";
import { loginHref, toPageFault, type PageFault } from "@/src/lib/api/pageFault";
import { PreviewBar, useAuthoringPreviewState } from "@/src/lib/preview/preview";
import type { components } from "@/src/lib/api/generated";

import styles from "./authoring.module.css";

type QuestionDraft = NonNullable<AuthoringConversation["question_drafts"]>[number];
type MaterialRole = components["schemas"]["QuestionMaterialRole"];
type Message = NonNullable<AuthoringConversation["messages"]>[number];

type Load =
  | { status: "loading" }
  | { status: "ready"; conversation: AuthoringConversation }
  | { status: "failed"; fault: PageFault };

type DraftForm = {
  taskInstruction: string;
  mustInclude: string;
  prohibited: string;
  background: string;
  referenceAnswer: string;
  materials: Array<{
    fileId: string;
    fileName: string;
    role: MaterialRole;
    priority: number;
    rationale: string;
  }>;
};

const STATUS_LABEL: Record<AuthoringConversation["status"], string> = {
  queued: "等待处理",
  processing: "AI 整理中",
  waiting_for_teacher: "需要补充",
  review_ready: "待审阅",
  ready: "可以继续",
  confirmed: "已确认",
  failed: "整理失败",
  projection_pending: "等待恢复",
  continuity_reset: "需要重建连续性",
};

const STATUS_CLASS: Record<AuthoringConversation["status"], string> = {
  queued: "state-active",
  processing: "state-active",
  waiting_for_teacher: "state-amber",
  review_ready: "state-neutral",
  ready: "state-neutral",
  confirmed: "state-green",
  failed: "state-red",
  projection_pending: "state-amber",
  continuity_reset: "state-amber",
};

const ROLE_LABEL: Record<MaterialRole, string> = {
  unconfirmed: "未确认",
  brief: "任务说明",
  fact: "事实输入",
  style: "风格参考",
  current_draft: "当前稿",
  background: "辅助背景",
  ignored: "忽略",
};

function commandId(prefix: string) {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function previewConversation(
  state: "empty" | "question" | "review" | "success" | "processing" | "failed" | "projection_pending" | "continuity_reset",
): AuthoringConversation {
  const now = new Date().toISOString();
  const draft: QuestionDraft = {
    id: "preview-draft",
    conversation_id: "preview-conversation",
    title: "媒体供稿题",
    summary: "根据老师确认的真实资料形成一份可直接使用的供稿。",
    status: state === "processing"
      ? "input_answer_drafting"
      : state === "success"
      ? "input_answer_confirmed"
      : state === "question"
        ? "input_answer_drafting"
        : state === "review"
          ? "input_answer_review"
          : "candidate",
    revision: 1,
    input: {
      task_instruction: "根据资料形成一份事实准确的新闻稿。",
      materials: [],
      must_include: ["事实来源"],
      prohibited: ["无来源推断"],
      background: "这是开发态的会话状态预演。",
    },
    reference_answer_text: state === "empty" || state === "question" ? null : "老师明确认可的参考结果。",
    reference_answer_source: state === "empty" || state === "question" ? null : "teacher_input",
    evidence_file_ids: [],
    materials: [],
    confirmed_revision: state === "success" ? 1 : null,
    confirmed_at: state === "success" ? now : null,
  };
  return {
    id: "preview-conversation",
    workspace_id: "preview-workspace",
    upload_batch_id: null,
    source_file_count: 0,
    title: "媒体供稿题",
    status: state === "question"
      ? "waiting_for_teacher"
      : state === "success"
        ? "confirmed"
        : state === "processing"
          ? "processing"
          : state === "failed"
            ? "failed"
            : state === "projection_pending"
              ? "projection_pending"
              : state === "continuity_reset"
                ? "continuity_reset"
                : "review_ready",
    revision: 2,
    messages: [
      { id: "preview-message-1", sequence: 1, role: "teacher", message_type: "chat", content: "我想把这次真实供稿沉淀成一道题。", attachment_ids: [], question_draft_id: null, created_at: now },
      { id: "preview-message-2", sequence: 2, role: "assistant", message_type: "chat", content: state === "question" ? "我已整理出候选题。还缺一项需要你确认的信息。" : "我已整理出候选题，请先审阅边界和标准答案。", attachment_ids: [], question_draft_id: null, created_at: now },
    ],
    question_drafts: state === "empty" ? [] : [draft],
    pending_question: state === "question"
      ? { id: "preview-question", text: "请提供这道题的老师终版或明确认可的标准答案。", reason: "不能把 AI 候选当作标准答案。", gap_type: "standard_answer", question_draft_id: "preview-draft" }
      : state === "continuity_reset"
        ? { id: "preview-reset", text: "会话连续性需要重新建立。", reason: "系统只会从已保存的业务快照继续。", gap_type: "evidence", question_draft_id: null }
      : null,
    next_action: state === "question"
      ? "provide_standard_answer"
      : state === "empty"
        ? "none"
        : state === "success"
        ? "none"
        : state === "failed" || state === "projection_pending"
          ? "retry_processing"
          : state === "continuity_reset"
            ? "continuity_reset"
              : state === "processing"
                ? "wait_for_processing"
                : state === "review"
                  ? "confirm_input_answer"
                  : "confirm_question_boundaries",
    active_operation: state === "processing"
      ? { kind: "authoring_process", status: "running" }
      : state === "projection_pending"
        ? { kind: "authoring_reproject", status: "projection_pending" }
        : state === "failed"
          ? { kind: "authoring_process", status: "failed" }
          : null,
    events_cursor: 2,
    blocking_issues: [],
    created_at: now,
    updated_at: now,
  };
}

function draftFormFrom(draft: QuestionDraft): DraftForm {
  return {
    taskInstruction: draft.input.task_instruction,
    mustInclude: (draft.input.must_include ?? []).join("\n"),
    prohibited: (draft.input.prohibited ?? []).join("\n"),
    background: draft.input.background ?? "",
    referenceAnswer: draft.reference_answer_text ?? "",
    materials: (draft.materials ?? []).map((item) => ({
      fileId: item.file_id,
      fileName: item.file_name ?? "资料文件",
      role: item.role,
      priority: item.priority,
      rationale: item.rationale ?? "",
    })),
  };
}

function lines(value: string) {
  return value.split(/\r?\n/).map((item) => item.trim()).filter(Boolean);
}

export function AuthoringConversationPage({
  workspaceId,
  conversationId,
}: {
  workspaceId: string;
  conversationId: string;
}) {
  const router = useRouter();
  const preview = useAuthoringPreviewState();
  const session = useSession();
  const reloadSession = session.reload;
  const returnTo = `/workspaces/${workspaceId}/authoring/${conversationId}`;
  const [load, setLoad] = useState<Load>({ status: "loading" });
  const [busy, setBusy] = useState<string | null>(null);
  const [fault, setFault] = useState<PageFault | null>(null);
  const [composer, setComposer] = useState("");
  const [selectedAttachmentIds, setSelectedAttachmentIds] = useState<string[]>([]);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [selectedDraftId, setSelectedDraftId] = useState<string | null>(null);
  const [draftForm, setDraftForm] = useState<DraftForm | null>(null);
  const [showSources, setShowSources] = useState(false);
  const [streamEvents, setStreamEvents] = useState<AuthoringStreamEvent[]>([]);
  const generation = useRef(0);
  const routeGeneration = useRef(0);
  const lastDraftRevision = useRef<{ id: string; revision: number } | null>(null);
  const pendingCommands = useRef(new Map<string, { fingerprint: string; id: string }>());

  useEffect(() => {
    routeGeneration.current += 1;
    pendingCommands.current.clear();
    setBusy(null);
    setFault(null);
    setComposer("");
    setSelectedAttachmentIds([]);
    setStreamEvents([]);
    setSelectedIds([]);
    setSelectedDraftId(null);
    setDraftForm(null);
    lastDraftRevision.current = null;
  }, [conversationId, preview, workspaceId]);

  const read = useCallback(async (silent: boolean) => {
    const currentGeneration = ++generation.current;
    if (!silent) setLoad({ status: "loading" });
    try {
      const result = await getAuthoringConversation(workspaceId, conversationId);
      if (currentGeneration !== generation.current) return;
      setLoad({ status: "ready", conversation: result.conversation });
      setFault(null);
    } catch (cause: unknown) {
      if (currentGeneration !== generation.current) return;
      const pageFault = toPageFault(cause);
      if (silent && pageFault.kind === "failed") {
        // A transient GET failure must not blank an already authorized
        // snapshot; the timer/SSE loop will retry.  Auth and resource errors
        // still take the normal fail-closed path below.
        setFault(pageFault);
        return;
      }
      setLoad({ status: "failed", fault: pageFault });
      if (pageFault.kind === "unauthorized") reloadSession();
    }
  }, [conversationId, reloadSession, workspaceId]);

  useEffect(() => {
    if (preview) {
      if (preview === "loading") setLoad({ status: "loading" });
      else if (preview === "error") setLoad({ status: "failed", fault: { kind: "failed", code: "PREVIEW_ERROR", message: "开发态预演错误。" } });
      else if (
        preview === "empty"
        || preview === "question"
        || preview === "review"
        || preview === "success"
        || preview === "processing"
        || preview === "failed"
        || preview === "projection_pending"
        || preview === "continuity_reset"
      ) {
        setLoad({ status: "ready", conversation: previewConversation(preview) });
      }
      return;
    }
    if (session.status !== "authenticated") return;
    void read(false);
    return () => {
      generation.current += 1;
    };
  }, [preview, read, session.status]);

  const loadedConversation = load.status === "ready" ? load.conversation : null;
  const conversationStatus = loadedConversation?.status ?? null;
  const eventsCursor = loadedConversation?.events_cursor ?? null;

  useEffect(() => {
    if (preview || conversationStatus === null || eventsCursor === null) return;
    if (conversationStatus !== "queued" && conversationStatus !== "processing" && conversationStatus !== "projection_pending") return;
    let active = true;
    const streamController = new AbortController();
    const currentRouteGeneration = routeGeneration.current;
    void readAuthoringEvents(workspaceId, conversationId, eventsCursor, streamController.signal)
      .then((events) => {
        if (!active || currentRouteGeneration !== routeGeneration.current) return;
        if (events.length > 0) setStreamEvents((current) => [...current, ...events].slice(-20));
        void read(true);
      })
      .catch((cause: unknown) => {
        if (!active || currentRouteGeneration !== routeGeneration.current) return;
        const pageFault = toPageFault(cause);
        if (pageFault.kind === "unauthorized" || pageFault.kind === "forbidden" || pageFault.kind === "not_found") {
          setLoad({ status: "failed", fault: pageFault });
          if (pageFault.kind === "unauthorized") reloadSession();
        } else {
          void read(true);
        }
      });
    let timer: number | null = null;
    const scheduleSnapshotRead = () => {
      timer = window.setTimeout(() => {
        if (!active) return;
        void read(true).finally(() => {
          if (active) scheduleSnapshotRead();
        });
      }, 1_800);
    };
    scheduleSnapshotRead();
    return () => {
      active = false;
      streamController.abort();
      if (timer !== null) window.clearTimeout(timer);
    };
  }, [conversationId, conversationStatus, eventsCursor, preview, read, reloadSession, workspaceId]);

  const conversation = loadedConversation;
  const activeDrafts = useMemo(
    () => (conversation?.question_drafts ?? []).filter((draft) => draft.status !== "discarded"),
    [conversation?.question_drafts],
  );
  const selectedDraft = activeDrafts.find((draft) => draft.id === selectedDraftId) ?? activeDrafts[0] ?? null;
  const attachmentOptions = useMemo(() => {
    const seen = new Set<string>();
    return activeDrafts.flatMap((draft) => (draft.materials ?? []).flatMap((material) => {
      if (seen.has(material.file_id)) return [];
      seen.add(material.file_id);
      return [{ id: material.file_id, name: material.file_name ?? "资料文件" }];
    }));
  }, [activeDrafts]);
  const pending = conversation?.pending_question ?? null;
  const processing = conversation?.status === "queued" || conversation?.status === "processing" || conversation?.status === "projection_pending";
  const standardAnswerMode = pending?.gap_type === "standard_answer";

  useEffect(() => {
    if (!conversation) return;
    if (!selectedDraftId || !activeDrafts.some((draft) => draft.id === selectedDraftId)) {
      setSelectedDraftId(activeDrafts[0]?.id ?? null);
    }
    if (conversation.next_action === "confirm_question_boundaries" && selectedIds.length === 0) {
      setSelectedIds(activeDrafts.filter((draft) => draft.status === "candidate").map((draft) => draft.id));
    }
  }, [activeDrafts, conversation, selectedDraftId, selectedIds.length]);

  useEffect(() => {
    if (!selectedDraft) {
      setDraftForm(null);
      lastDraftRevision.current = null;
      return;
    }
    if (
      lastDraftRevision.current?.id === selectedDraft.id
      && lastDraftRevision.current.revision === selectedDraft.revision
      && draftForm
    ) return;
    setDraftForm(draftFormFrom(selectedDraft));
    lastDraftRevision.current = { id: selectedDraft.id, revision: selectedDraft.revision };
  }, [draftForm, selectedDraft]);

  function updateConversation(next: AuthoringConversation, expectedRouteGeneration = routeGeneration.current) {
    if (expectedRouteGeneration !== routeGeneration.current) return;
    setLoad({ status: "ready", conversation: next });
    setFault(null);
  }

  function stableCommand(scope: string, payload: unknown) {
    const fingerprint = JSON.stringify(payload);
    const existing = pendingCommands.current.get(scope);
    if (existing?.fingerprint === fingerprint) return existing;
    const next = { fingerprint, id: commandId(scope) };
    pendingCommands.current.set(scope, next);
    return next;
  }

  function clearStableCommand(scope: string, fingerprint: string) {
    if (pendingCommands.current.get(scope)?.fingerprint === fingerprint) {
      pendingCommands.current.delete(scope);
    }
  }

  function handleCommandError(cause: unknown, expectedRouteGeneration: number) {
    if (expectedRouteGeneration !== routeGeneration.current) return;
    const pageFault = toPageFault(cause);
    if (pageFault.kind === "unauthorized" || pageFault.kind === "forbidden" || pageFault.kind === "not_found") {
      setLoad({ status: "failed", fault: pageFault });
      if (pageFault.kind === "unauthorized") reloadSession();
      return;
    }
    setFault(pageFault);
    if (pageFault.kind === "conflict") void read(true);
  }

  async function submitMessage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!conversation || !composer.trim() || processing || busy) return;
    const requestRouteGeneration = routeGeneration.current;
    const messageInput = {
      content: composer.trim(),
      message_type: standardAnswerMode ? "standard_answer" as const : "chat" as const,
      question_draft_id: standardAnswerMode ? pending?.question_draft_id ?? null : null,
      attachment_ids: selectedAttachmentIds,
    };
    const stable = stableCommand("teacher-message", messageInput);
    setBusy("message");
    setFault(null);
    try {
      const result = await postAuthoringMessage(workspaceId, conversationId, {
        command_id: stable.id,
        conversation_revision: conversation.revision,
        ...messageInput,
      });
      if (requestRouteGeneration !== routeGeneration.current) return;
      updateConversation(result.conversation, requestRouteGeneration);
      clearStableCommand("teacher-message", stable.fingerprint);
      setComposer("");
      setSelectedAttachmentIds([]);
    } catch (cause: unknown) {
      handleCommandError(cause, requestRouteGeneration);
    } finally {
      if (requestRouteGeneration === routeGeneration.current) setBusy(null);
    }
  }

  async function changeBoundaries(action: "confirm" | "split" | "merge" | "discard", ids = selectedIds, groups: components["schemas"]["QuestionBoundaryGroupInput"][] = []) {
    if (!conversation || ids.length === 0 || busy) return;
    const requestRouteGeneration = routeGeneration.current;
    const stable = stableCommand("boundary", { action, ids, groups });
    setBusy("boundary");
    setFault(null);
    try {
      const result = await mutateQuestionBoundaries(workspaceId, conversationId, {
        command_id: stable.id,
        conversation_revision: conversation.revision,
        action,
        draft_ids: ids,
        groups,
      });
      if (requestRouteGeneration !== routeGeneration.current) return;
      updateConversation(result.conversation, requestRouteGeneration);
      clearStableCommand("boundary", stable.fingerprint);
      setSelectedIds([]);
    } catch (cause: unknown) {
      handleCommandError(cause, requestRouteGeneration);
    } finally {
      if (requestRouteGeneration === routeGeneration.current) setBusy(null);
    }
  }

  async function saveDraft() {
    if (!conversation || !selectedDraft || !draftForm || busy) return;
    const requestRouteGeneration = routeGeneration.current;
    const draftInput = {
      input: {
        task_instruction: draftForm.taskInstruction.trim(),
        materials: draftForm.materials.map((item) => ({
          file_id: item.fileId,
          role: item.role,
          priority: item.priority,
          rationale: item.rationale.trim() || null,
        })),
        must_include: lines(draftForm.mustInclude),
        prohibited: lines(draftForm.prohibited),
        background: draftForm.background.trim() || null,
      },
      reference_answer_text: draftForm.referenceAnswer.trim() || null,
    };
    const stable = stableCommand("draft-input", { draftId: selectedDraft.id, ...draftInput });
    setBusy("draft");
    setFault(null);
    try {
      const result = await patchQuestionInputAnswer(workspaceId, conversationId, selectedDraft.id, {
        command_id: stable.id,
        draft_revision: selectedDraft.revision,
        ...draftInput,
      });
      if (requestRouteGeneration !== routeGeneration.current) return;
      updateConversation(result.conversation, requestRouteGeneration);
      clearStableCommand("draft-input", stable.fingerprint);
    } catch (cause: unknown) {
      handleCommandError(cause, requestRouteGeneration);
    } finally {
      if (requestRouteGeneration === routeGeneration.current) setBusy(null);
    }
  }

  async function confirmDraft() {
    if (!conversation || !selectedDraft || busy) return;
    const requestRouteGeneration = routeGeneration.current;
    const stable = stableCommand("draft-confirm", {
      draftId: selectedDraft.id,
      draftRevision: selectedDraft.revision,
    });
    setBusy("confirm");
    setFault(null);
    try {
      const result = await confirmQuestionInputAnswer(workspaceId, conversationId, selectedDraft.id, {
        command_id: stable.id,
        draft_revision: selectedDraft.revision,
      });
      if (requestRouteGeneration !== routeGeneration.current) return;
      updateConversation(result.conversation, requestRouteGeneration);
      clearStableCommand("draft-confirm", stable.fingerprint);
      if (requestRouteGeneration !== routeGeneration.current) return;
      const nextDraft = (result.conversation.question_drafts ?? []).find(
        (item) => item.status !== "discarded" && item.status !== "input_answer_confirmed",
      );
      setSelectedDraftId(nextDraft?.id ?? null);
    } catch (cause: unknown) {
      handleCommandError(cause, requestRouteGeneration);
    } finally {
      if (requestRouteGeneration === routeGeneration.current) setBusy(null);
    }
  }

  async function retry() {
    if (!conversation || busy) return;
    const requestRouteGeneration = routeGeneration.current;
    const stable = stableCommand("authoring-retry", { conversationRevision: conversation.revision });
    setBusy("retry");
    setFault(null);
    try {
      const result = await retryAuthoringConversation(workspaceId, conversationId, {
        command_id: stable.id,
        conversation_revision: conversation.revision,
      });
      if (requestRouteGeneration !== routeGeneration.current) return;
      updateConversation(result.conversation, requestRouteGeneration);
      clearStableCommand("authoring-retry", stable.fingerprint);
    } catch (cause: unknown) {
      handleCommandError(cause, requestRouteGeneration);
    } finally {
      if (requestRouteGeneration === routeGeneration.current) setBusy(null);
    }
  }

  async function resetContinuity() {
    if (!conversation || busy) return;
    const requestRouteGeneration = routeGeneration.current;
    const stable = stableCommand("authoring-reset", {
      conversationRevision: conversation.revision,
      reason: "从已保存的业务快照重新建立会话连续性。",
    });
    setBusy("reset");
    setFault(null);
    try {
      const result = await resetAuthoringContinuity(workspaceId, conversationId, {
        command_id: stable.id,
        reason: "从已保存的业务快照重新建立会话连续性。",
      });
      if (requestRouteGeneration !== routeGeneration.current) return;
      updateConversation(result.conversation, requestRouteGeneration);
      clearStableCommand("authoring-reset", stable.fingerprint);
    } catch (cause: unknown) {
      handleCommandError(cause, requestRouteGeneration);
    } finally {
      if (requestRouteGeneration === routeGeneration.current) setBusy(null);
    }
  }

  const rail = (
    <DeskRail
      crumbs={[
        { label: "场景", href: "/workspaces" },
        { label: !preview && session.status !== "authenticated" ? "建题会话" : conversation?.title ?? "建题会话" },
      ]}
      right={<UserChip previewName={preview ? "teacher-a" : undefined} session={session} />}
    />
  );
  const previewBar = <PreviewBar states={["loading", "empty", "question", "review", "success", "processing", "failed", "projection_pending", "continuity_reset", "error", "unauthorized", "forbidden", "not_found"]} />;

  if (preview === "unauthorized" || (!preview && session.status === "anonymous")) {
    return (
      <>
        {rail}
        {previewBar}
        <main className="page page-mid">
          <StatePanel actions={<ButtonLink href={loginHref(returnTo)} variant="primary">去登录</ButtonLink>} description="登录后才能查看这条建题会话。" title="需要登录" tone="locked" />
        </main>
      </>
    );
  }

  if (!preview && session.status === "loading") {
    return (
      <>
        {rail}
        {previewBar}
        <main className="page authoring-page stack-lg">
          <SkeletonLine height={28} width="42%" />
          <section aria-busy="true" className="sheet sheet-pad stack-lg">
            <SkeletonLine height={18} width="65%" />
            <SkeletonLine height={96} />
            <SkeletonLine height={76} />
          </section>
        </main>
      </>
    );
  }

  if (!preview && session.status === "failed") {
    return (
      <>
        {rail}
        {previewBar}
        <main className="page page-mid">
          <StatePanel
            actions={<Button onClick={reloadSession} variant="primary">重新验证登录</Button>}
            code={session.fault.code}
            description={session.fault.message}
            title="登录状态读取失败"
            tone="fault"
          />
        </main>
      </>
    );
  }

  if (load.status === "failed") {
    return (
      <>
        {rail}
        {previewBar}
        <main className="page page-mid">
          <StatePanel
            actions={<Button onClick={() => void read(false)} variant="primary">重新读取</Button>}
            code={load.fault.code}
            description={load.fault.message}
            title="建题会话读取失败"
            tone="fault"
          />
        </main>
      </>
    );
  }

  if (load.status === "loading" || !conversation) {
    return (
      <>
        {rail}
        {previewBar}
        <main className="page authoring-page stack-lg">
          <SkeletonLine height={28} width="42%" />
          <section aria-busy="true" className="sheet sheet-pad stack-lg">
            <SkeletonLine height={18} width="65%" />
            <SkeletonLine height={96} />
            <SkeletonLine height={76} />
          </section>
        </main>
      </>
    );
  }

  const currentStatus = conversation.status;
  const title = STATUS_LABEL[currentStatus];
  const lastEventValue = streamEvents.at(-1)?.payload.label ?? streamEvents.at(-1)?.payload.text;
  const lastEventLabel = typeof lastEventValue === "string" ? lastEventValue : null;

  return (
    <>
      {rail}
      {previewBar}
      <main className={`${styles.page} page stack-lg`} data-testid="authoring-conversation">
        <header className={styles.header}>
          <div className="stack-sm">
            <span className="section-label">建题会话</span>
            <h1 className="doc-title">{conversation.title}</h1>
            <p className="secondary">题目输入与标准答案 · 修订 {conversation.revision}</p>
          </div>
          <span className={`state ${STATUS_CLASS[currentStatus]}`} data-testid="authoring-status">
            <span className={`dot${processing ? " pulse-dot" : ""}`} />
            {title}
          </span>
        </header>

        {fault && (
          <Note code={fault.code} title="操作没有完成" tone="fail">
            {fault.message}
          </Note>
        )}

        {processing && (
          <section aria-live="polite" className={styles.processingLine} data-testid="authoring-processing">
            <span className="dot pulse-dot" />
            <span>{currentStatus === "projection_pending" ? "整理结果已保存，正在恢复业务快照。" : "AI 正在整理，完成后会回到这条会话。"}</span>
            {lastEventLabel && <span className="muted">· {String(lastEventLabel)}</span>}
          </section>
        )}

        <div className={styles.workspace}>
          <section className={`${styles.transcript} stack`} aria-label="会话记录">
            <div className={styles.transcriptLabel}>
              <span className="section-label">形成过程</span>
              <button className="btn btn-quiet btn-sm" onClick={() => setShowSources(true)} type="button">
                查看资料范围
              </button>
            </div>
            {(conversation.messages ?? []).length === 0 ? (
              <div className="inset" style={{ padding: "var(--s-6)" }}>
                <p className="secondary">这条会话还没有公开消息。</p>
              </div>
            ) : (
              (conversation.messages ?? []).map((message) => <TranscriptMessage key={message.id} message={message} />)
            )}
            {conversation.pending_question && (
              <section className={styles.questionCard} data-testid="authoring-pending-question">
                <span className="section-label">需要补充</span>
                <h2 className="doc-title-sm">{conversation.pending_question.text}</h2>
                <p className="secondary">为什么问：{conversation.pending_question.reason}</p>
              </section>
            )}
          </section>

          <section className={styles.nextAction} aria-label="当前下一步">
            <span className="section-label">下一步</span>
            {conversation.next_action === "confirm_question_boundaries" && (
              <BoundaryPanel
                busy={busy !== null}
                drafts={activeDrafts.filter((draft) => draft.status === "candidate")}
                selectedIds={selectedIds}
                onDiscard={() => void changeBoundaries("discard")}
                onMerge={() => void changeBoundaries("merge")}
                onSplit={(draftId, groups) => void changeBoundaries("split", [draftId], groups)}
                onSelect={(id) => setSelectedIds((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id])}
                onConfirm={() => void changeBoundaries("confirm")}
              />
            )}
            {(conversation.next_action === "provide_standard_answer" || conversation.next_action === "confirm_input_answer" || conversation.next_action === "review_question" || (processing && activeDrafts.some((draft) => draft.status !== "candidate"))) && (
              <>
                {activeDrafts.length > 1 && (
                  <DraftTrack
                    drafts={activeDrafts}
                    selectedId={selectedDraft?.id ?? null}
                    onSelect={setSelectedDraftId}
                  />
                )}
                <DraftReview
                  busy={busy !== null}
                  draft={selectedDraft}
                  form={draftForm}
                  processing={processing}
                  onChange={setDraftForm}
                  onSave={() => void saveDraft()}
                  onConfirm={() => void confirmDraft()}
                  canConfirm={!processing && conversation.next_action !== "provide_standard_answer"}
                />
              </>
            )}
            {(currentStatus === "failed" || currentStatus === "projection_pending" || conversation.next_action === "retry_processing") && (
              <section className="sheet sheet-pad stack">
                <h2 className="doc-title-sm">{currentStatus === "projection_pending" ? "结果等待恢复" : "本轮整理失败"}</h2>
                <p className="secondary">已保存的老师消息和题稿不会丢失，可以从当前快照继续。</p>
                <Button busy={busy === "retry"} busyLabel="正在重试…" onClick={() => void retry()} variant="primary">重试整理</Button>
              </section>
            )}
            {currentStatus === "continuity_reset" && (
              <section className="sheet sheet-pad stack">
                <h2 className="doc-title-sm">需要重新建立连续性</h2>
                <p className="secondary">系统保留了已保存内容；重置只会从业务快照开始，不会暴露内部运行信息。</p>
                <Button busy={busy === "reset"} busyLabel="正在重置…" onClick={() => void resetContinuity()} variant="primary">从当前快照继续</Button>
              </section>
            )}
            {conversation.next_action === "none" && currentStatus !== "confirmed" && <p className="secondary">当前没有需要你处理的动作。</p>}
            {currentStatus === "confirmed" && (
              <section className="sheet sheet-pad stack">
                <span className="state state-green"><span className="dot" />题目输入与标准答案已确认</span>
                <p className="secondary">下一阶段会在后续流程中生成评分规则；这里不会把 AI 候选当作发布事实。</p>
              </section>
            )}
          </section>
        </div>

        <form className={styles.composer} onSubmit={submitMessage}>
          <div className={styles.composerMeta}>
            <span className="section-label">{standardAnswerMode ? "补充标准答案" : "继续这条会话"}</span>
            {processing && <span className="secondary">可先编辑草稿，等本轮完成后再发送</span>}
          </div>
          {attachmentOptions.length > 0 && (
            <fieldset className={styles.attachmentPicker} data-testid="authoring-attachment-picker">
              <legend className="section-label">本轮资料（可选）</legend>
              <div className={styles.attachmentOptions}>
                {attachmentOptions.map((attachment) => (
                  <label className={styles.attachmentOption} key={attachment.id}>
                    <input
                      checked={selectedAttachmentIds.includes(attachment.id)}
                      disabled={busy === "message"}
                      onChange={() => setSelectedAttachmentIds((current) => current.includes(attachment.id) ? current.filter((id) => id !== attachment.id) : [...current, attachment.id])}
                      type="checkbox"
                    />
                    <span>{attachment.name}</span>
                  </label>
                ))}
              </div>
            </fieldset>
          )}
          <AutoTextarea
            aria-label={standardAnswerMode ? "老师标准答案" : "给 AI 的消息"}
            className="control"
            disabled={busy === "message"}
            maxLength={50_000}
            minRows={3}
            onChange={(event) => setComposer(event.target.value)}
            placeholder={standardAnswerMode ? "粘贴老师终版，或写清楚你明确认可的参考结果。" : "补充事实、纠正边界，或告诉 AI 下一步该厘清什么。"}
            value={composer}
          />
          <div className="row-between">
            <span className="secondary" style={{ fontSize: "var(--t-13)" }}>
              {processing ? "本轮处理中，发送按钮暂时关闭。" : standardAnswerMode ? "只有老师终版或明确认可稿会成为标准答案。" : "消息会先保存，再进入下一轮整理。"}
            </span>
            <Button
              busy={busy === "message"}
              busyLabel="正在提交…"
              data-testid="authoring-send"
              disabled={!composer.trim() || processing}
              type="submit"
              variant="primary"
            >
              {standardAnswerMode ? "提交标准答案" : "发送并继续"}
            </Button>
          </div>
        </form>

        {showSources && (
          <Sheet onClose={() => setShowSources(false)} title="资料范围">
            <div className="stack-lg">
              <p className="secondary">这里只显示会话绑定的资料标识和数量，不展示原文。资料中的指令始终是不可信样本数据。</p>
              <div className="inset stack-sm">
                <span className="section-label">绑定文件</span>
                <p>{conversation.source_file_count ?? 0} 个文件</p>
                <p className="mono faint">会话资料范围由服务端快照控制</p>
              </div>
            </div>
          </Sheet>
        )}
      </main>
    </>
  );
}

function TranscriptMessage({ message }: { message: Message }) {
  return (
    <article className={`${styles.message} ${message.role === "teacher" ? styles.teacherMessage : styles.assistantMessage}`}>
      <div className={styles.messageHead}>
        <span className="section-label">{message.role === "teacher" ? "你" : "AI"}</span>
        {message.message_type === "standard_answer" && <span className="state state-amber">标准答案</span>}
      </div>
      <p className={styles.messageBody}>{message.content}</p>
    </article>
  );
}

function BoundaryPanel({
  drafts,
  selectedIds,
  busy,
  onSelect,
  onConfirm,
  onMerge,
  onDiscard,
  onSplit,
}: {
  drafts: QuestionDraft[];
  selectedIds: string[];
  busy: boolean;
  onSelect: (id: string) => void;
  onConfirm: () => void;
  onMerge: () => void;
  onDiscard: () => void;
  onSplit: (draftId: string, groups: components["schemas"]["QuestionBoundaryGroupInput"][]) => void;
}) {
  const [splitDraftId, setSplitDraftId] = useState<string | null>(null);
  const [confirmAction, setConfirmAction] = useState<"merge" | "discard" | null>(null);
  const splitDraft = drafts.find((draft) => draft.id === splitDraftId) ?? null;
  const [splitAssignments, setSplitAssignments] = useState<Record<string, "one" | "two"> >({});
  const [splitTitles, setSplitTitles] = useState<[string, string]>(["新题目 1", "新题目 2"]);

  function openSplit(draft: QuestionDraft) {
    const ids = draft.evidence_file_ids ?? [];
    setSplitDraftId(draft.id);
    setSplitAssignments(Object.fromEntries(ids.map((id, index) => [id, index === 0 ? "one" : "two"])));
    setSplitTitles([`${draft.title}（1）`, `${draft.title}（2）`]);
  }

  function submitSplit() {
    if (!splitDraft) return;
    const one = (splitDraft.evidence_file_ids ?? []).filter((id) => splitAssignments[id] === "one");
    const two = (splitDraft.evidence_file_ids ?? []).filter((id) => splitAssignments[id] === "two");
    if (one.length === 0 || two.length === 0 || !splitTitles[0].trim() || !splitTitles[1].trim()) return;
    onSplit(splitDraft.id, [
      { title: splitTitles[0].trim(), summary: "老师拆分后的独立任务。", evidence_file_ids: one },
      { title: splitTitles[1].trim(), summary: "老师拆分后的独立任务。", evidence_file_ids: two },
    ]);
    setSplitDraftId(null);
  }

  return (
    <section className="sheet sheet-pad stack" data-testid="authoring-boundaries">
      <div className="stack-sm">
        <h2 className="doc-title-sm">先确认题目边界</h2>
        <p className="secondary">AI 只提出候选；不同交付物要分成不同题，资料范围由你决定。</p>
      </div>
      <div className={styles.draftList}>
        {drafts.map((draft, index) => (
          <label className={styles.draftOption} key={draft.id}>
            <input checked={selectedIds.includes(draft.id)} disabled={busy} onChange={() => onSelect(draft.id)} type="checkbox" />
            <span className="stack-sm">
              <strong>{draft.title || `候选题 ${index + 1}`}</strong>
              <span className="secondary">{draft.summary}</span>
              <span className="mono faint">{draft.evidence_file_ids?.length ?? 0} 个资料文件</span>
            </span>
          </label>
        ))}
      </div>
      <div className="row">
        <Button busy={busy} busyLabel="正在确认…" disabled={selectedIds.length === 0} onClick={onConfirm} variant="primary">确认选中题目</Button>
        <Button disabled={busy || selectedIds.length < 2} onClick={() => setConfirmAction("merge")} variant="secondary">合并选中</Button>
        <Button
          disabled={busy || selectedIds.length !== 1 || (drafts.find((draft) => draft.id === selectedIds[0])?.evidence_file_ids?.length ?? 0) < 2}
          onClick={() => {
            const draft = drafts.find((item) => item.id === selectedIds[0]);
            if (draft) openSplit(draft);
          }}
          variant="secondary"
        >
          拆分为两题
        </Button>
        <Button disabled={busy || selectedIds.length === 0} onClick={() => setConfirmAction("discard")} variant="quiet">舍弃选中</Button>
      </div>
      {splitDraft && (
        <section className="inset stack" aria-label="拆分题目">
          <div className="stack-sm">
            <strong>把资料分到两道题</strong>
            <span className="secondary">每道题至少保留一份资料；拆分后仍需分别审阅标准答案。</span>
          </div>
          <div className="row">
            {[0, 1].map((index) => (
              <input
                aria-label={`拆分题目 ${index + 1} 名称`}
                className="control"
                key={index}
                onChange={(event) => setSplitTitles((current) => {
                  const next: [string, string] = [...current] as [string, string];
                  next[index] = event.target.value;
                  return next;
                })}
                disabled={busy}
                value={splitTitles[index]}
              />
            ))}
          </div>
          <div className="stack-sm">
            {(splitDraft.materials ?? []).map((material) => (
              <label className="row-between" key={material.file_id}>
                <span style={{ minWidth: 0, overflowWrap: "anywhere" }}>{material.file_name ?? "资料文件"}</span>
                <select
                  aria-label={`${material.file_name ?? material.file_id} 拆分归属`}
                  className="control"
                  disabled={busy}
                  onChange={(event) => setSplitAssignments((current) => ({ ...current, [material.file_id]: event.target.value as "one" | "two" }))}
                  value={splitAssignments[material.file_id] ?? "one"}
                >
                  <option value="one">题目 1</option>
                  <option value="two">题目 2</option>
                </select>
              </label>
            ))}
          </div>
          <div className="row">
            <Button disabled={busy} onClick={submitSplit} variant="primary">确认拆分</Button>
            <Button disabled={busy} onClick={() => setSplitDraftId(null)} variant="quiet">取消</Button>
          </div>
        </section>
      )}
      {confirmAction && (
        <ConfirmSheet
          busy={busy}
          confirmLabel={confirmAction === "discard" ? "确认舍弃" : "确认合并"}
          description={
            confirmAction === "discard"
              ? `将舍弃已选中的 ${selectedIds.length} 道候选题，之后不会再进入本条会话的题目确认。`
              : `将把已选中的 ${selectedIds.length} 道候选题合并成一道题，并要求重新审阅资料边界和标准答案。`
          }
          onCancel={() => setConfirmAction(null)}
          onConfirm={() => {
            if (confirmAction === "discard") onDiscard();
            else onMerge();
            setConfirmAction(null);
          }}
          title={confirmAction === "discard" ? "确认舍弃候选题" : "确认合并候选题"}
        />
      )}
    </section>
  );
}

function DraftTrack({
  drafts,
  selectedId,
  onSelect,
}: {
  drafts: QuestionDraft[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  return (
    <nav aria-label="题目轨" className={styles.draftTrack} data-testid="authoring-draft-track">
      {drafts.map((draft, index) => {
        const complete = draft.status === "input_answer_confirmed";
        return (
          <button
            aria-current={selectedId === draft.id ? "step" : undefined}
            className={styles.draftTrackItem}
            data-active={selectedId === draft.id}
            key={draft.id}
            onClick={() => onSelect(draft.id)}
            type="button"
          >
            <span className={styles.draftTrackIndex}>{String(index + 1).padStart(2, "0")}</span>
            <span className={styles.draftTrackText}>{draft.title || `候选题 ${index + 1}`}</span>
            <span className="mono faint">{complete ? "已确认" : "待确认"}</span>
          </button>
        );
      })}
    </nav>
  );
}

function DraftReview({
  draft,
  form,
  busy,
  processing,
  canConfirm,
  onChange,
  onSave,
  onConfirm,
}: {
  draft: QuestionDraft | null;
  form: DraftForm | null;
  busy: boolean;
  processing: boolean;
  canConfirm: boolean;
  onChange: (value: DraftForm | null) => void;
  onSave: () => void;
  onConfirm: () => void;
}) {
  if (!draft || !form) {
    return <div className="inset"><p className="secondary">还没有可审阅的题目草稿。</p></div>;
  }
  const set = <K extends keyof DraftForm>(key: K, value: DraftForm[K]) => onChange({ ...form, [key]: value });
  const hasUnconfirmed = form.materials.some((item) => item.role === "unconfirmed");
  return (
    <section className="sheet sheet-pad stack" data-testid="authoring-draft-review">
      <div className="stack-sm">
        <span className="section-label">{processing ? "整理中的题目草稿" : canConfirm ? "审阅题目输入" : "标准答案"}</span>
        <h2 className="doc-title-sm">{draft.title}</h2>
        <p className="secondary">
          {processing ? "本轮 AI 正在整理；你的修改先保留在本地，完成后再保存或确认。" : "先确认任务说明、资料角色和单一标准答案，之后才进入评分规则。"}
        </p>
      </div>
      <Field htmlFor="draft-instruction" label="任务指令">
        <AutoTextarea className="control" disabled={busy} id="draft-instruction" minRows={3} onChange={(event) => set("taskInstruction", event.target.value)} value={form.taskInstruction} />
      </Field>
      {form.materials.length > 0 && (
        <fieldset className={styles.materialFieldset}>
          <legend className="section-label">资料角色与优先级</legend>
          <div className="stack">
            {form.materials.map((material, index) => (
              <div className={styles.materialRow} key={material.fileId}>
                <div className="stack-sm" style={{ minWidth: 0 }}>
                  <strong style={{ overflowWrap: "anywhere" }}>{material.fileName}</strong>
                  <span className="mono faint">优先级 {material.priority}</span>
                </div>
                <div className={styles.materialControls}>
                  <select
                    aria-label={`${material.fileName} 资料角色`}
                    className="control"
                    disabled={busy}
                    onChange={(event) => {
                      const materials = [...form.materials];
                      materials[index] = { ...material, role: event.target.value as MaterialRole };
                      set("materials", materials);
                    }}
                    value={material.role}
                  >
                    {(Object.keys(ROLE_LABEL) as MaterialRole[]).map((role) => <option key={role} value={role}>{ROLE_LABEL[role]}</option>)}
                  </select>
                  <input
                    aria-label={`${material.fileName} 优先级`}
                    className="control"
                    disabled={busy}
                    max={100}
                    min={0}
                    onChange={(event) => {
                      const materials = [...form.materials];
                      materials[index] = { ...material, priority: Number(event.target.value) || 0 };
                      set("materials", materials);
                    }}
                    type="number"
                    value={material.priority}
                  />
                </div>
              </div>
            ))}
          </div>
        </fieldset>
      )}
      <Field hint="每行一项" htmlFor="draft-must" label="必须包含">
        <AutoTextarea className="control" disabled={busy} id="draft-must" minRows={2} onChange={(event) => set("mustInclude", event.target.value)} value={form.mustInclude} />
      </Field>
      <Field hint="每行一项" htmlFor="draft-prohibited" label="禁止内容">
        <AutoTextarea className="control" disabled={busy} id="draft-prohibited" minRows={2} onChange={(event) => set("prohibited", event.target.value)} value={form.prohibited} />
      </Field>
      <Field htmlFor="draft-background" label="必要背景">
        <AutoTextarea className="control" disabled={busy} id="draft-background" minRows={2} onChange={(event) => set("background", event.target.value)} value={form.background} />
      </Field>
      <Field hint="只接受老师终版或明确认可稿" htmlFor="draft-reference" label="单一标准答案">
        <AutoTextarea className="control" disabled={busy} id="draft-reference" minRows={5} onChange={(event) => set("referenceAnswer", event.target.value)} value={form.referenceAnswer} />
      </Field>
      {hasUnconfirmed && <Note tone="amber" title="还有资料没有确认">请为每份资料选择角色；不确定的资料不要直接确认题目。</Note>}
      <div className="row">
        <Button busy={busy} busyLabel="正在保存…" disabled={processing} onClick={onSave} variant="secondary">保存修改</Button>
        <Button busy={busy} busyLabel="正在确认…" disabled={processing || !form.referenceAnswer.trim() || hasUnconfirmed} onClick={onConfirm} size="lg" variant="primary">确认题目输入</Button>
      </div>
    </section>
  );
}
