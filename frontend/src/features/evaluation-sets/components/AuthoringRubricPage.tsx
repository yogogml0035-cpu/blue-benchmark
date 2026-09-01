"use client";

import { useRouter } from "next/navigation";
import { type FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { DeskRail } from "@/src/components/shell/DeskRail";
import { AutoTextarea } from "@/src/components/ui/AutoTextarea";
import { Button, ButtonLink } from "@/src/components/ui/Button";
import { Field } from "@/src/components/ui/Field";
import { Note } from "@/src/components/ui/Note";
import { ConfirmSheet, Sheet, TechnicalDisclosure } from "@/src/components/ui/Sheet";
import { SkeletonLine } from "@/src/components/ui/Skeleton";
import { StatePanel } from "@/src/components/ui/StatePanel";
import { UserChip } from "@/src/features/auth/components/UserChip";
import { useSession } from "@/src/features/auth/hooks/useSession";
import {
  getAuthoringConversation,
  type AuthoringConversation,
} from "@/src/features/case-builder/services/authoringService";
import {
  confirmAndPublishAutomatic,
  getRubricForQuestion,
  listRubricRevisions,
  patchRubric,
  startRubric,
  type RubricContent,
  type RubricCriterion,
  type RubricDraft,
  type RubricRevisionListResponse,
} from "@/src/features/evaluation-sets/services/rubricService";
import { loginHref, toPageFault, type PageFault } from "@/src/lib/api/pageFault";
import {
  PreviewBar,
  useRubricPreviewState,
  type RubricPreviewState,
} from "@/src/lib/preview/preview";

import styles from "./rubric.module.css";

type QuestionDraft = NonNullable<AuthoringConversation["question_drafts"]>[number];
type QuestionChoice = Pick<QuestionDraft, "id" | "title" | "input" | "bad_samples" | "reference_answer_text" | "confirmed_revision" | "lifecycle_status">;

type ConversationLoad =
  | { status: "loading" }
  | { status: "ready"; conversation: AuthoringConversation }
  | { status: "failed"; fault: PageFault };

type RubricLoad =
  | { status: "loading" }
  | { status: "not_started" }
  | { status: "ready"; rubric: RubricDraft }
  | { status: "failed"; fault: PageFault };

type BusyAction = "start" | "save" | "publish" | null;

function isRubricProcessing(status: RubricDraft["status"]): boolean {
  return status === "queued" || status === "processing";
}

function rubricStatusLabel(status: RubricDraft["status"]): string {
  switch (status) {
    case "queued":
      return "等待开始";
    case "not_started":
      return "尚未生成";
    case "processing":
      return "规则处理中";
    case "waiting_for_teacher":
      return "需要补充";
    case "review_ready":
      return "待审阅";
    case "confirmed":
      return "待发布";
    case "published":
      return "已发布";
    case "stale":
      return "规则已过期";
    case "failed":
      return "规则失败";
    case "projection_pending":
      return "等待恢复";
    default:
      return "规则状态未知";
  }
}

function commandId(prefix: string) {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function lines(value: string) {
  return value.split(/\r?\n/).map((item) => item.trim()).filter(Boolean);
}

function previewQuestion(): QuestionChoice {
  return {
    id: "preview-question",
    title: "媒体供稿题",
    input: {
      task_instruction: "根据确认资料形成一份事实准确的新闻稿。",
      materials: [],
      must_include: ["事实来源"],
      prohibited: ["无来源推断"],
      background: "这是开发态规则审阅预演。",
    },
    bad_samples: [],
    reference_answer_text: "老师明确认可的参考结果。",
    confirmed_revision: 1,
    lifecycle_status: "draft",
  };
}

function previewContent(): RubricContent {
  return {
    pass_threshold: 60,
    criteria: [
      {
        id: "fact_accuracy",
        name: "事实准确性",
        purpose: "确保关键事实与确认资料一致。",
        max_score: 60,
        award_points: ["关键事实可以从确认资料中复核。"],
        deduction_points: ["编造或篡改资料未提供的事实。"],
        critical: true,
        critical_mode: "minimum",
        critical_min_score: 36,
        hard_fail_conditions: [],
        reference_expected_score: 58,
        reference_score_reason: "标准答案遵守资料边界。",
        reference_hard_fail_triggered: false,
      },
      {
        id: "deliverable_quality",
        name: "交付可用性",
        purpose: "确保结果满足交付目标并可以直接使用。",
        max_score: 40,
        award_points: ["完整回应任务要求，表达清楚。"],
        deduction_points: ["遗漏必要交付内容。"],
        critical: false,
        critical_mode: "none",
        critical_min_score: null,
        hard_fail_conditions: [],
        reference_expected_score: 40,
        reference_score_reason: "标准答案覆盖了交付目标。",
        reference_hard_fail_triggered: false,
      },
    ],
  };
}

function previewRubric(state: RubricPreviewState): RubricDraft {
  const now = new Date().toISOString();
  const content = previewContent();
  const status = state === "rubric_processing"
    ? "processing"
    : state === "rubric_waiting"
      ? "waiting_for_teacher"
      : state === "rubric_failed"
        ? "failed"
        : state === "rubric_published"
          ? "published"
          : state === "rubric_stale"
            ? "stale"
            : "review_ready";
  return {
    id: "preview-rubric",
    workspace_id: "preview-workspace",
    question_draft_id: "preview-question",
    question_title: "媒体供稿题",
    source_question_revision: 1,
    status,
    revision: 2,
    question_input: previewQuestion().input,
    reference_answer_text: previewQuestion().reference_answer_text ?? "",
    rubric: state === "rubric_processing" || state === "rubric_waiting" || state === "rubric_failed" || state === "rubric_stale"
      ? state === "rubric_failed" ? content : null
      : content,
    reference_total_score: 98,
    reference_critical_passed: state === "rubric_stale" ? null : true,
    reference_passed: state === "rubric_stale" ? null : true,
    pending_question: state === "rubric_waiting"
      ? { id: "preview-rubric-question", text: "这道题还需要补充哪一条老师确认的判定依据？", reason: "规则必须基于本题已确认内容。", gap_type: "input", question_draft_id: "preview-question" }
      : null,
    blocking_issues: state === "rubric_stale" ? ["题目输入或标准答案已经更新，请回到第一阶段重新确认。"] : [],
    next_action: state === "rubric_processing" || state === "rubric_waiting"
      ? "wait_for_processing"
      : state === "rubric_failed"
        ? "retry_processing"
        : state === "rubric_stale"
          ? "stale_upstream"
          : state === "rubric_published"
            ? "none"
            : "confirm_rubric",
    active_operation: state === "rubric_processing"
      ? { kind: "rubric_process", status: "running" }
      : state === "rubric_failed"
        ? { kind: "rubric_process", status: "failed" }
        : null,
    published_revision_id: state === "rubric_published" ? "preview-published-revision" : null,
    confirmed_at: state === "rubric_published" ? now : null,
    created_at: now,
    updated_at: now,
  };
}

function referenceOutcome(content: RubricContent | null) {
  if (!content) return { max: 0, reference: 0, critical: false, passed: false };
  const max = content.criteria.reduce((total, item) => total + item.max_score, 0);
  const reference = content.criteria.reduce((total, item) => total + item.reference_expected_score, 0);
  const critical = content.criteria.every((item) => {
    if (!item.critical) return true;
    if (item.critical_mode === "minimum") return item.critical_min_score != null && item.reference_expected_score >= item.critical_min_score;
    if (item.critical_mode === "hard_fail") return !item.reference_hard_fail_triggered;
    return false;
  });
  return { max, reference, critical, passed: max === 100 && reference >= content.pass_threshold && critical };
}

function CriterionEditor({
  criterion,
  index,
  disabled,
  onChange,
}: {
  criterion: RubricCriterion;
  index: number;
  disabled: boolean;
  onChange: (patch: Partial<RubricCriterion>) => void;
}) {
  return (
    <article className={styles.criterion}>
      <div className={styles.criterionHeader}>
        <div className="stack-sm">
          <span className={styles.criterionNumber}>评分项 {String(index + 1).padStart(2, "0")} · {criterion.id}</span>
          <strong>{criterion.name || "未命名评分项"}</strong>
        </div>
        <span className="mono faint">满分 {criterion.max_score}</span>
      </div>
      <div className={styles.criterionGrid}>
        <Field htmlFor={`criterion-name-${criterion.id}`} label="名称">
          <input className="control" disabled={disabled} id={`criterion-name-${criterion.id}`} onChange={(event) => onChange({ name: event.target.value })} value={criterion.name} />
        </Field>
        <Field htmlFor={`criterion-max-${criterion.id}`} label="满分">
          <input className="control" disabled={disabled} id={`criterion-max-${criterion.id}`} max={100} min={1} onChange={(event) => onChange({ max_score: Number(event.target.value) || 0 })} type="number" value={criterion.max_score} />
        </Field>
      </div>
      <Field htmlFor={`criterion-purpose-${criterion.id}`} label="评分目的">
        <AutoTextarea className="control" disabled={disabled} id={`criterion-purpose-${criterion.id}`} minRows={2} onChange={(event) => onChange({ purpose: event.target.value })} value={criterion.purpose} />
      </Field>
      <div className={styles.criterionGridWide}>
        <div className={styles.arrayField}>
          <Field htmlFor={`criterion-award-${criterion.id}`} label="给分点">
            <AutoTextarea className="control" disabled={disabled} id={`criterion-award-${criterion.id}`} minRows={3} onChange={(event) => onChange({ award_points: lines(event.target.value) })} value={criterion.award_points.join("\n")} />
          </Field>
          <span className={styles.arrayHint}>每行一个可观察的给分点</span>
        </div>
        <div className={styles.arrayField}>
          <Field htmlFor={`criterion-deduction-${criterion.id}`} label="扣分点">
            <AutoTextarea className="control" disabled={disabled} id={`criterion-deduction-${criterion.id}`} minRows={3} onChange={(event) => onChange({ deduction_points: lines(event.target.value) })} value={(criterion.deduction_points ?? []).join("\n")} />
          </Field>
          <span className={styles.arrayHint}>每行一个应扣分的错误</span>
        </div>
      </div>
      <div className={styles.criticalRow} role="group" aria-label={`${criterion.name || "评分项"}关键项设置`}>
        <label className={styles.checkLabel}>
          <input checked={criterion.critical} disabled={disabled} onChange={(event) => onChange({
            critical: event.target.checked,
            critical_mode: event.target.checked ? "minimum" : "none",
            critical_min_score: event.target.checked ? Math.min(criterion.max_score, criterion.reference_expected_score) : null,
            hard_fail_conditions: [],
            reference_hard_fail_triggered: false,
          })} type="checkbox" />
          关键项
        </label>
        {criterion.critical && (
          <>
            <label className="field">
              <span className="field-label">关键项判定</span>
              <select className="control" disabled={disabled} onChange={(event) => onChange({
                critical_mode: event.target.value as RubricCriterion["critical_mode"],
                critical_min_score: event.target.value === "minimum" ? Math.min(criterion.max_score, criterion.reference_expected_score) : null,
                hard_fail_conditions: event.target.value === "hard_fail" ? ((criterion.hard_fail_conditions ?? []).length > 0 ? criterion.hard_fail_conditions : ["命中不可接受条件。"]) : [],
                reference_hard_fail_triggered: false,
              })} value={criterion.critical_mode}>
                <option value="minimum">最低分</option>
                <option value="hard_fail">一票否决</option>
              </select>
            </label>
            {criterion.critical_mode === "minimum" ? (
              <label className="field">
                <span className="field-label">最低分</span>
                <input className="control" disabled={disabled} max={criterion.max_score} min={0} onChange={(event) => onChange({ critical_min_score: Number(event.target.value) || 0 })} type="number" value={criterion.critical_min_score ?? 0} />
              </label>
            ) : (
              <div className={styles.arrayField}>
                <Field htmlFor={`criterion-hard-fail-${criterion.id}`} label="一票否决条件">
                  <AutoTextarea className="control" disabled={disabled} id={`criterion-hard-fail-${criterion.id}`} minRows={2} onChange={(event) => onChange({ hard_fail_conditions: lines(event.target.value) })} value={(criterion.hard_fail_conditions ?? []).join("\n")} />
                </Field>
                <label className={styles.checkLabel}>
                  <input checked={criterion.reference_hard_fail_triggered} disabled={disabled} onChange={(event) => onChange({ reference_hard_fail_triggered: event.target.checked })} type="checkbox" />
                  标准答案命中该条件
                </label>
              </div>
            )}
          </>
        )}
      </div>
      <div className={styles.criterionGrid}>
        <Field htmlFor={`criterion-reference-${criterion.id}`} label="标准答案期望得分">
          <input className="control" disabled={disabled} id={`criterion-reference-${criterion.id}`} max={criterion.max_score} min={0} onChange={(event) => onChange({ reference_expected_score: Number(event.target.value) || 0 })} type="number" value={criterion.reference_expected_score} />
        </Field>
        <div />
      </div>
      <Field htmlFor={`criterion-reference-reason-${criterion.id}`} label="标准答案得分理由">
        <AutoTextarea className="control" disabled={disabled} id={`criterion-reference-reason-${criterion.id}`} minRows={2} onChange={(event) => onChange({ reference_score_reason: event.target.value })} value={criterion.reference_score_reason} />
      </Field>
    </article>
  );
}

function RubricEditor({
  draft,
  busy,
  onSave,
  onPublishRequest,
}: {
  draft: RubricDraft;
  busy: BusyAction;
  onSave: (content: RubricContent) => void;
  onPublishRequest: () => void;
}) {
  const [content, setContent] = useState<RubricContent | null>(draft.rubric ?? null);
  const readOnly = draft.status === "published" || draft.status === "confirmed" || draft.status === "stale";
  const outcome = referenceOutcome(content);
  useEffect(() => {
    setContent(draft.rubric ?? null);
  }, [draft.id, draft.revision, draft.rubric]);

  const updateCriterion = (index: number, patch: Partial<RubricCriterion>) => {
    setContent((current) => current ? {
      ...current,
      criteria: current.criteria.map((criterion, criterionIndex) => criterionIndex === index ? { ...criterion, ...patch } : criterion),
    } : current);
  };

  if (!content) {
    return (
      <section className="sheet sheet-pad stack" aria-busy="true">
        <SkeletonLine height={20} width="40%" />
        <SkeletonLine height={160} />
        <SkeletonLine height={160} />
      </section>
    );
  }

  return (
    <section className="stack-lg" data-testid="rubric-editor">
      <div className={styles.summary} aria-live="polite">
        <div className="row-between">
          <strong>规则校验</strong>
          <span className={outcome.passed ? "state state-green" : "state state-amber"}><span className="dot" />{outcome.passed ? "标准答案可通过" : "还需要调整"}</span>
        </div>
        <div className={styles.summaryValues}>
          <div className={styles.summaryValue}><strong>{outcome.max}</strong><span>评分项满分 / 100</span></div>
          <div className={styles.summaryValue}><strong>{outcome.reference}</strong><span>标准答案期望得分</span></div>
          <div className={styles.summaryValue}><strong>{content.pass_threshold}</strong><span>总分通过线</span></div>
        </div>
        {!outcome.passed && <p className="secondary">发布前必须满足满分合计 100、标准答案达到通过线，并通过全部关键项。</p>}
      </div>
      <div className="sheet sheet-pad stack-lg">
        <div className={styles.editorHead}>
          <div className="stack-sm">
            <span className="section-label">评分规则</span>
            <h2 className="doc-title-sm">逐项审阅，确认这把尺子</h2>
          </div>
          <Field htmlFor="rubric-threshold" hint="0–100 的整数" label="总分通过线">
            <input className="control" disabled={readOnly || busy !== null} id="rubric-threshold" max={100} min={0} onChange={(event) => setContent({ ...content, pass_threshold: Number(event.target.value) || 0 })} type="number" value={content.pass_threshold} />
          </Field>
        </div>
        <div className={styles.criteria}>
          {content.criteria.map((criterion, index) => (
            <CriterionEditor
              criterion={criterion}
              disabled={readOnly || busy !== null}
              index={index}
              key={criterion.id}
              onChange={(patch) => updateCriterion(index, patch)}
            />
          ))}
        </div>
        <div className={styles.actions}>
          {!readOnly && <Button busy={busy === "save"} busyLabel="正在保存…" disabled={busy !== null} onClick={() => onSave(content)} variant="secondary">保存修改</Button>}
          {(draft.status === "review_ready" || draft.status === "confirmed") && <Button busy={busy === "publish"} busyLabel="正在发布…" disabled={busy !== null || !outcome.passed} onClick={onPublishRequest} size="lg" variant="primary">确认规则并发布到评测集</Button>}
        </div>
      </div>
    </section>
  );
}

function RevisionHistory({
  history,
}: {
  history: RubricRevisionListResponse | null;
}) {
  const revisions = history?.revisions ?? [];
  if (revisions.length === 0) return null;
  return (
    <section className="sheet sheet-pad stack">
      <div className="stack-sm">
        <span className="section-label">不可变历史</span>
        <h2 className="doc-title-sm">已发布修订</h2>
      </div>
      <div className={styles.history}>
        {revisions.map((revision) => (
          <div className={styles.historyItem} key={revision.id}>
            <span><strong>题 v{revision.revision}</strong><span className="secondary"> · 通过线 {revision.pass_threshold}</span></span>
            <span className="state state-neutral"><span className="dot" />只读历史</span>
          </div>
        ))}
      </div>
      <TechnicalDisclosure label="查看修订技术详情">
        <div className="stack-sm">
          {revisions.map((revision) => <span className="mono faint" key={revision.id}>题 v{revision.revision} · 内容校验 {revision.content_sha256}</span>)}
        </div>
      </TechnicalDisclosure>
    </section>
  );
}

export function AuthoringRubricPage({
  workspaceId,
  conversationId,
  startedFromConfirmation = false,
}: {
  workspaceId: string;
  conversationId: string;
  startedFromConfirmation?: boolean;
}) {
  const router = useRouter();
  const preview = useRubricPreviewState();
  const session = useSession();
  const reloadSession = session.reload;
  const returnTo = `/workspaces/${workspaceId}/authoring/${conversationId}/rubric`;
  const [conversationLoad, setConversationLoad] = useState<ConversationLoad>({ status: "loading" });
  const [selectedQuestionId, setSelectedQuestionId] = useState<string | null>(null);
  const [rubricLoad, setRubricLoad] = useState<RubricLoad>({ status: "loading" });
  const [history, setHistory] = useState<RubricRevisionListResponse | null>(null);
  const [busy, setBusy] = useState<BusyAction>(null);
  const [fault, setFault] = useState<PageFault | null>(null);
  const [confirmAction, setConfirmAction] = useState<"publish" | null>(null);
  const [awaitingStartedRubric, setAwaitingStartedRubric] = useState(startedFromConfirmation);
  const generation = useRef(0);

  const previewDraft = preview ? previewRubric(preview) : null;
  const previewQuestionChoice = previewQuestion();
  const liveConversation = conversationLoad.status === "ready" ? conversationLoad.conversation : null;
  const questions = useMemo<QuestionChoice[]>(() => liveConversation
    ? (liveConversation.question_drafts ?? [])
      .filter((draft) => draft.status === "input_answer_confirmed" && draft.reference_answer_text && draft.confirmed_revision !== null)
      .map((draft) => ({ id: draft.id, title: draft.title, input: draft.input, bad_samples: draft.bad_samples, reference_answer_text: draft.reference_answer_text, confirmed_revision: draft.confirmed_revision, lifecycle_status: draft.lifecycle_status }))
    : [], [liveConversation]);
  const selectedQuestion = preview ? previewQuestionChoice : questions.find((question) => question.id === selectedQuestionId) ?? questions[0] ?? null;
  const liveRubric = rubricLoad.status === "ready" ? rubricLoad.rubric : null;
  const shownRubric = previewDraft ?? liveRubric;

  useEffect(() => {
    if (preview || session.status !== "authenticated") return;
    let active = true;
    setConversationLoad({ status: "loading" });
    getAuthoringConversation(workspaceId, conversationId)
      .then((result) => { if (active) setConversationLoad({ status: "ready", conversation: result.conversation }); })
      .catch((cause: unknown) => { if (active) setConversationLoad({ status: "failed", fault: toPageFault(cause) }); });
    return () => { active = false; };
  }, [conversationId, preview, session.status, workspaceId]);

  useEffect(() => {
    if (!selectedQuestionId && questions[0]) setSelectedQuestionId(questions[0].id);
    if (selectedQuestionId && !questions.some((question) => question.id === selectedQuestionId)) setSelectedQuestionId(questions[0]?.id ?? null);
  }, [questions, selectedQuestionId]);

  useEffect(() => {
    if (preview || session.status !== "authenticated" || !selectedQuestion) return;
    const currentGeneration = ++generation.current;
    const questionId = selectedQuestion.id;
    let active = true;
    setRubricLoad({ status: "loading" });
    setHistory(null);
    getRubricForQuestion(workspaceId, questionId)
      .then((result) => {
        if (!active || currentGeneration !== generation.current) return;
        if (result.rubric.status === "not_started") {
          setRubricLoad({ status: "not_started" });
          setAwaitingStartedRubric(startedFromConfirmation);
        } else {
          setRubricLoad({ status: "ready", rubric: result.rubric });
          setAwaitingStartedRubric(false);
        }
        void listRubricRevisions(workspaceId, questionId)
          .then((revisions) => {
            if (active && currentGeneration === generation.current) setHistory(revisions);
          })
          .catch(() => undefined);
      })
      .catch((cause: unknown) => {
        if (!active || currentGeneration !== generation.current) return;
        const pageFault = toPageFault(cause);
        setRubricLoad(pageFault.code === "RUBRIC_NOT_STARTED" ? { status: "not_started" } : { status: "failed", fault: pageFault });
      });
    return () => {
      active = false;
      generation.current += 1;
    };
  }, [preview, selectedQuestion, session.status, startedFromConfirmation, workspaceId]);

  useEffect(() => {
    if (
      preview
      || session.status !== "authenticated"
      || !selectedQuestion
      || !awaitingStartedRubric
      || rubricLoad.status !== "not_started"
    ) return;
    const currentGeneration = ++generation.current;
    let active = true;
    let attempts = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const poll = async () => {
      attempts += 1;
      try {
        const result = await getRubricForQuestion(workspaceId, selectedQuestion.id);
        if (!active || currentGeneration !== generation.current) return;
        if (result.rubric.status !== "not_started") {
          setRubricLoad({ status: "ready", rubric: result.rubric });
          setAwaitingStartedRubric(false);
          return;
        }
        if (attempts >= 12) {
          setAwaitingStartedRubric(false);
          return;
        }
        timer = setTimeout(() => void poll(), 500);
      } catch (cause: unknown) {
        if (!active || currentGeneration !== generation.current) return;
        setAwaitingStartedRubric(false);
        setRubricLoad({ status: "failed", fault: toPageFault(cause) });
      }
    };
    timer = setTimeout(() => void poll(), 250);
    return () => {
      active = false;
      generation.current += 1;
      if (timer) clearTimeout(timer);
    };
  }, [awaitingStartedRubric, preview, rubricLoad.status, selectedQuestion, session.status, workspaceId]);

  useEffect(() => {
    if (
      preview
      || session.status !== "authenticated"
      || !selectedQuestion
      || !liveRubric
      || liveRubric.question_draft_id !== selectedQuestion.id
      || !isRubricProcessing(liveRubric.status)
    ) return;
    const currentGeneration = ++generation.current;
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const poll = async () => {
      try {
        const result = await getRubricForQuestion(workspaceId, selectedQuestion.id);
        if (!active || currentGeneration !== generation.current) return;
        if (isRubricProcessing(result.rubric.status)) {
          setRubricLoad({ status: "ready", rubric: result.rubric });
          timer = setTimeout(() => void poll(), 900);
        } else {
          try {
            const revisions = await listRubricRevisions(workspaceId, selectedQuestion.id);
            if (active && currentGeneration === generation.current) setHistory(revisions);
          } catch {
            // The rubric snapshot is still authoritative if the history list
            // is temporarily unavailable.
          }
          if (!active || currentGeneration !== generation.current) return;
          setRubricLoad({ status: "ready", rubric: result.rubric });
        }
      } catch (cause: unknown) {
        if (!active || currentGeneration !== generation.current) return;
        setRubricLoad({ status: "failed", fault: toPageFault(cause) });
      }
    };
    timer = setTimeout(() => void poll(), 500);
    return () => {
      active = false;
      generation.current += 1;
      if (timer) clearTimeout(timer);
    };
  }, [
    liveRubric?.id,
    liveRubric?.question_draft_id,
    liveRubric?.status,
    preview,
    selectedQuestion?.id,
    session.status,
    workspaceId,
  ]);

  useEffect(() => {
    if (!preview && session.status === "anonymous") router.replace(loginHref(returnTo));
  }, [preview, returnTo, router, session.status]);

  const handleError = useCallback((cause: unknown) => {
    const pageFault = toPageFault(cause);
    setFault(pageFault);
    if (pageFault.kind === "unauthorized") reloadSession();
  }, [reloadSession]);

  async function handleStart(event?: FormEvent) {
    event?.preventDefault();
    if (!selectedQuestion || busy || preview) return;
    setBusy("start");
    setFault(null);
    try {
      const result = await startRubric(workspaceId, selectedQuestion.id, {
        command_id: commandId("rubric-start"),
        question_revision: selectedQuestion.confirmed_revision ?? 0,
      });
      setRubricLoad({ status: "ready", rubric: result.rubric });
    } catch (cause: unknown) {
      handleError(cause);
    } finally {
      setBusy(null);
    }
  }

  async function handleSave(content: RubricContent) {
    if (!liveRubric || busy || preview) return;
    setBusy("save");
    setFault(null);
    try {
      const result = await patchRubric(workspaceId, liveRubric.id, { command_id: commandId("rubric-save"), rubric_revision: liveRubric.revision, rubric: content });
      setRubricLoad({ status: "ready", rubric: result.rubric });
    } catch (cause: unknown) {
      handleError(cause);
    } finally {
      setBusy(null);
    }
  }

  async function handlePublish() {
    if (!liveRubric || !selectedQuestion || busy || preview) return;
    setBusy("publish");
    setFault(null);
    try {
      const result = await confirmAndPublishAutomatic(workspaceId, selectedQuestion.id, { command_id: commandId("rubric-publish"), rubric_revision: liveRubric.revision });
      setRubricLoad({ status: "ready", rubric: result.rubric });
      if (selectedQuestion) void listRubricRevisions(workspaceId, selectedQuestion.id).then(setHistory).catch(() => undefined);
      setConfirmAction(null);
    } catch (cause: unknown) {
      handleError(cause);
    } finally {
      setBusy(null);
    }
  }


  const rail = (
    <DeskRail
      crumbs={[{ label: "场景", href: "/workspaces" }, { label: "建题会话", href: `/workspaces/${workspaceId}/authoring/${conversationId}` }, { label: "评分规则" }]}
      right={<UserChip previewName={preview ? "teacher-a" : undefined} session={session} />}
    />
  );
  const previewBar = <PreviewBar states={["rubric_processing", "rubric_waiting", "rubric_review", "rubric_failed", "rubric_published", "rubric_stale"]} />;

  if (!preview && session.status === "loading") {
    return <>{rail}{previewBar}<main className="page page-mid stack-lg"><SkeletonLine height={28} width="42%" /><section aria-busy="true" className="sheet sheet-pad stack-lg"><SkeletonLine height={20} /><SkeletonLine height={180} /></section></main></>;
  }
  if (!preview && session.status === "anonymous") {
    return <>{rail}{previewBar}<main className="page page-mid"><StatePanel actions={<ButtonLink href={loginHref(returnTo)} variant="primary">去登录</ButtonLink>} description="登录后才能审阅打分规则。" title="需要登录" tone="locked" /></main></>;
  }
  if (!preview && session.status === "failed") {
    return <>{rail}{previewBar}<main className="page page-mid"><StatePanel actions={<Button onClick={reloadSession} variant="primary">重新验证登录</Button>} code={session.fault.code} description={session.fault.message} title="登录状态读取失败" tone="fault" /></main></>;
  }
  if (!preview && conversationLoad.status === "failed") {
    return <>{rail}{previewBar}<main className="page page-mid"><StatePanel actions={<Button onClick={() => window.location.reload()} variant="primary">重新读取</Button>} code={conversationLoad.fault.code} description={conversationLoad.fault.message} title="建题会话读取失败" tone="fault" /></main></>;
  }
  if (!preview && (conversationLoad.status === "loading" || !selectedQuestion)) {
    if (conversationLoad.status === "ready" && !selectedQuestion) {
      return <>{rail}{previewBar}<main className="page page-mid"><StatePanel actions={<ButtonLink href={`/workspaces/${workspaceId}/authoring/${conversationId}`} variant="primary">回到建题会话</ButtonLink>} description="请先确认至少一道题的题目输入和标准答案。" title="还没有可生成规则的题目" tone="empty" /></main></>;
    }
    return <>{rail}{previewBar}<main className="page page-mid stack-lg"><SkeletonLine height={28} width="42%" /><section aria-busy="true" className="sheet sheet-pad stack-lg"><SkeletonLine height={20} /><SkeletonLine height={180} /></section></main></>;
  }

  const displayedConversation = liveConversation;
  const title = displayedConversation?.title ?? "媒体供稿题";
  const statusLabel = shownRubric ? rubricStatusLabel(shownRubric.status) : "等待规则";
  const rubricFault = rubricLoad.status === "failed" ? rubricLoad.fault : null;

  return (
    <>
      {rail}
      {previewBar}
      <main className={`${styles.page} page stack-lg`} data-testid="rubric-page">
        <header className={styles.header}>
          <div className="stack-sm">
            <span className="section-label">评分规则</span>
            <h1 className="doc-title">{title}</h1>
            <p className="secondary">基于已确认题目形成一套可复核的 100 分制规则。</p>
          </div>
          {shownRubric && <span className={`state ${shownRubric.status === "published" ? "state-green" : shownRubric.status === "stale" || shownRubric.status === "confirmed" || shownRubric.status === "projection_pending" ? "state-amber" : shownRubric.status === "failed" ? "state-red" : isRubricProcessing(shownRubric.status) ? "state-active" : "state-neutral"}`} data-testid="rubric-status"><span className={`dot${isRubricProcessing(shownRubric.status) ? " pulse-dot" : ""}`} />{statusLabel}</span>}
        </header>
        {fault && <Note code={fault.code} title="操作没有完成" tone="fail">{fault.message}</Note>}
        {rubricFault && <Note code={rubricFault.code} title="规则读取失败" tone="fail">{rubricFault.message}</Note>}
        <div className={styles.workspace}>
          <section className={`${styles.context} stack-lg`} aria-label="已确认题目">
            <div className="stack-sm"><span className="section-label">已确认题目</span><p className="secondary">规则只基于当前题目，不会混入其他题。</p></div>
            <nav aria-label="题目轨" className={styles.track}>
              {(preview ? [previewQuestionChoice] : questions).map((question, index) => (
                <button aria-current={selectedQuestion?.id === question.id ? "step" : undefined} className={styles.trackItem} data-active={selectedQuestion?.id === question.id} key={question.id} onClick={() => setSelectedQuestionId(question.id)} type="button">
                  <span className={styles.trackIndex}>{String(index + 1).padStart(2, "0")}</span><span className={styles.trackText}>{question.title}</span><span className="mono faint">已确认</span>
                </button>
              ))}
            </nav>
            {selectedQuestion && (
              <section className="sheet sheet-pad stack">
                <div className="stack-sm"><span className="section-label">题目输入</span><h2 className="doc-title-sm">{selectedQuestion.title}</h2></div>
                <div className={styles.contextBlock}><span className="section-label">任务指令</span><p className="doc-body">{selectedQuestion.input.task_instruction}</p></div>
                {(selectedQuestion.input.must_include ?? []).length > 0 && <div className={styles.contextBlock}><span className="section-label">必须包含</span><p className={styles.contextText}>{(selectedQuestion.input.must_include ?? []).join("\n")}</p></div>}
                {(selectedQuestion.input.prohibited ?? []).length > 0 && <div className={styles.contextBlock}><span className="section-label">禁止内容</span><p className={styles.contextText}>{(selectedQuestion.input.prohibited ?? []).join("\n")}</p></div>}
                <details><summary className="section-label">查看标准答案</summary><p className={`${styles.contextText} doc-body`} style={{ marginTop: "var(--s-3)" }}>{selectedQuestion.reference_answer_text}</p></details>
                {(selectedQuestion.bad_samples ?? []).length > 0 && <details><summary className="section-label">查看老师确认的坏样本（{selectedQuestion.bad_samples?.length}）</summary><div className="stack" style={{ marginTop: "var(--s-3)" }}>{selectedQuestion.bad_samples?.map((sample) => <div className="inset stack-sm" key={sample.id}><span className="section-label">否定原因</span><p className={styles.contextText}>{sample.reason_summary}</p><span className="section-label">老师原话</span><p className={styles.contextText}>{sample.teacher_feedback_texts.join("\n")}</p></div>)}</div></details>}
              </section>
            )}
          </section>
          <section className={`${styles.editor} stack-lg`} aria-label="规则审阅">
            <span className="section-label">下一步</span>
            {previewDraft ? (
              previewDraft.status === "stale" ? (
                <section className="sheet sheet-pad stack"><h2 className="doc-title-sm">题目已经更新</h2><p className="secondary">这套规则不再代表最新题目，请回到第一阶段重新确认上游内容。</p></section>
              ) : previewDraft.status === "processing" ? (
                <div className={styles.summary}><span className="state state-active"><span className="dot pulse-dot" />AI 正在整理规则，完成后会回到这里。</span></div>
              ) : previewDraft.status === "waiting_for_teacher" ? (
                <section className="sheet sheet-pad stack"><span className="state state-amber"><span className="dot" />需要补充</span><h2 className="doc-title-sm">{previewDraft.pending_question?.text}</h2><p className="secondary">{previewDraft.pending_question?.reason}</p></section>
              ) : previewDraft.status === "failed" ? (
                <><Note tone="fail" title="规则整理失败">已确认的题目内容仍然保留，可以重试。</Note><RubricEditor draft={previewDraft} busy={null} onPublishRequest={() => undefined} onSave={() => undefined} /></>
              ) : (
                <RubricEditor draft={previewDraft} busy={null} onPublishRequest={() => undefined} onSave={() => undefined} />
              )
            ) : rubricLoad.status === "loading" ? (
              <section aria-busy="true" className="sheet sheet-pad stack-lg"><SkeletonLine height={20} width="35%" /><SkeletonLine height={100} /><SkeletonLine height={180} /></section>
            ) : rubricLoad.status === "not_started" && awaitingStartedRubric ? (
              <section aria-busy="true" className="sheet sheet-pad stack"><span className="section-label">已提交启动命令</span><h2 className="doc-title-sm">正在确认规则任务</h2><p className="secondary">规则任务已经提交，正在等待服务端快照出现；页面不会重复启动。</p></section>
            ) : rubricLoad.status === "not_started" ? (
              <form className="sheet sheet-pad stack" onSubmit={(event) => void handleStart(event)}><div className="stack-sm"><span className="section-label">还没有规则草稿</span><h2 className="doc-title-sm">先让 AI 提出一版规则</h2><p className="secondary">它只读取这道已确认题的输入、标准答案和资料边界，最终由你逐项确认。</p></div><Button busy={busy === "start"} busyLabel="正在生成…" size="lg" type="submit" variant="primary">生成打分规则</Button></form>
            ) : rubricLoad.status === "failed" ? (
              rubricFault?.code === "QUESTION_NOT_CONFIRMED" ? (
                <section className="sheet sheet-pad stack"><h2 className="doc-title-sm">题目需要重新确认</h2><p className="secondary">上游题目已经变化，旧规则不能继续使用。</p><ButtonLink href={`/workspaces/${workspaceId}/authoring/${conversationId}`} variant="primary">回到建题会话</ButtonLink></section>
              ) : (
                <section className="sheet sheet-pad stack"><h2 className="doc-title-sm">规则暂时无法读取</h2><p className="secondary">可以从当前已确认题目重新开始生成。</p><Button busy={busy === "start"} busyLabel="正在重试…" onClick={() => void handleStart()} variant="primary">重新生成规则</Button></section>
              )
            ) : liveRubric?.status === "stale" ? (
              <section className="sheet sheet-pad stack"><h2 className="doc-title-sm">题目已经更新</h2><p className="secondary">当前规则不再代表最新题目；请回到建题会话重新确认上游内容。</p><ButtonLink href={`/workspaces/${workspaceId}/authoring/${conversationId}`} variant="primary">回到建题会话</ButtonLink></section>
            ) : liveRubric ? (
              <>
                {isRubricProcessing(liveRubric.status) ? <div className={styles.summary}><span className="state state-active"><span className="dot pulse-dot" />AI 正在整理规则，完成后会回到这里。</span></div> : null}
                {liveRubric.status === "projection_pending" && <section className="sheet sheet-pad stack"><span className="state state-amber"><span className="dot" />等待恢复</span><h2 className="doc-title-sm">规则已经生成，正在恢复业务快照</h2><p className="secondary">不会重新调用 AI；恢复动作只会提交已保存的规则结果。</p><Button busy={busy === "start"} busyLabel="正在恢复…" onClick={() => void handleStart()} variant="primary">恢复规则快照</Button></section>}
                {liveRubric.status === "failed" && <section className="sheet sheet-pad stack"><Note tone="fail" title="规则整理失败">已确认的题目内容不会丢失，可以重新生成。</Note><Button busy={busy === "start"} busyLabel="正在重试…" onClick={() => void handleStart()} variant="primary">重新生成规则</Button></section>}
                {liveRubric.status === "waiting_for_teacher" && liveRubric.pending_question && <section className="sheet sheet-pad stack"><span className="state state-amber"><span className="dot" />需要补充</span><h2 className="doc-title-sm">{liveRubric.pending_question.text}</h2><p className="secondary">{liveRubric.pending_question.reason}</p></section>}
                {liveRubric.rubric && <RubricEditor draft={liveRubric} busy={busy} onPublishRequest={() => setConfirmAction("publish")} onSave={(content) => void handleSave(content)} />}
                {liveRubric.status === "published" && <section className={`${styles.nextStep} sheet sheet-pad stack`} data-testid="rubric-published-next-step"><span className="section-label">已完成</span><h2 className="doc-title-sm">已进入当前评测集</h2><p className="secondary">这道题已经进入当前正式评测集，并自动留下不可变历史版本。修改时会先形成下一修订。</p><div className="row"><ButtonLink href={`/workspaces/${workspaceId}?section=questions`} variant="primary">查看题目</ButtonLink><ButtonLink href={`/workspaces/${workspaceId}/question-revisions/${liveRubric.published_revision_id}/submissions/new`} variant="quiet">提交待评答卷</ButtonLink></div></section>}
                <RevisionHistory history={history} />
              </>
            ) : null}
          </section>
        </div>
        {confirmAction && (
          <ConfirmSheet
            busy={busy === confirmAction}
            confirmLabel="确认规则并发布"
            description="发布后立即进入当前评测集，并留下不可变历史版本；以后修改会形成下一修订，不会覆盖当前题。"
            onCancel={() => setConfirmAction(null)}
            onConfirm={() => void handlePublish()}
            title="确认规则并发布到评测集"
          />
        )}
      </main>
    </>
  );
}
