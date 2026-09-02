"use client";

import { useRouter } from "next/navigation";
import { type FormEvent, useCallback, useEffect, useRef, useState } from "react";

import { PageShell } from "@/src/components/shell/PageShell";
import { AutoTextarea } from "@/src/components/ui/AutoTextarea";
import { Button, ButtonLink } from "@/src/components/ui/Button";
import { Field } from "@/src/components/ui/Field";
import { Note } from "@/src/components/ui/Note";
import { SkeletonLine } from "@/src/components/ui/Skeleton";
import { StatePanel } from "@/src/components/ui/StatePanel";
import { UserChip } from "@/src/features/auth/components/UserChip";
import { useSession } from "@/src/features/auth/hooks/useSession";
import {
  createPastedSubmission,
  createUploadedSubmission,
  getSubmission,
  submitScore,
  type HumanScore,
  type HumanSubmissionResponse,
  type QuestionRevision,
} from "@/src/features/human-scoring/services/humanScoringService";
import { previewSubmission } from "@/src/features/human-scoring/preview/fixtures";
import { loginHref, toPageFault, type PageFault } from "@/src/lib/api/pageFault";
import {
  HUMAN_SCORING_PREVIEW_STATES,
  PREVIEW_STATES,
  useHumanScoringPreviewState,
  type HumanScoringPreviewState,
} from "@/src/lib/preview/preview";

import styles from "./humanScoring.module.css";

type Criterion = QuestionRevision["criteria"][number];
type EntryMode = "paste" | "file";

type ScoreDraft = Record<
  string,
  {
    score: string;
    reason: string;
    hardFailTriggered: boolean | null;
  }
>;

type Load =
  | { status: "loading" }
  | { status: "ready"; snapshot: HumanSubmissionResponse }
  | { status: "failed"; fault: PageFault };

function commandId(prefix: string) {
  const suffix = typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  return `${prefix}-${suffix}`;
}

function isHumanPreviewState(value: string | null): value is HumanScoringPreviewState {
  return HUMAN_SCORING_PREVIEW_STATES.includes(value as HumanScoringPreviewState);
}

const HUMAN_PREVIEW_BAR_STATES = [...PREVIEW_STATES, ...HUMAN_SCORING_PREVIEW_STATES] as const;

function scoringCrumbs(title: string) {
  return [{ label: "场景", href: "/workspaces" }, { label: "人工评分" }, { label: title }];
}

function scoringRailRight(
  session: ReturnType<typeof useSession>,
  preview: string | null,
) {
  return <UserChip previewName={preview ? "teacher-a" : undefined} session={session} />;
}

function FaultPanel({
  fault,
  returnTo,
  title = "页面暂时无法读取",
}: {
  fault: PageFault;
  returnTo: string;
  title?: string;
}) {
  if (fault.kind === "unauthorized") {
    return (
      <StatePanel
        actions={<ButtonLink href={loginHref(returnTo)} variant="primary">去登录</ButtonLink>}
        description="登录后才能提交或查看人工评分。"
        title="需要登录"
        tone="locked"
      />
    );
  }
  if (fault.kind === "forbidden") {
    return (
      <StatePanel
        actions={<ButtonLink href="/workspaces" variant="primary">回到场景</ButtonLink>}
        description="这份内容不在当前场景的访问范围内。"
        title="无法访问"
        tone="locked"
      />
    );
  }
  if (fault.kind === "not_found") {
    return (
      <StatePanel
        actions={<ButtonLink href="/workspaces" variant="primary">回到场景</ButtonLink>}
        description="请检查链接，或从已发布题目重新进入。"
        title="内容不存在"
        tone="empty"
      />
    );
  }
  return (
    <StatePanel
      actions={<Button onClick={() => window.location.reload()} variant="primary">重新读取</Button>}
      description={fault.message}
      title={title}
      tone="fault"
    />
  );
}

function EntrySkeleton() {
  return (
    <main className={`${styles.entryPage} page stack-lg`} aria-busy="true">
      <SkeletonLine height={28} width="48%" />
      <section className="sheet sheet-pad stack-lg">
        <SkeletonLine height={40} />
        <SkeletonLine height={220} />
        <SkeletonLine height={44} width="34%" />
      </section>
    </main>
  );
}

export function SubmissionEntryPage({
  workspaceId,
  questionRevisionId,
}: {
  workspaceId: string;
  questionRevisionId: string;
}) {
  const router = useRouter();
  const preview = useHumanScoringPreviewState();
  const session = useSession({ skip: Boolean(preview) });
  const returnTo = `/workspaces/${workspaceId}/question-revisions/${questionRevisionId}/submissions/new`;
  const [mode, setMode] = useState<EntryMode>("paste");
  const [content, setContent] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [fault, setFault] = useState<PageFault | null>(null);
  const commandIdRef = useRef<string | null>(null);

  const handleError = useCallback((cause: unknown) => {
    const next = toPageFault(cause);
    setFault(next);
    if (next.kind === "unauthorized") session.reload();
  }, [session]);

  useEffect(() => {
    if (!preview && session.status === "anonymous") router.replace(loginHref(returnTo));
  }, [preview, returnTo, router, session.status]);

  function getCommandId() {
    if (!commandIdRef.current) commandIdRef.current = commandId("submission");
    return commandIdRef.current;
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy || preview) return;
    setFault(null);
    if (mode === "paste" && !content.trim()) {
      setFault({ kind: "failed", code: "EMPTY_SUBMISSION", message: "请先粘贴一份待评答卷。" });
      return;
    }
    if (mode === "file" && !file) {
      setFault({ kind: "failed", code: "FILE_REQUIRED", message: "请选择一个 Markdown 或 TXT 文件。" });
      return;
    }
    setBusy(true);
    try {
      const result = mode === "paste"
        ? await createPastedSubmission(workspaceId, questionRevisionId, {
          command_id: getCommandId(),
          content_text: content,
        })
        : await createUploadedSubmission(workspaceId, questionRevisionId, getCommandId(), file as File);
      router.push(`/workspaces/${workspaceId}/submissions/${result.submission.id}`);
    } catch (cause) {
      handleError(cause);
    } finally {
      setBusy(false);
    }
  }

  const railRight = scoringRailRight(session, preview);
  const crumbs = scoringCrumbs("提交答卷");
  if (preview === "loading" || (!preview && session.status === "loading")) return <PageShell chromeOnly crumbs={crumbs} previewStates={HUMAN_PREVIEW_BAR_STATES} right={railRight}><EntrySkeleton /></PageShell>;
  if (!preview && session.status === "anonymous") return <PageShell crumbs={crumbs} mainClassName="page-mid" previewStates={HUMAN_PREVIEW_BAR_STATES} right={railRight}><FaultPanel fault={session.fault} returnTo={returnTo} /></PageShell>;
  if (!preview && session.status === "failed") return <PageShell crumbs={crumbs} mainClassName="page-mid" previewStates={HUMAN_PREVIEW_BAR_STATES} right={railRight}><FaultPanel fault={session.fault} returnTo={returnTo} title="登录状态读取失败" /></PageShell>;
  if (preview === "empty" || preview === "unauthorized" || preview === "forbidden" || preview === "not_found" || preview === "error" || preview === "human_invalid") {
    const previewFault: PageFault = preview === "unauthorized"
      ? { kind: "unauthorized", code: "AUTH_REQUIRED", message: "请先登录。" }
      : preview === "forbidden"
        ? { kind: "forbidden", code: "FORBIDDEN", message: "这份题目修订不属于当前场景。" }
        : preview === "not_found"
          ? { kind: "not_found", code: "RESOURCE_NOT_FOUND", message: "题目修订不存在。" }
          : preview === "empty"
            ? { kind: "failed", code: "NO_PUBLISHED_REVISION", message: "当前场景还没有可用于评分的已发布题目修订。" }
            : { kind: "failed", code: "INVALID_SUBMISSION", message: "这份待评答卷暂时不能提交，请检查内容后重试。" };
    return <PageShell crumbs={crumbs} mainClassName="page-mid" previewStates={HUMAN_PREVIEW_BAR_STATES} right={railRight}><FaultPanel fault={previewFault} returnTo={returnTo} title="提交入口暂时不可用" /></PageShell>;
  }

  return (
    <PageShell crumbs={crumbs} mainClassName={`${styles.entryPage} stack-lg`} previewStates={HUMAN_PREVIEW_BAR_STATES} right={railRight}>
      <div data-testid="submission-entry" className="stack-lg">
        <header className="stack-sm">
          <span className="section-label">待评答卷</span>
          <h1 className="doc-title">提交一份答卷</h1>
          <p className="secondary">这份内容只绑定当前已发布题目修订，提交后由老师依据同一套规则独立评分。</p>
        </header>
        <form className="sheet sheet-pad stack-lg" onSubmit={(event) => void submit(event)}>
          <div className={styles.entryModes} role="group" aria-label="答卷提交方式">
            <button
              aria-pressed={mode === "paste"}
              className={styles.entryMode}
              data-active={mode === "paste"}
              onClick={() => setMode("paste")}
              type="button"
            >
              粘贴文本
            </button>
            <button
              aria-pressed={mode === "file"}
              className={styles.entryMode}
              data-active={mode === "file"}
              onClick={() => setMode("file")}
              type="button"
            >
              上传文件
            </button>
          </div>
          {mode === "paste" ? (
            <Field htmlFor="submission-content" hint="最大 1 MiB" label="待评文本">
              <AutoTextarea
                aria-describedby="submission-content-hint"
                id="submission-content"
                minRows={12}
                onChange={(event) => {
                  setContent(event.target.value);
                  commandIdRef.current = null;
                }}
                placeholder="把平台外生成的主文本粘贴到这里…"
                value={content}
              />
            </Field>
          ) : (
            <Field htmlFor="submission-file" hint="仅 .md / .txt，UTF-8" label="答卷文件">
              <input
                accept=".md,.txt,text/markdown,text/plain"
                className={styles.fileInput}
                id="submission-file"
                onChange={(event) => {
                  setFile(event.target.files?.[0] ?? null);
                  commandIdRef.current = null;
                }}
                type="file"
              />
              <span className={styles.entryHint}>{file ? `已选择：${file.name}` : "请选择一个单独的 Markdown 或 TXT 文件。"}</span>
            </Field>
          )}
          <p className={styles.entryHint} id="submission-content-hint">提交后答卷会保留原文和校验摘要，不能在平台内修改。</p>
          {fault && <Note title="提交没有完成" tone="fail">{fault.message}</Note>}
          <div className="row">
            <Button busy={busy} busyLabel="正在保存…" className={styles.submit} size="lg" type="submit" variant="primary">
              保存并开始评分
            </Button>
            <ButtonLink href={`/workspaces/${workspaceId}?section=versions`} variant="quiet">返回版本</ButtonLink>
          </div>
        </form>
      </div>
    </PageShell>
  );
}

function initialDraft(revision: QuestionRevision, score?: HumanScore): ScoreDraft {
  const items = new Map((score?.items ?? []).map((item) => [item.criterion_id, item]));
  return Object.fromEntries(
    revision.criteria.map((criterion) => {
      const item = items.get(criterion.id);
      return [criterion.id, {
        score: item ? String(item.score) : "",
        reason: item?.reason ?? "",
        hardFailTriggered: item?.hard_fail_triggered ?? null,
      }];
    }),
  );
}

function revisionMap(snapshot: HumanSubmissionResponse): Record<string, QuestionRevision> {
  return {
    ...(snapshot.question_revisions ?? {}),
    [snapshot.question_revision.id]: snapshot.question_revision,
  };
}

function revisionFor(
  snapshot: HumanSubmissionResponse,
  revisionId: string | null | undefined,
): QuestionRevision {
  const revisions = revisionMap(snapshot);
  return (revisionId && revisions[revisionId]) || snapshot.question_revision;
}

function revisionOptions(snapshot: HumanSubmissionResponse) {
  return Object.values(revisionMap(snapshot)).sort((left, right) => right.revision_number - left.revision_number);
}

function latestScore(scores: HumanScore[]) {
  return scores.length > 0 ? scores[scores.length - 1] : null;
}

function formatScoreDate(value: string) {
  return new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

function ScoreHistory({
  scores,
  revisions,
}: {
  scores: HumanScore[];
  revisions: Record<string, QuestionRevision>;
}) {
  if (scores.length === 0) return null;
  return (
    <section className={`sheet sheet-pad ${styles.historySheet}`} aria-label="评分历史" data-testid="score-history">
      <div className="row-between">
        <div className="stack-sm">
          <span className="section-label">不可变记录</span>
          <h2 className="doc-title-sm">评分历史</h2>
        </div>
        <span className="mono faint">{scores.length} 次</span>
      </div>
      <div className={styles.history}>
        {scores.map((score, index) => {
          const scoreRevision = revisions[score.question_revision_id];
          const parentIndex = score.parent_score_id
            ? scores.findIndex((candidate) => candidate.id === score.parent_score_id)
            : -1;
          return (
          <article className={styles.historyItem} key={score.id}>
            <div className={styles.historyMeta}>
              <span>第 {index + 1} 次{score.parent_score_id ? (parentIndex >= 0 ? ` · 基于第 ${parentIndex + 1} 次评分` : " · 重评") : " · 首次评分"}</span>
              <span>题 v{scoreRevision?.revision_number ?? "—"}</span>
              <span>{formatScoreDate(score.submitted_at)}</span>
            </div>
            <div className="row-between">
              <span className={styles.historyScore}>{score.total_score} / 100</span>
              <span className={score.passed ? "state state-green" : "state state-amber"}>
                <span className="dot" />{score.passed ? "通过" : "未通过"}
              </span>
            </div>
            {score.overall_reason && <p className={styles.historyReason}>{score.overall_reason}</p>}
            <details>
              <summary className="section-label">查看逐项记录</summary>
              <div className="stack-sm" style={{ marginTop: "var(--s-3)" }}>
                {score.items.map((item) => {
                  const criterion = scoreRevision?.criteria.find((candidate) => candidate.id === item.criterion_id);
                  const criterionIndex = scoreRevision?.criteria.findIndex((candidate) => candidate.id === item.criterion_id) ?? -1;
                  return (
                    <div className="row-between" key={item.criterion_id}>
                      <span className="secondary">{criterion?.name ?? `评分项 ${criterionIndex + 1}`}{criterion?.critical ? " · 关键项" : ""}</span>
                      <span className="mono">{item.score} / {criterion?.max_score ?? "—"}</span>
                      {criterion?.critical && <span className={item.critical_passed ? "state state-green" : "state state-red"}><span className="dot" />{item.critical_passed ? "关键项通过" : "关键项未通过"}</span>}
                      {item.hard_fail_triggered !== null && item.hard_fail_triggered !== undefined && (
                        <span className={item.hard_fail_triggered ? "state state-red" : "state state-green"}>
                          <span className="dot" />{item.hard_fail_triggered ? "一票否决已命中" : "一票否决未命中"}
                        </span>
                      )}
                      {item.reason && <span className="secondary" style={{ flex: 1, minWidth: 0, overflowWrap: "anywhere" }}>{item.reason}</span>}
                    </div>
                  );
                })}
              </div>
            </details>
          </article>
          );
        })}
      </div>
    </section>
  );
}

function RevisionPicker({
  revisions,
  value,
  disabled,
  onChange,
}: {
  revisions: QuestionRevision[];
  value: string;
  disabled: boolean;
  onChange: (revisionId: string) => void;
}) {
  if (revisions.length <= 1) {
    return <p className={styles.revisionHint}>当前只有题 v{revisions[0]?.revision_number ?? "—"} 可供重评。</p>;
  }
  return (
    <Field htmlFor="rescore-revision" hint="切换版本会清空不兼容的评分草稿" label="按哪一版标准重评">
      <select
        className="control"
        disabled={disabled}
        id="rescore-revision"
        onChange={(event) => onChange(event.target.value)}
        value={value}
      >
        {revisions.map((revision) => (
          <option key={revision.id} value={revision.id}>
            题 v{revision.revision_number} · {revision.title}
          </option>
        ))}
      </select>
    </Field>
  );
}

function StandardColumn({ revision }: { revision: QuestionRevision }) {
  const { question_input: input } = revision;
  return (
    <div className="stack-lg">
      <section className={`sheet sheet-pad ${styles.standardSheet}`} aria-label="题目标准">
        <div className={styles.standardSection}>
          <span className="section-label">题目输入 · 题 v{revision.revision_number}</span>
          <h2 className="doc-title-sm">{revision.title}</h2>
          <p className={`${styles.standardText} doc-body`}>{input.task_instruction}</p>
        </div>
        {(input.must_include ?? []).length > 0 && (
          <div className={styles.standardSection}>
            <span className="section-label">必须包含</span>
            <ul className={styles.listText}>{(input.must_include ?? []).map((item) => <li key={item}>{item}</li>)}</ul>
          </div>
        )}
        {(input.prohibited ?? []).length > 0 && (
          <div className={styles.standardSection}>
            <span className="section-label">禁止内容</span>
            <ul className={styles.listText}>{(input.prohibited ?? []).map((item) => <li key={item}>{item}</li>)}</ul>
          </div>
        )}
        {input.background && (
          <div className={styles.standardSection}>
            <span className="section-label">补充背景</span>
            <p className={styles.standardText}>{input.background}</p>
          </div>
        )}
        <div className={styles.standardSection}>
          <span className="section-label">标准答案</span>
          <p className={`${styles.standardText} doc-body`}>{revision.reference_answer_text}</p>
        </div>
      </section>
    </div>
  );
}

function CriterionCard({
  criterion,
  draft,
  error,
  disabled,
  onChange,
}: {
  criterion: Criterion;
  draft: ScoreDraft[string];
  error?: string;
  disabled: boolean;
  onChange: (patch: Partial<ScoreDraft[string]>) => void;
}) {
  const scoreValue = Number.parseInt(draft.score, 10);
  const scoreKnown = /^\d+$/.test(draft.score);
  const minimumFailed = scoreKnown && criterion.critical_mode === "minimum"
    && (criterion.critical_min_score == null || scoreValue < criterion.critical_min_score);
  const reasonRequired = (scoreKnown && scoreValue < criterion.reference_expected_score) || minimumFailed || draft.hardFailTriggered === true;
  const scoreId = `score-${criterion.id}`;
  const reasonId = `reason-${criterion.id}`;
  const errorId = `error-${criterion.id}`;
  return (
    <article className={styles.criterion} data-testid={`criterion-${criterion.id}`}>
      <div className={styles.criterionHeader}>
        <div className={styles.criterionTitle}>
          <span className={styles.criterionLabel}>评分项</span>
          <strong>{criterion.name}</strong>
        </div>
        <span className={styles.maxScore}>满分 {criterion.max_score}</span>
      </div>
      <p className={styles.criterionPurpose}>{criterion.purpose}</p>
      <div className={styles.anchor}>
        <div className={styles.anchorScore}>
          <span>标准答案期望得分</span>
          <strong>{criterion.reference_expected_score} / {criterion.max_score}</strong>
        </div>
        <p className={styles.criterionPurpose}>{criterion.reference_score_reason}</p>
      </div>
      <div className={styles.pointGroup}>
        <div><strong>给分点</strong><ul className={styles.pointList}>{criterion.award_points.map((point) => <li key={point}>{point}</li>)}</ul></div>
        {(criterion.deduction_points ?? []).length > 0 && <div><strong>扣分点</strong><ul className={styles.pointList}>{criterion.deduction_points?.map((point) => <li key={point}>{point}</li>)}</ul></div>}
      </div>
      {criterion.critical && criterion.critical_mode === "minimum" && (
        <Note tone="amber" title="关键项 · 最低分">本项至少 {criterion.critical_min_score} 分，否则整体不能通过。</Note>
      )}
      {criterion.critical && criterion.critical_mode === "hard_fail" && (
        <fieldset className={styles.criticalFieldset} aria-describedby={error ? errorId : undefined}>
          <legend className={styles.criticalLegend}>关键项 · 一票否决</legend>
          <div className={styles.pointGroup}><strong>命中条件</strong><ul className={styles.pointList}>{criterion.hard_fail_conditions?.map((condition) => <li key={condition}>{condition}</li>)}</ul></div>
          <div className={styles.radioOptions}>
            <label className={styles.radioOption}>
              <input checked={draft.hardFailTriggered === false} disabled={disabled} name={`hard-fail-${criterion.id}`} onChange={() => onChange({ hardFailTriggered: false })} type="radio" />
              未命中
            </label>
            <label className={styles.radioOption}>
              <input checked={draft.hardFailTriggered === true} disabled={disabled} name={`hard-fail-${criterion.id}`} onChange={() => onChange({ hardFailTriggered: true })} type="radio" />
              命中
            </label>
          </div>
        </fieldset>
      )}
      <div className={styles.scoreRow}>
        <label className="field-label" htmlFor={scoreId}>待评得分</label>
        <input
          aria-describedby={error ? errorId : undefined}
          aria-invalid={Boolean(error)}
          className={`control ${styles.scoreInput}${error ? " control-invalid" : ""}`}
          disabled={disabled}
          id={scoreId}
          inputMode="numeric"
          max={criterion.max_score}
          min={0}
          onChange={(event) => onChange({ score: event.target.value })}
          type="number"
          value={draft.score}
        />
      </div>
      <Field htmlFor={reasonId} hint={reasonRequired ? "必填" : "可选"} label={reasonRequired ? "评分理由" : "评分理由（可选）"}>
        <AutoTextarea
          aria-describedby={error ? errorId : undefined}
          aria-invalid={Boolean(error)}
          aria-required={reasonRequired}
          className={error ? "control-invalid" : undefined}
          disabled={disabled}
          id={reasonId}
          minRows={3}
          onChange={(event) => onChange({ reason: event.target.value })}
          placeholder={reasonRequired ? "请说明低于标准或关键项失败的依据…" : "可以补充你的判断依据…"}
          value={draft.reason}
        />
      </Field>
      {error && <p className={styles.fieldError} id={errorId} role="alert">{error}</p>}
    </article>
  );
}

function ResultSummary({ score, passThreshold }: { score: HumanScore; passThreshold: number }) {
  return (
    <section className={styles.result} data-passed={score.passed} data-testid="score-result" aria-live="polite">
      <div className="stack-sm">
        <span className="section-label">本次结果</span>
        <h2 className="doc-title-sm" tabIndex={-1}>评分已保存</h2>
      </div>
      <div className={styles.resultScore}>
        <strong>{score.total_score} / 100</strong>
        <span>{score.passed ? "达到通过线" : "未达到通过线"} · 通过线 {passThreshold}</span>
      </div>
      <div className="row-between">
        <span className={score.critical_passed ? "state state-green" : "state state-red"}><span className="dot" />{score.critical_passed ? "关键项全部通过" : "存在关键项失败"}</span>
        <span className={score.passed ? "state state-green" : "state state-amber"}><span className="dot" />{score.passed ? "通过" : "未通过"}</span>
      </div>
      {score.overall_reason && <p className={styles.historyReason}>{score.overall_reason}</p>}
    </section>
  );
}

export function HumanScoringPage({
  workspaceId,
  submissionId,
}: {
  workspaceId: string;
  submissionId: string;
}) {
  const router = useRouter();
  const preview = useHumanScoringPreviewState();
  const session = useSession({ skip: Boolean(preview) });
  const returnTo = `/workspaces/${workspaceId}/submissions/${submissionId}`;
  const [load, setLoad] = useState<Load>({ status: "loading" });
  const [draft, setDraft] = useState<ScoreDraft>({});
  const [overallReason, setOverallReason] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [rescoreMode, setRescoreMode] = useState(false);
  const [parentScoreId, setParentScoreId] = useState<string | null>(null);
  const [selectedRevisionId, setSelectedRevisionId] = useState<string | null>(null);
  const [fault, setFault] = useState<PageFault | null>(null);
  const scoreCommandRef = useRef<string | null>(null);
  const resultTitleRef = useRef<HTMLDivElement>(null);

  const snapshot = load.status === "ready" ? load.snapshot : null;
  const latest = snapshot ? latestScore(snapshot.scores ?? []) : null;
  const isPreviewPage = isHumanPreviewState(preview);

  useEffect(() => {
    if (!preview && session.status === "anonymous") router.replace(loginHref(returnTo));
  }, [preview, returnTo, router, session.status]);

  useEffect(() => {
    if (preview === "loading") {
      setLoad({ status: "loading" });
      return;
    }
    if (preview === "error" || preview === "unauthorized" || preview === "forbidden" || preview === "not_found" || preview === "human_invalid") {
      return;
    }
    const previewSnapshotState = preview === "success" ? "human_draft" : preview;
    if ((isPreviewPage || preview === "success") && previewSnapshotState && ["human_draft", "human_submitted", "human_rescore", "human_history"].includes(previewSnapshotState)) {
      const next = previewSubmission(previewSnapshotState as "human_draft" | "human_submitted" | "human_rescore" | "human_history");
      setLoad({ status: "ready", snapshot: next });
      const nextLatest = latestScore(next.scores ?? []);
      const nextRevisionId = nextLatest?.question_revision_id ?? next.question_revision.id;
      setSelectedRevisionId(nextRevisionId);
      setDraft(initialDraft(revisionFor(next, nextRevisionId), nextLatest ?? undefined));
      setOverallReason(nextLatest?.overall_reason ?? "");
      setErrors({});
      setRescoreMode(previewSnapshotState === "human_rescore");
      setParentScoreId(previewSnapshotState === "human_rescore" ? nextLatest?.id ?? null : null);
      return;
    }
    if (session.status !== "authenticated") return;
    let active = true;
    setLoad({ status: "loading" });
    setFault(null);
    getSubmission(workspaceId, submissionId)
      .then((result) => {
        if (!active) return;
        setLoad({ status: "ready", snapshot: result });
        const nextLatest = latestScore(result.scores ?? []);
        const nextRevisionId = nextLatest?.question_revision_id ?? result.question_revision.id;
        setSelectedRevisionId(nextRevisionId);
        setDraft(initialDraft(revisionFor(result, nextRevisionId), nextLatest ?? undefined));
        setOverallReason(nextLatest?.overall_reason ?? "");
        setErrors({});
        setRescoreMode(false);
        setParentScoreId(null);
        scoreCommandRef.current = null;
      })
      .catch((cause: unknown) => {
        if (active) setLoad({ status: "failed", fault: toPageFault(cause) });
      });
    return () => {
      active = false;
    };
  }, [isPreviewPage, preview, session.status, submissionId, workspaceId]);

  function updateCriterion(criterionId: string, patch: Partial<ScoreDraft[string]>) {
    scoreCommandRef.current = null;
    setDraft((current) => ({ ...current, [criterionId]: { ...current[criterionId], ...patch } }));
    setErrors((current) => {
      if (!current[criterionId]) return current;
      const next = { ...current };
      delete next[criterionId];
      return next;
    });
  }

  function enterRescore() {
    if (!snapshot || !latest) return;
    const nextRevisionId = latest.question_revision_id;
    setSelectedRevisionId(nextRevisionId);
    setDraft(initialDraft(revisionFor(snapshot, nextRevisionId), latest));
    setOverallReason(latest.overall_reason ?? "");
    setParentScoreId(latest.id);
    setRescoreMode(true);
    setErrors({});
    scoreCommandRef.current = null;
  }

  function changeRescoreRevision(nextRevisionId: string) {
    if (!snapshot || !rescoreMode) return;
    const target = revisionFor(snapshot, nextRevisionId);
    setSelectedRevisionId(nextRevisionId);
    setDraft(initialDraft(target, nextRevisionId === latest?.question_revision_id ? latest : undefined));
    setOverallReason(nextRevisionId === latest?.question_revision_id ? latest?.overall_reason ?? "" : "");
    setErrors({});
    scoreCommandRef.current = null;
  }

  function validateDraft(revision: QuestionRevision) {
    const nextErrors: Record<string, string> = {};
    for (const criterion of revision.criteria) {
      const item = draft[criterion.id] ?? { score: "", reason: "", hardFailTriggered: null };
      const numeric = Number.parseInt(item.score, 10);
      const validInteger = /^\d+$/.test(item.score);
      if (!validInteger || !Number.isInteger(numeric)) {
        nextErrors[criterion.id] = "请输入整数分数。";
        continue;
      }
      if (numeric < 0 || numeric > criterion.max_score) {
        nextErrors[criterion.id] = `分数必须在 0–${criterion.max_score} 之间。`;
        continue;
      }
      if (criterion.critical_mode === "hard_fail" && item.hardFailTriggered === null) {
        nextErrors[criterion.id] = "请先选择是否命中一票否决条件。";
        continue;
      }
      const criticalFailed = criterion.critical_mode === "minimum"
        && (criterion.critical_min_score == null || numeric < criterion.critical_min_score);
      const reasonRequired = numeric < criterion.reference_expected_score || criticalFailed || item.hardFailTriggered === true;
      if (reasonRequired && !item.reason.trim()) {
        nextErrors[criterion.id] = "低于标准答案锚点或关键项失败时，理由不能为空。";
      }
    }
    return nextErrors;
  }

  async function saveScore() {
    if (!snapshot || busy || preview) return;
    const activeRevision = revisionFor(snapshot, selectedRevisionId);
    const nextErrors = validateDraft(activeRevision);
    setErrors(nextErrors);
    const firstError = Object.keys(nextErrors)[0];
    if (firstError) {
      const message = nextErrors[firstError];
      if (message.includes("理由")) document.getElementById(`reason-${firstError}`)?.focus();
      else if (message.includes("一票否决")) document.querySelector<HTMLInputElement>(`input[name="hard-fail-${firstError}"]`)?.focus();
      else document.getElementById(`score-${firstError}`)?.focus();
      return;
    }
    setBusy(true);
    setFault(null);
    if (!scoreCommandRef.current) scoreCommandRef.current = commandId(rescoreMode ? "rescore" : "score");
    const items = activeRevision.criteria.map((criterion) => {
      const item = draft[criterion.id];
      const value: {
        criterion_id: string;
        score: number;
        reason?: string | null;
        hard_fail_triggered?: boolean | null;
      } = {
        criterion_id: criterion.id,
        score: Number.parseInt(item.score, 10),
        reason: item.reason.trim() || null,
      };
      if (criterion.critical_mode === "hard_fail") value.hard_fail_triggered = item.hardFailTriggered;
      return value;
    });
    try {
      const scoreInput = {
        command_id: scoreCommandRef.current,
        items,
        overall_reason: overallReason.trim() || null,
        parent_score_id: rescoreMode ? parentScoreId : null,
        ...(rescoreMode ? { question_revision_id: activeRevision.id } : {}),
      };
      await submitScore(workspaceId, submissionId, scoreInput);
      let refreshed: HumanSubmissionResponse;
      try {
        refreshed = await getSubmission(workspaceId, submissionId);
      } catch (cause) {
        const next = toPageFault(cause);
        setLoad({ status: "failed", fault: next });
        setFault(next);
        if (next.kind === "unauthorized") session.reload();
        return;
      }
      setLoad({ status: "ready", snapshot: refreshed });
      const refreshedLatest = latestScore(refreshed.scores ?? []);
      const refreshedRevisionId = refreshedLatest?.question_revision_id ?? refreshed.question_revision.id;
      setSelectedRevisionId(refreshedRevisionId);
      setDraft(initialDraft(revisionFor(refreshed, refreshedRevisionId), refreshedLatest ?? undefined));
      setRescoreMode(false);
      setParentScoreId(null);
      setOverallReason("");
      setErrors({});
      scoreCommandRef.current = null;
      requestAnimationFrame(() => resultTitleRef.current?.focus());
    } catch (cause) {
      handleCommandError(cause);
    } finally {
      setBusy(false);
    }
  }

  function handleCommandError(cause: unknown) {
    const next = toPageFault(cause);
    setFault(next);
    if (next.kind === "unauthorized" || next.kind === "forbidden" || next.kind === "not_found") {
      setLoad({ status: "failed", fault: next });
    }
    if (next.kind === "unauthorized") session.reload();
  }

  const title = snapshot
    ? revisionFor(snapshot, selectedRevisionId).title
    : "人工评分";
  const railRight = scoringRailRight(session, preview);
  const crumbs = scoringCrumbs(title);
  if (preview === "loading" || (!preview && session.status === "loading")) return <PageShell chromeOnly crumbs={crumbs} previewStates={HUMAN_PREVIEW_BAR_STATES} right={railRight}><EntrySkeleton /></PageShell>;
  if (!preview && session.status === "anonymous") return <PageShell crumbs={crumbs} mainClassName="page-mid" previewStates={HUMAN_PREVIEW_BAR_STATES} right={railRight}><FaultPanel fault={session.fault} returnTo={returnTo} /></PageShell>;
  if (!preview && session.status === "failed") return <PageShell crumbs={crumbs} mainClassName="page-mid" previewStates={HUMAN_PREVIEW_BAR_STATES} right={railRight}><FaultPanel fault={session.fault} returnTo={returnTo} title="登录状态读取失败" /></PageShell>;
  if (preview === "empty" || preview === "error" || preview === "unauthorized" || preview === "forbidden" || preview === "not_found" || preview === "human_invalid") {
    const previewFault: PageFault = preview === "unauthorized"
      ? { kind: "unauthorized", code: "AUTH_REQUIRED", message: "请先登录。" }
      : preview === "forbidden"
        ? { kind: "forbidden", code: "FORBIDDEN", message: "这份答卷不属于当前场景。" }
          : preview === "not_found"
            ? { kind: "not_found", code: "RESOURCE_NOT_FOUND", message: "待评答卷不存在。" }
          : preview === "empty"
            ? { kind: "failed", code: "NO_SUBMISSION", message: "还没有可读取的待评答卷。" }
            : { kind: "failed", code: "SUBMISSION_INVALID", message: "答卷快照暂时无法读取。" };
    return <PageShell crumbs={crumbs} mainClassName="page-mid" previewStates={HUMAN_PREVIEW_BAR_STATES} right={railRight}><FaultPanel fault={previewFault} returnTo={returnTo} title="答卷暂时无法读取" /></PageShell>;
  }
  if (load.status === "loading") return <PageShell chromeOnly crumbs={crumbs} previewStates={HUMAN_PREVIEW_BAR_STATES} right={railRight}><EntrySkeleton /></PageShell>;
  if (load.status === "failed") return <PageShell crumbs={crumbs} mainClassName="page-mid" previewStates={HUMAN_PREVIEW_BAR_STATES} right={railRight}><FaultPanel fault={load.fault} returnTo={returnTo} /></PageShell>;
  if (!snapshot) return null;

  const scores = snapshot.scores ?? [];
  const editing = scores.length === 0 || rescoreMode;
  const displayScore = latest;
  const revisions = revisionMap(snapshot);
  const activeRevision = revisionFor(snapshot, rescoreMode ? selectedRevisionId : latest?.question_revision_id);

  return (
    <PageShell crumbs={crumbs} mainClassName={`${styles.page} stack-lg`} previewStates={HUMAN_PREVIEW_BAR_STATES} right={railRight}>
      <div data-testid="human-scoring-page" className="stack-lg">
        <header className={styles.header}>
          <div className="stack-sm">
            <span className="section-label">人工评分 · 题 v{activeRevision.revision_number}</span>
            <h1 className="doc-title">{activeRevision.title}</h1>
            <p className="secondary">{activeRevision.summary}</p>
          </div>
          <span className={editing ? "state state-amber" : "state state-green"}>
            <span className="dot" />{editing ? (scores.length > 0 ? "重新评分" : "待评分") : "已提交"}
          </span>
        </header>
        {fault && <Note title="操作没有完成" tone="fail">{fault.message}</Note>}
        <div className={styles.layout}>
          <div className={`${styles.answerColumn} stack-lg`}>
            <section className={`sheet sheet-pad ${styles.answerSheet}`} aria-label="待评答卷">
              <div className="row-between">
                <div className="stack-sm">
                  <span className="section-label">待评答卷</span>
                  <h2 className="doc-title-sm">{snapshot.submission.original_name ?? "粘贴文本"}</h2>
                </div>
                <span className="state state-neutral"><span className="dot" />独立答卷</span>
              </div>
              <div className={styles.answerMeta}>
                <span>{snapshot.submission.size_bytes.toLocaleString("zh-CN")} 字节</span>
                <span>{snapshot.submission.media_type}</span>
                <span>{formatScoreDate(snapshot.submission.submitted_at)}</span>
              </div>
              <div className={styles.answerText}>{snapshot.submission.content_text}</div>
            </section>
            <StandardColumn revision={activeRevision} />
            <ScoreHistory revisions={revisions} scores={scores} />
          </div>
          <aside className={styles.reviewColumn} aria-label="连续评分">
            <form className={`sheet sheet-pad ${styles.reviewSheet}`} onSubmit={(event) => { event.preventDefault(); void saveScore(); }}>
              <div className={styles.rubricLead}>
                <div className="stack-sm">
                  <span className="section-label">连续评分</span>
                  <h2 className="doc-title-sm">按标准逐项判断</h2>
                </div>
                <div className={styles.rubricSummary}>
                  <div className={styles.rubricSummaryItem}><strong>100</strong><span>规则满分</span></div>
                  <div className={styles.rubricSummaryItem}><strong>{snapshot.question_revision.pass_threshold}</strong><span>总分通过线</span></div>
                </div>
              </div>
              {editing ? (
                <>
                  {rescoreMode && (
                    <RevisionPicker
                      disabled={busy}
                      onChange={changeRescoreRevision}
                      revisions={revisionOptions(snapshot)}
                      value={activeRevision.id}
                    />
                  )}
                  <div className={styles.criteria}>
                    {activeRevision.criteria.map((criterion) => (
                      <CriterionCard
                        criterion={criterion}
                        disabled={busy}
                        draft={draft[criterion.id] ?? { score: "", reason: "", hardFailTriggered: null }}
                        error={errors[criterion.id]}
                        key={criterion.id}
                        onChange={(patch) => updateCriterion(criterion.id, patch)}
                      />
                    ))}
                  </div>
                  <Field htmlFor="overall-reason" hint="可选" label="整体说明">
                    <AutoTextarea
                      id="overall-reason"
                      minRows={3}
                      onChange={(event) => {
                        setOverallReason(event.target.value);
                        scoreCommandRef.current = null;
                      }}
                      placeholder="补充这次评分的整体判断…"
                      value={overallReason}
                    />
                  </Field>
                  <Button busy={busy} busyLabel="正在保存评分…" className={styles.submit} disabled={busy} size="lg" type="submit" variant="primary">
                    {rescoreMode ? "保存重新评分" : "提交评分"}
                  </Button>
                </>
              ) : displayScore ? (
                <>
                  <div ref={resultTitleRef} tabIndex={-1}>
                    <ResultSummary passThreshold={activeRevision.pass_threshold} score={displayScore} />
                  </div>
                  <Button className={styles.submit} onClick={enterRescore} size="lg" type="button" variant="primary">
                    重新评分
                  </Button>
                </>
              ) : null}
            </form>
          </aside>
        </div>
      </div>
    </PageShell>
  );
}
