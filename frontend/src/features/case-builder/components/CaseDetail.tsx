"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { DeskRail } from "@/src/components/shell/DeskRail";
import { Button, ButtonLink } from "@/src/components/ui/Button";
import { Note } from "@/src/components/ui/Note";
import { SkeletonClaim, SkeletonLine } from "@/src/components/ui/Skeleton";
import { StatePanel } from "@/src/components/ui/StatePanel";
import { UserChip } from "@/src/features/auth/components/UserChip";
import { useSession } from "@/src/features/auth/hooks/useSession";
import { AttachmentStrip } from "@/src/features/case-builder/components/AttachmentStrip";
import { ConfirmedCard } from "@/src/features/case-builder/components/ConfirmedCard";
import { DraftEditor } from "@/src/features/case-builder/components/DraftEditor";
import { DraftView } from "@/src/features/case-builder/components/DraftView";
import { ProgressTrack } from "@/src/features/case-builder/components/ProgressTrack";
import { QuestionCard } from "@/src/features/case-builder/components/QuestionCard";
import { hasTeacherAnswer, STATE_META, TONE_CLASS } from "@/src/features/case-builder/lib/caseState";
import {
  PREVIEW_CASE_AI_FAILED,
  PREVIEW_CASE_CONFIRMED,
  PREVIEW_CASE_PARSE_EMPTY,
  PREVIEW_CASE_WAITING_CONFIRMATION,
  PREVIEW_CASE_WAITING_INPUT,
} from "@/src/features/case-builder/preview/fixtures";
import {
  answerQuestion,
  type Case,
  confirmCase,
  type DraftContent,
  generateDraft,
  getCase,
} from "@/src/features/case-builder/services/caseBuilderService";
import { loginHref, toPageFault, type PageFault } from "@/src/lib/api/pageFault";
import { stamp } from "@/src/lib/format";
import { PreviewBar, usePreviewState, type PreviewState } from "@/src/lib/preview/preview";

type Load =
  | { status: "loading" }
  | { status: "ready"; case: Case }
  | { status: "failed"; fault: PageFault };

const PREVIEW_CASES: Partial<Record<PreviewState, Case>> = {
  empty: PREVIEW_CASE_PARSE_EMPTY,
  error: PREVIEW_CASE_AI_FAILED,
  question: PREVIEW_CASE_WAITING_INPUT,
  review: PREVIEW_CASE_WAITING_CONFIRMATION,
  success: PREVIEW_CASE_CONFIRMED,
};

/** 整理中的占位：撑住草稿最终的版面高度，AI 返回时页面不跳。 */
function DraftSkeleton({ title }: { title: string }) {
  return (
    <section aria-busy="true" className="sheet">
      <div className="sheet-head spread">
        <span className="row" style={{ gap: "var(--s-2)" }}>
          <span className="state state-active">
            <span className="dot pulse-dot" />
            {title}
          </span>
        </span>
        <SkeletonLine height={11} width="72px" />
      </div>
      <div className="sheet-pad stack">
        <SkeletonClaim lines={2} />
        <SkeletonClaim lines={1} />
        <SkeletonClaim lines={3} />
        <SkeletonClaim lines={2} />
      </div>
    </section>
  );
}

export function CaseDetail({ workspaceId, caseId }: { workspaceId: string; caseId: string }) {
  const router = useRouter();
  const preview = usePreviewState();
  const session = useSession();

  const [load, setLoad] = useState<Load>({ status: "loading" });
  const [previewCase, setPreviewCase] = useState<Case | null>(null);
  const [busy, setBusy] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [commandFault, setCommandFault] = useState<PageFault | null>(null);
  const [answered, setAnswered] = useState(false);
  const generationStarted = useRef(false);

  const authenticated = session.status === "authenticated";
  const returnTo = `/workspaces/${workspaceId}/cases/${caseId}`;

  const read = useCallback(
    async ({ auto, silent }: { auto: boolean; silent: boolean }) => {
      if (silent) setRefreshing(true);
      try {
        const result = await getCase(workspaceId, caseId);
        let current = result.case;
        // 合同要求解析就绪后自动请一次草稿；后端状态保护负责防止重复运行。
        if (auto && current.state === "ready_for_ai" && !generationStarted.current) {
          generationStarted.current = true;
          setBusy(true);
          current = (await generateDraft(workspaceId, caseId)).case;
        }
        setLoad({ status: "ready", case: current });
        setCommandFault(null);
      } catch (cause) {
        const fault = toPageFault(cause);
        setLoad((current) =>
          current.status === "ready" && silent ? current : { status: "failed", fault },
        );
        if (silent) setCommandFault(fault);
      } finally {
        setBusy(false);
        setRefreshing(false);
      }
    },
    [caseId, workspaceId],
  );

  useEffect(() => {
    if (preview) {
      setPreviewCase(PREVIEW_CASES[preview] ?? null);
      return;
    }
    if (!authenticated) return;
    generationStarted.current = false;
    setAnswered(false);
    void read({ auto: true, silent: false });
  }, [authenticated, preview, read]);

  useEffect(() => {
    if (preview) return;
    if (session.status === "anonymous") router.replace(loginHref(returnTo));
  }, [preview, returnTo, router, session.status]);

  // parsing / generating 是同步命令留下的过渡态，只做温和轮询，不引入推送协议。
  const liveState = load.status === "ready" ? load.case.state : null;
  useEffect(() => {
    if (preview || busy) return;
    if (liveState !== "parsing" && liveState !== "generating") return;
    const timer = setTimeout(() => void read({ auto: false, silent: true }), 2500);
    return () => clearTimeout(timer);
  }, [busy, liveState, preview, read]);

  async function runCommand(command: () => Promise<{ case: Case }>) {
    setBusy(true);
    setCommandFault(null);
    try {
      const result = await command();
      setLoad({ status: "ready", case: result.case });
    } catch (cause) {
      setCommandFault(toPageFault(cause));
    } finally {
      setBusy(false);
    }
  }

  function onRetry() {
    if (preview) {
      setPreviewCase(PREVIEW_CASE_WAITING_CONFIRMATION);
      return;
    }
    void runCommand(() => generateDraft(workspaceId, caseId));
  }

  function onAnswer(answer: string) {
    setAnswered(true);
    if (preview) {
      setPreviewCase(PREVIEW_CASE_WAITING_CONFIRMATION);
      return;
    }
    const question = load.status === "ready" ? load.case.builder.pending_question : null;
    if (!question) return;
    void runCommand(() => answerQuestion(workspaceId, caseId, { question_id: question.id, answer }));
  }

  function onConfirm(content: DraftContent) {
    if (preview) {
      setPreviewCase(PREVIEW_CASE_CONFIRMED);
      return;
    }
    if (load.status !== "ready") return;
    void runCommand(() =>
      confirmCase(workspaceId, caseId, {
        draft_revision: load.case.builder.draft_revision,
        content,
      }),
    );
  }

  const shown: Case | null = preview ? previewCase : load.status === "ready" ? load.case : null;

  const rail = (
    <DeskRail
      crumbs={[
        { label: "场景", href: "/workspaces" },
        { label: shown?.title ?? "真实案例" },
      ]}
      right={
        <UserChip previewName={preview ? "teacher-a" : undefined} session={session} />
      }
    />
  );
  const previewBar = (
    <PreviewBar
      states={[
        "loading",
        "empty",
        "question",
        "review",
        "success",
        "error",
        "unauthorized",
        "forbidden",
        "not_found",
      ]}
    />
  );

  const unauthorized = preview === "unauthorized" || (!preview && session.status === "anonymous");
  if (unauthorized) {
    return (
      <>
        {rail}
        {previewBar}
        <main className="page page-wide">
          <StatePanel
            actions={<ButtonLink href={loginHref(returnTo)} variant="primary">去登录</ButtonLink>}
            code="401 · AUTH_REQUIRED"
            description="地址里带着案例编号也不代表有权限。会话失效时页面不会渲染标题、材料、草稿或候选标准案例。"
            title="需要登录才能查看这个真实案例"
            tone="locked"
          />
        </main>
      </>
    );
  }

  const fault: PageFault | null =
    preview === "forbidden"
      ? { kind: "forbidden", code: "FORBIDDEN", message: "你无权访问这个真实案例。" }
      : preview === "not_found"
        ? { kind: "not_found", code: "RESOURCE_NOT_FOUND", message: "真实案例不存在。" }
        : !preview && session.status === "failed"
          ? session.fault
          : !preview && load.status === "failed"
            ? load.fault
            : null;

  if (fault) {
    const copy =
      fault.kind === "forbidden"
        ? {
            title: "这个真实案例不属于当前账号",
            body: "真实案例、材料、草稿和候选标准案例都继承场景归属。页面不会用已有缓存继续渲染任何内容。",
            hint: "403",
          }
        : fault.kind === "not_found"
          ? {
              title: "真实案例不存在",
              body: "在你的授权范围内查不到这个案例。不会用另一个场景编号猜测读取。",
              hint: "404",
            }
          : { title: "案例读取失败", body: fault.message, hint: "500" };
    return (
      <>
        {rail}
        {previewBar}
        <main className="page page-wide">
          <StatePanel
            actions={
              <>
                <ButtonLink href="/workspaces" variant="primary">
                  回到场景
                </ButtonLink>
                {fault.kind === "failed" && (
                  <Button onClick={() => void read({ auto: false, silent: false })}>
                    重新读取
                  </Button>
                )}
              </>
            }
            code={`${copy.hint} · ${fault.code}`}
            description={copy.body}
            title={copy.title}
            tone="fault"
          />
        </main>
      </>
    );
  }

  if (preview === "loading" || !shown) {
    return (
      <>
        {rail}
        {previewBar}
        <main aria-busy="true" className="page page-wide stack-lg">
          <section className="sheet">
            <div className="sheet-head spread">
              <SkeletonLine height={11} width="120px" />
              <SkeletonLine height={20} width="88px" />
            </div>
            <div className="sheet-pad stack">
              <SkeletonLine height={30} width="52%" />
              <SkeletonLine height={40} />
              <SkeletonLine height={64} />
            </div>
            <div className="sheet-foot">
              <SkeletonLine height={12} />
            </div>
          </section>
          <DraftSkeleton title="正在读取案例快照" />
        </main>
      </>
    );
  }

  const { builder, state } = shown;
  const meta = STATE_META[state];
  const draft = builder.draft;

  return (
    <>
      {rail}
      {previewBar}
      <main className="page page-wide stack-lg">
        <section className="sheet">
          <div className="sheet-head spread">
            <span className="mono faint">案例编号 · {shown.id.slice(0, 8)}</span>
            <div className="row" style={{ gap: "var(--s-2)" }}>
              <span className={`state ${TONE_CLASS[meta.tone]}`}>
                <span
                  className={`dot${state === "generating" || state === "parsing" ? " pulse-dot" : ""}`}
                />
                {meta.label}
              </span>
              <Button
                busy={refreshing}
                busyLabel="读取中…"
                disabled={busy}
                onClick={() => void read({ auto: false, silent: true })}
                size="sm"
                variant="quiet"
              >
                刷新
              </Button>
            </div>
          </div>
          <div className="sheet-pad stack">
            <h1 className="doc-title">{shown.title}</h1>
            <AttachmentStrip attachment={shown.attachment} />
            {shown.task_description && (
              <div className="inset stack-sm">
                <span className="section-label">任务说明</span>
                <p className="doc-body">{shown.task_description}</p>
              </div>
            )}
            <span className="mono faint">
              上传于 {stamp(shown.created_at)} · 更新于 {stamp(shown.updated_at)}
            </span>
          </div>
          <div className="sheet-foot">
            <ProgressTrack
              answered={answered || hasTeacherAnswer(draft)}
              hasDraft={Boolean(draft)}
              state={state}
            />
          </div>
        </section>

        {commandFault && state !== "waiting_for_confirmation" && state !== "waiting_for_input" && (
          <Note code={commandFault.code} title="上一个命令没有被接受" tone="fail">
            {commandFault.message}
          </Note>
        )}

        {state === "parsing" && <DraftSkeleton title="正在解析材料" />}

        {state === "parse_failed" && (
          <StatePanel
            actions={
              <ButtonLink href={`/workspaces/${workspaceId}/cases/new`} variant="primary">
                修正后重新上传
              </ButtonLink>
            }
            code={builder.last_error?.code}
            description={
              builder.last_error?.message ??
              "这份材料无法解析。已经留下可追踪的失败记录，但不会进入 AI 整理。"
            }
            title="解析失败"
            tone="fault"
          >
            <p className="mono faint">retryable · false — 同一个文件重试没有意义</p>
          </StatePanel>
        )}

        {(state === "ready_for_ai" || state === "generating") && (
          <DraftSkeleton title={state === "generating" ? "AI 整理中" : "正在请 AI 整理"} />
        )}

        {state === "ai_failed" && (
          <StatePanel
            actions={
              builder.last_error?.retryable ? (
                <Button busy={busy} busyLabel="正在重试…" onClick={onRetry} variant="primary">
                  重试 AI 整理
                </Button>
              ) : (
                <ButtonLink href="/workspaces" variant="primary">
                  回到场景
                </ButtonLink>
              )
            }
            code={builder.last_error?.code}
            description={builder.last_error?.message ?? "AI 处理失败。"}
            title="整理失败"
            tone="fault"
          >
            <p className="mono faint">
              retryable · {String(builder.last_error?.retryable ?? false)} — 重试沿用同一个会话，不会新建
            </p>
          </StatePanel>
        )}

        {state === "waiting_for_input" && builder.pending_question && (
          <QuestionCard
            busy={busy}
            fault={commandFault}
            onSubmit={onAnswer}
            question={builder.pending_question}
          />
        )}

        {state === "waiting_for_confirmation" && draft && (
          <DraftEditor
            busy={busy}
            draft={draft}
            draftRevision={builder.draft_revision}
            fault={commandFault}
            onConfirm={onConfirm}
            onReload={() => void read({ auto: false, silent: true })}
          />
        )}

        {state === "confirmed" && shown.candidate_case && (
          <div className="stack">
            <ConfirmedCard candidate={shown.candidate_case} />
            <Note title="这是一条候选标准案例" tone="info">
              它还没有加入评测集，也没有触发任何评测。加入评测集、版本发布和评测属于后续阶段。
            </Note>
            <section className="sheet">
              <div className="sheet-head row-between">
                <div className="stack-sm">
                  <h2 className="doc-title-sm">已确认的标准内容</h2>
                  <p className="secondary" style={{ fontSize: "var(--t-14)" }}>
                    以下内容与数据库中保存的候选标准案例逐字一致，本页转为只读。
                  </p>
                </div>
                <span className="mono faint">v{shown.candidate_case.draft_revision}</span>
              </div>
              <div style={{ padding: "var(--s-6) var(--s-5)" }}>
                <DraftView draft={shown.candidate_case.content} />
              </div>
            </section>
          </div>
        )}
      </main>
    </>
  );
}
