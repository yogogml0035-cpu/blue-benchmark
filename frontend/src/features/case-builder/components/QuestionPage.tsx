"use client";

import { useRouter } from "next/navigation";
import { type FormEvent, useEffect, useState } from "react";

import { DeskRail } from "@/src/components/shell/DeskRail";
import { Button, ButtonLink } from "@/src/components/ui/Button";
import { Field } from "@/src/components/ui/Field";
import { Note } from "@/src/components/ui/Note";
import { SkeletonLine } from "@/src/components/ui/Skeleton";
import { StatePanel } from "@/src/components/ui/StatePanel";
import { AutoTextarea } from "@/src/components/ui/AutoTextarea";
import { Sheet } from "@/src/components/ui/Sheet";
import { UserChip } from "@/src/features/auth/components/UserChip";
import { useSession } from "@/src/features/auth/hooks/useSession";
import {
  answerCoCreation,
  confirmContract,
  confirmJudgment,
  getCoCreationSession,
  retryCoCreation,
  startCoCreation,
  type CoCreationSessionView,
} from "@/src/features/workspaces/services/studioService";
import { getTaskPackage, type TaskPackageSummary } from "@/src/features/workspaces/services/studioService";
import { loginHref, toPageFault, type PageFault } from "@/src/lib/api/pageFault";
import { PreviewBar, usePreviewState } from "@/src/lib/preview/preview";

import styles from "./studio.module.css";

type Load =
  | { status: "loading" }
  | { status: "ready"; session: CoCreationSessionView | null; taskPackage: TaskPackageSummary }
  | { status: "failed"; fault: PageFault };

export function QuestionPage({
  workspaceId,
  questionId,
}: {
  workspaceId: string;
  questionId: string;
}) {
  const router = useRouter();
  const preview = usePreviewState();
  const session = useSession();

  const [load, setLoad] = useState<Load>({ status: "loading" });
  const [busy, setBusy] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [answer, setAnswer] = useState("");
  const [commandFault, setCommandFault] = useState<PageFault | null>(null);
  const [showStandards, setShowStandards] = useState(false);

  const authenticated = session.status === "authenticated";
  const returnTo = `/workspaces/${workspaceId}/questions/${questionId}`;

  useEffect(() => {
    if (preview) return;
    if (session.status === "anonymous") router.replace(loginHref(returnTo));
  }, [preview, returnTo, router, session.status]);

  useEffect(() => {
    if (preview || !authenticated) return;
    let active = true;
    setLoad({ status: "loading" });

    // questionId 是 taskPackageId；start 对已存在的共创会话幂等，直接复用
    getTaskPackage(workspaceId, questionId)
      .then((result) => {
        if (!active) return;
        const pkg = result.task_package;
        if (pkg.status === "confirmed" && pkg.has_judgment_package) {
          // 已定稿的题直接进入定稿态展示，无需再启动共创会话
          setLoad({ status: "ready", session: null, taskPackage: pkg });
          return;
        }
        return startCoCreation(workspaceId, questionId, {
          commandId: `start-${questionId}-${Date.now()}`,
          kind: "task_judgment",
          taskPackageRevision: pkg.revision,
        }).then((sessionResult) => {
          if (!active) return;
          setLoad({ status: "ready", session: sessionResult.session, taskPackage: pkg });
        });
      })
      .catch((cause: unknown) => {
        if (active) setLoad({ status: "failed", fault: toPageFault(cause) });
      });

    return () => {
      active = false;
    };
  }, [preview, authenticated, workspaceId, questionId]);

  // 轮询：等待 AI 处理完成
  useEffect(() => {
    if (preview || load.status !== "ready") return;
    const { session: cocreationSession } = load;
    if (!cocreationSession) return;
    if (
      cocreationSession.status !== "processing" &&
      cocreationSession.status !== "queued" &&
      cocreationSession.status !== "projection_pending"
    ) return;
    const sessionId = cocreationSession.id;
    const timer = setTimeout(() => {
      void getCoCreationSession(workspaceId, sessionId)
        .then((result) => {
          setLoad((current) =>
            current.status === "ready"
              ? { ...current, session: result.session }
              : current,
          );
        })
        .catch(() => undefined);
    }, 2000);
    return () => clearTimeout(timer);
  }, [preview, load, workspaceId]);

  async function submitAnswer(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!answer.trim() || load.status !== "ready") return;
    const { session: cocreationSession } = load;
    if (!cocreationSession) return;
    const question = cocreationSession.pending_question;
    if (!question) return;

    setBusy(true);
    setCommandFault(null);
    try {
      const result = await answerCoCreation(workspaceId, cocreationSession.id, {
        commandId: `answer-${question.id}-${Date.now()}`,
        questionId: question.id,
        answer: answer.trim(),
        businessRevision: cocreationSession.business_revision,
      });
      setLoad({ status: "ready", session: result.session, taskPackage: load.taskPackage });
      setAnswer("");
    } catch (cause) {
      setCommandFault(toPageFault(cause));
    } finally {
      setBusy(false);
    }
  }

  async function onConfirm() {
    if (load.status !== "ready") return;
    const { session: cocreationSession } = load;
    if (!cocreationSession) return;
    setBusy(true);
    setCommandFault(null);
    try {
      const confirmFn = cocreationSession.kind === "scenario_contract" ? confirmContract : confirmJudgment;
      const result = await confirmFn(workspaceId, cocreationSession.id, {
        commandId: `confirm-${cocreationSession.id}-${Date.now()}`,
        businessRevision: cocreationSession.business_revision,
      });
      setLoad({ status: "ready", session: result.session, taskPackage: load.taskPackage });
    } catch (cause) {
      setCommandFault(toPageFault(cause));
    } finally {
      setBusy(false);
    }
  }

  async function onRetry() {
    if (load.status !== "ready") return;
    const { session: cocreationSession } = load;
    if (!cocreationSession) return;
    setBusy(true);
    setCommandFault(null);
    try {
      const result = await retryCoCreation(workspaceId, cocreationSession.id, {
        commandId: `retry-${cocreationSession.id}-${Date.now()}`,
        businessRevision: cocreationSession.business_revision,
      });
      setLoad({ status: "ready", session: result.session, taskPackage: load.taskPackage });
    } catch (cause) {
      setCommandFault(toPageFault(cause));
    } finally {
      setBusy(false);
    }
  }

  const rail = (
    <DeskRail
      crumbs={[
        { label: "场景", href: "/workspaces" },
        { label: load.status === "ready" ? load.taskPackage.title : "题稿共创" },
      ]}
      right={
        <UserChip previewName={preview ? "teacher-a" : undefined} session={session} />
      }
    />
  );
  const previewBar = (
    <PreviewBar
      states={["loading", "empty", "question", "review", "success", "error", "unauthorized", "forbidden", "not_found"]}
    />
  );

  const unauthorized = preview === "unauthorized" || (!preview && session.status === "anonymous");
  if (unauthorized) {
    return (
      <>
        {rail}
        {previewBar}
        <main className="page page-mid">
          <StatePanel
            actions={<ButtonLink href={loginHref(returnTo)} variant="primary">去登录</ButtonLink>}
            code="401 · AUTH_REQUIRED"
            description="登录后才能查看这道题。"
            title="需要登录"
            tone="locked"
          />
        </main>
      </>
    );
  }

  if (load.status === "failed") {
    const fault = load.fault;
    return (
      <>
        {rail}
        {previewBar}
        <main className="page page-mid">
          <StatePanel
            actions={
              <ButtonLink href={`/workspaces/${workspaceId}`} variant="primary">
                回到工作台
              </ButtonLink>
            }
            code={fault.code}
            description={fault.message}
            title="题稿读取失败"
            tone="fault"
          />
        </main>
      </>
    );
  }

  if (load.status === "loading") {
    return (
      <>
        {rail}
        {previewBar}
        <main className="page page-mid stack-lg">
          <div aria-busy="true" className="stack">
            <SkeletonLine height={28} width="40%" />
            <div className="sheet sheet-pad stack">
              <SkeletonLine height={20} width="60%" />
              <SkeletonLine height={40} />
              <SkeletonLine height={80} />
            </div>
          </div>
        </main>
      </>
    );
  }

  const { session: cocreationSession, taskPackage } = load;

  // 已定稿且无可共创会话：直接展示定稿状态
  if (!cocreationSession) {
    return (
      <>
        {rail}
        {previewBar}
        <main className="page page-mid stack-lg">
          <div className="stack-sm">
            <div className="spread">
              <h1 className="doc-title">{taskPackage.title}</h1>
              <span className="state state-green">
                <span className="dot" />
                已定稿
              </span>
            </div>
            <p className="secondary">这道题已定稿，内容进入下一版评测集。</p>
          </div>
          <section className="sheet sheet-pad stack">
            <p className="secondary">定稿后的内容不可修改，会进入下一版评测集。</p>
            <div className="row">
              <ButtonLink href={`/workspaces/${workspaceId}?section=versions`} variant="primary">
                去版本页查看
              </ButtonLink>
            </div>
          </section>
        </main>
      </>
    );
  }

  const question = cocreationSession.pending_question;
  const status = cocreationSession.status;

  return (
    <>
      {rail}
      {previewBar}
      <main className="page page-mid stack-lg">
        <div className="stack-sm">
          <div className="spread">
            <h1 className="doc-title">{taskPackage.title}</h1>
            <span className={`state ${status === "confirmed" ? "state-green" : status === "failed" ? "state-red" : status === "waiting_for_teacher" ? "state-amber" : "state-active"}`}>
              <span className={`dot${status === "processing" || status === "queued" ? " pulse-dot" : ""}`} />
              {status === "confirmed"
                ? "已定稿"
                : status === "failed"
                  ? "整理失败"
                  : status === "waiting_for_teacher"
                    ? "需要补充"
                    : status === "ready_for_confirmation"
                      ? "待你定稿"
                      : status === "continuity_reset"
                        ? "已重置"
                        : "AI 整理中"}
            </span>
          </div>
          <p className="secondary">
            {cocreationSession.kind === "scenario_contract" ? "场景标准共创" : "题稿共创"} · 修订 {cocreationSession.business_revision}
          </p>
        </div>

        {commandFault && (
          <Note code={commandFault.code} title="操作失败" tone="fail">
            {commandFault.message}
          </Note>
        )}

        {/* 处理中状态 */}
        {(status === "queued" || status === "processing" || status === "projection_pending") && (
          <section className="sheet sheet-pad stack" aria-live="polite">
            <div className="row" style={{ gap: "var(--s-2)" }}>
              <span className="state state-active">
                <span className="dot pulse-dot" />
                正在处理
              </span>
            </div>
            <p className="secondary">
              AI 正在整理你的回答和现有资料，完成后会显示本轮更新。
            </p>
          </section>
        )}

        {/* 连续性重置：会话被重置，需要重新开始 */}
        {status === "continuity_reset" && (
          <section className="sheet sheet-pad stack">
            <Note tone="amber" title="会话已重置">
              共创连续性已重置。请刷新页面重新开始。
            </Note>
            <div className="row">
              <Button onClick={() => window.location.reload()} variant="primary">
                刷新重试
              </Button>
            </div>
          </section>
        )}

        {/* 失败状态 */}
        {status === "failed" && (
          <section className="sheet sheet-pad stack">
            <Note tone="fail" title="整理失败">
              <p>AI 整理时遇到问题，你的回答已保存，不会丢失。</p>
              {cocreationSession.blocking_issues && cocreationSession.blocking_issues.length > 0 && (
                <ul className="stack-sm" style={{ marginTop: "var(--s-2)" }}>
                  {cocreationSession.blocking_issues.map((issue) => (
                    <li key={issue}>{issue}</li>
                  ))}
                </ul>
              )}
            </Note>
            <div className="row">
              <Button busy={busy} busyLabel="正在重试…" onClick={onRetry} variant="primary">
                重试整理
              </Button>
            </div>
          </section>
        )}

        {/* 等待回答 */}
        {status === "waiting_for_teacher" && question && (
          <section className="sheet sheet-pad stack">
            <div className="stack-sm">
              <span className="section-label">需要补充</span>
              <h2 className="doc-title-sm">{question.text}</h2>
              <p className="secondary">为什么问：{question.reason}</p>
              {question.gap_type && (
                <p className="mono faint" style={{ fontSize: "var(--t-12)" }}>
                  缺口类型：{question.gap_type}
                </p>
              )}
            </div>
            <form className="stack" onSubmit={submitAnswer}>
              <Field htmlFor="answer" label="你的回答">
                <AutoTextarea
                  autoFocus
                  className="control"
                  disabled={busy}
                  id="answer"
                  maxLength={10000}
                  minRows={4}
                  onChange={(event) => setAnswer(event.target.value)}
                  placeholder="写清楚你的判断和理由。"
                  value={answer}
                />
              </Field>
              <div className="row">
                <Button
                  busy={busy}
                  busyLabel="正在提交…"
                  disabled={!answer.trim()}
                  size="lg"
                  type="submit"
                  variant="primary"
                >
                  提交回答并继续
                </Button>
              </div>
            </form>
          </section>
        )}

        {/* 待确认 */}
        {status === "ready_for_confirmation" && (
          <section className="sheet sheet-pad stack">
            <div className="stack-sm">
              <span className="section-label">待你定稿</span>
              <h2 className="doc-title-sm">审阅本轮更新</h2>
              <p className="secondary">
                AI 已根据你的回答更新了内容。请审阅后定稿。
              </p>
            </div>
            {cocreationSession.turns && cocreationSession.turns.length > 0 && (
              <div className="stack-sm">
                <span className="section-label">本轮更新</span>
                {cocreationSession.turns.slice(-1).map((turn) => (
                  <div className="inset" key={turn.id} style={{ padding: "var(--s-3)" }}>
                    {turn.delta?.added && turn.delta.added.length > 0 && (
                      <p style={{ fontSize: "var(--t-13)" }}>新增 {turn.delta.added.length} 项</p>
                    )}
                    {turn.delta?.modified && turn.delta.modified.length > 0 && (
                      <p style={{ fontSize: "var(--t-13)" }}>修改 {turn.delta.modified.length} 项</p>
                    )}
                    {turn.delta?.deleted && turn.delta.deleted.length > 0 && (
                      <p style={{ fontSize: "var(--t-13)" }}>删除 {turn.delta.deleted.length} 项</p>
                    )}
                    {turn.delta?.unresolved && turn.delta.unresolved.length > 0 && (
                      <p className="secondary" style={{ fontSize: "var(--t-13)" }}>
                        仍有 {turn.delta.unresolved.length} 项疑问
                      </p>
                    )}
                  </div>
                ))}
              </div>
            )}
            <div className="row">
              <Button busy={busy} busyLabel="正在定稿…" onClick={onConfirm} size="lg" variant="primary">
                定稿
              </Button>
              <Button onClick={() => setShowStandards(true)} variant="secondary">
                查看标准与依据
              </Button>
            </div>
          </section>
        )}

        {/* 已定稿 */}
        {status === "confirmed" && (
          <section className="sheet sheet-pad stack">
            <div className="stack-sm">
              <span className="section-label">已定稿</span>
              <h2 className="doc-title-sm">这道题已定稿</h2>
              <p className="secondary">
                定稿后的内容不可修改，会进入下一版评测集。
              </p>
            </div>
            <div className="row">
              <ButtonLink href={`/workspaces/${workspaceId}?section=versions`} variant="primary">
                去版本页查看
              </ButtonLink>
            </div>
          </section>
        )}

        {/* 标准与依据 Sheet */}
        {showStandards && (
          <Sheet onClose={() => setShowStandards(false)} title="标准与依据">
            <div className="stack-lg">
              {cocreationSession.contract && (
                <section className="stack">
                  <h3 className="doc-title-sm">场景标准</h3>
                  <ContractView contract={cocreationSession.contract} />
                </section>
              )}
              {cocreationSession.judgment_package && (
                <section className="stack">
                  <h3 className="doc-title-sm">判定依据</h3>
                  <JudgmentView judgment={cocreationSession.judgment_package} />
                </section>
              )}
              {cocreationSession.turns && cocreationSession.turns.length > 0 && (
                <section className="stack">
                  <h3 className="doc-title-sm">形成过程</h3>
                  <div className="stack-sm">
                    {cocreationSession.turns.map((turn, index) => (
                      <div className="inset" key={turn.id} style={{ padding: "var(--s-3)" }}>
                        <p style={{ fontSize: "var(--t-13)", fontWeight: 600 }}>
                          第 {index + 1} 轮
                        </p>
                        {turn.question && (
                          <p style={{ fontSize: "var(--t-13)" }}>问：{turn.question.text}</p>
                        )}
                        {turn.answer && (
                          <p style={{ fontSize: "var(--t-13)" }}>答：{turn.answer}</p>
                        )}
                      </div>
                    ))}
                  </div>
                </section>
              )}
            </div>
          </Sheet>
        )}
      </main>
    </>
  );
}

type ContractContent = NonNullable<CoCreationSessionView["contract"]>;
type JudgmentContent = NonNullable<CoCreationSessionView["judgment_package"]>;

function KvBlock({ label, items }: { label: string; items: string[] }) {
  if (items.length === 0) return null;
  return (
    <div className="kv-block">
      <span className="kv-label">{label}</span>
      <ul className="kv-items">
        {items.map((item, index) => (
          <li key={index}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

function KvText({ label, text }: { label: string; text: string }) {
  if (!text) return null;
  return (
    <div className="kv-block">
      <span className="kv-label">{label}</span>
      <p className="kv-items">{text}</p>
    </div>
  );
}

function ContractView({ contract }: { contract: ContractContent }) {
  return (
    <div>
      <KvText label="任务边界" text={contract.task_boundary} />
      <KvBlock label="输入约定" items={contract.input_contract} />
      <KvBlock label="输出约定" items={contract.output_contract} />
      <KvBlock label="硬性门禁" items={contract.hard_gates} />
      <KvBlock label="质量维度" items={contract.quality_dimensions} />
      <KvBlock label="禁止错误" items={contract.prohibited_errors ?? []} />
      <KvBlock label="能力要求" items={contract.capabilities} />
    </div>
  );
}

function JudgmentView({ judgment }: { judgment: JudgmentContent }) {
  return (
    <div>
      <KvBlock label="参考结果" items={judgment.reference_results} />
      <KvBlock label="可接受理由" items={judgment.accepted_reasons} />
      <KvBlock label="拒绝理由" items={judgment.rejected_reasons} />
      <KvBlock label="硬性门禁" items={judgment.hard_gates} />
      <KvText label="最低质量线" text={judgment.minimum_quality_line} />
      <KvBlock label="任务规则" items={judgment.task_specific_rules} />
      <KvBlock label="能力要求" items={judgment.capabilities} />
      <KvBlock label="评分维度" items={judgment.dimensions} />
    </div>
  );
}
