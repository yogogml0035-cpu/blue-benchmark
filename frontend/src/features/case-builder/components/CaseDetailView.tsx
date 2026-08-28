"use client";

import Link from "next/link";
import { FormEvent, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { ApiError } from "@/src/lib/api/client";
import {
  answerQuestion,
  Case,
  confirmCase,
  DraftContent,
  generateDraft,
  getCase,
} from "@/src/features/case-builder/services/caseBuilderService";

const stateLabels: Record<Case["state"], string> = {
  parsing: "解析中",
  parse_failed: "解析失败",
  ready_for_ai: "等待 AI",
  generating: "AI 分析中",
  waiting_for_input: "等待补充信息",
  waiting_for_confirmation: "等待人工确认",
  ai_failed: "AI 失败",
  confirmed: "已确认",
};

export function CaseDetailView({ workspaceId, caseId }: { workspaceId: string; caseId: string }) {
  const router = useRouter();
  const generationStarted = useRef(false);
  const draftRevisionLoaded = useRef<number | null>(null);
  const [caseData, setCaseData] = useState<Case | null>(null);
  const [answer, setAnswer] = useState("");
  const [draftText, setDraftText] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  function handleError(cause: unknown) {
    if (cause instanceof ApiError && cause.status === 401) {
      router.replace(`/login?returnTo=${encodeURIComponent(window.location.pathname)}`);
      return;
    }
    setError(cause instanceof ApiError ? cause.message : "请求失败，请稍后重试。");
  }

  async function loadCase(startGeneration = true) {
    setLoading(true);
    setError("");
    try {
      const result = await getCase(workspaceId, caseId);
      setCaseData(result.case);
      const nextCase = result.case;
      if (nextCase.builder.draft && draftRevisionLoaded.current !== nextCase.builder.draft_revision) {
        setDraftText(JSON.stringify(nextCase.builder.draft, null, 2));
        draftRevisionLoaded.current = nextCase.builder.draft_revision;
      }
      if (startGeneration && nextCase.state === "ready_for_ai" && !generationStarted.current) {
        generationStarted.current = true;
        setBusy(true);
        const generated = await generateDraft(workspaceId, caseId);
        setCaseData(generated.case);
        if (generated.case.builder.draft) {
          setDraftText(JSON.stringify(generated.case.builder.draft, null, 2));
          draftRevisionLoaded.current = generated.case.builder.draft_revision;
        }
      }
    } catch (cause) {
      handleError(cause);
    } finally {
      setBusy(false);
      setLoading(false);
    }
  }

  useEffect(() => {
    generationStarted.current = false;
    draftRevisionLoaded.current = null;
    void loadCase();
    // The page owns one case ID for its lifetime; loadCase is intentionally local to this view.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspaceId, caseId]);

  async function retryGeneration() {
    setBusy(true);
    setError("");
    try {
      const result = await generateDraft(workspaceId, caseId);
      setCaseData(result.case);
      if (result.case.builder.draft) setDraftText(JSON.stringify(result.case.builder.draft, null, 2));
    } catch (cause) {
      handleError(cause);
    } finally {
      setBusy(false);
    }
  }

  async function submitAnswer(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!caseData?.builder.pending_question) return;
    setBusy(true);
    setError("");
    try {
      const result = await answerQuestion(workspaceId, caseId, {
        question_id: caseData.builder.pending_question.id,
        answer,
      });
      setCaseData(result.case);
      setAnswer("");
      if (result.case.builder.draft) setDraftText(JSON.stringify(result.case.builder.draft, null, 2));
    } catch (cause) {
      handleError(cause);
    } finally {
      setBusy(false);
    }
  }

  async function submitConfirmation(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!caseData) return;
    setBusy(true);
    setError("");
    try {
      const content = JSON.parse(draftText) as DraftContent;
      const result = await confirmCase(workspaceId, caseId, {
        draft_revision: caseData.builder.draft_revision,
        content,
      });
      setCaseData(result.case);
    } catch (cause) {
      handleError(cause instanceof SyntaxError ? new Error("草案必须是合法 JSON。") : cause);
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <main><p className="muted">正在加载案例…</p></main>;
  if (!caseData) return <main><div className="error">{error || "案例不存在或暂时无法读取。"}</div></main>;

  const { builder } = caseData;
  const draft = builder.draft;
  return (
    <main className="stack">
      <div className="toolbar">
        <div><Link href={`/workspaces/${workspaceId}/cases/new`}>← 返回上传</Link><h1>{caseData.title}</h1><span className="badge">{stateLabels[caseData.state]}</span></div>
        <button className="secondary" type="button" onClick={() => void loadCase(false)}>刷新</button>
      </div>
      <div className="card stack">
        <div><strong>文件：</strong>{caseData.attachment.original_name}（{caseData.attachment.size_bytes} bytes）</div>
        {caseData.task_description && <div><strong>任务说明：</strong>{caseData.task_description}</div>}
        {error && <div className="error">{error}</div>}
        {caseData.state === "parse_failed" && <div className="error">{builder.last_error?.message || "文件解析失败，请修正后重新上传。"}</div>}
        {caseData.state === "generating" && <p className="muted">AI 正在分析，请稍候。</p>}
        {caseData.state === "ai_failed" && (
          <div className="stack"><div className="error">{builder.last_error?.message || "AI 处理失败。"}</div>{builder.last_error?.retryable && <button disabled={busy} type="button" onClick={() => void retryGeneration()}>重试 AI</button>}</div>
        )}
        {caseData.state === "waiting_for_input" && builder.pending_question && (
          <form className="stack" onSubmit={submitAnswer}>
            <div><h2>请补充一个信息</h2><p>{builder.pending_question.text}</p><p className="muted">{builder.pending_question.reason}</p></div>
            <label>回答<textarea required minLength={1} maxLength={10000} value={answer} onChange={(event) => setAnswer(event.target.value)} /></label>
            <button disabled={busy} type="submit">{busy ? "提交中…" : "提交回答"}</button>
          </form>
        )}
        {caseData.state === "waiting_for_confirmation" && draft && (
          <form className="stack" onSubmit={submitConfirmation}>
            <div><h2>审阅并确认草案</h2><p className="muted">草案修订号：{builder.draft_revision}。下方 JSON 可直接修改。</p></div>
            <DraftSummary draft={draft} />
            <label>完整确认稿<textarea required value={draftText} onChange={(event) => setDraftText(event.target.value)} /></label>
            <button disabled={busy} type="submit">{busy ? "确认中…" : "确认并保存候选用例"}</button>
          </form>
        )}
        {caseData.state === "confirmed" && caseData.candidate_case && (
          <div className="stack"><div className="success">已保存候选用例：{caseData.candidate_case.id}</div><p className="muted">确认时间：{caseData.candidate_case.confirmed_at}</p><pre>{JSON.stringify(caseData.candidate_case.content, null, 2)}</pre></div>
        )}
      </div>
    </main>
  );
}

function DraftSummary({ draft }: { draft: DraftContent }) {
  return (
    <div className="grid">
      <article className="card"><h3>场景与目标</h3><p>{draft.scenario.summary}</p><p>{draft.task_goal}</p></article>
      <article className="card"><h3>事实</h3><ul>{(draft.facts ?? []).map((item) => <li key={item.id}>{item.text}<div className="evidence">证据：{(item.evidence_refs ?? []).map((ref) => ref.locator || ref.kind).join("、")}</div></li>)}</ul></article>
      <article className="card"><h3>老师判断</h3><ul>{(draft.teacher_judgments ?? []).length ? (draft.teacher_judgments ?? []).map((item) => <li key={item.id}>{item.text}</li>) : <li className="muted">暂无</li>}</ul></article>
      <article className="card"><h3>候选标准 / 未知</h3><ul>{(draft.proposed_standards ?? []).map((item) => <li key={item.id}>{item.text}</li>)}{(draft.unknowns ?? []).map((item) => <li key={item.id}>未知：{item.text}{item.blocking ? "（阻塞）" : ""}</li>)}</ul></article>
      <article className="card"><h3>维度</h3><ul>{draft.dimensions.map((item) => <li key={item.id}>{item.name}（{item.kind}）：{item.criterion}</li>)}</ul></article>
    </div>
  );
}
