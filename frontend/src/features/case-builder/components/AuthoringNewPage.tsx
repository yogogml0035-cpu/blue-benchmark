"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { type FormEvent, useEffect, useRef, useState } from "react";

import { DeskRail } from "@/src/components/shell/DeskRail";
import { AutoTextarea } from "@/src/components/ui/AutoTextarea";
import { Button, ButtonLink } from "@/src/components/ui/Button";
import { Field } from "@/src/components/ui/Field";
import { Note } from "@/src/components/ui/Note";
import { SkeletonLine } from "@/src/components/ui/Skeleton";
import { StatePanel } from "@/src/components/ui/StatePanel";
import { UserChip } from "@/src/features/auth/components/UserChip";
import { useSession } from "@/src/features/auth/hooks/useSession";
import { getUploadBatch } from "@/src/features/workspaces/services/studioService";
import type { UploadBatch } from "@/src/features/workspaces/services/studioService";
import { createAuthoringConversation } from "@/src/features/case-builder/services/authoringService";
import { loginHref, toPageFault, type PageFault } from "@/src/lib/api/pageFault";
import { PreviewBar, usePreviewState } from "@/src/lib/preview/preview";

import styles from "./authoring.module.css";

function commandId(prefix: string) {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

export function AuthoringNewPage({ workspaceId }: { workspaceId: string }) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const preview = usePreviewState();
  const session = useSession();
  const reloadSession = session.reload;
  const batchId = searchParams.get("batch");
  const returnTo = `/workspaces/${workspaceId}/authoring/new${batchId ? `?batch=${encodeURIComponent(batchId)}` : ""}`;
  const [batch, setBatch] = useState<UploadBatch | null>(null);
  const [batchFault, setBatchFault] = useState<PageFault | null>(null);
  const [title, setTitle] = useState("");
  const [taskInstruction, setTaskInstruction] = useState("");
  const [message, setMessage] = useState("");
  const [referenceAnswer, setReferenceAnswer] = useState("");
  const [busy, setBusy] = useState(false);
  const [fault, setFault] = useState<PageFault | null>(null);
  const createCommand = useRef<{ fingerprint: string; id: string } | null>(null);
  const routeGeneration = useRef(0);

  useEffect(() => {
    routeGeneration.current += 1;
  }, [batchId, preview, workspaceId]);

  useEffect(() => {
    // A client-side navigation can reuse this component for another batch or
    // workspace.  Clear the old local form before the new batch snapshot
    // arrives so its task text cannot be submitted with the new evidence.
    setBatch(null);
    setBatchFault(null);
    setTitle("");
    setTaskInstruction("");
    setMessage("");
    setReferenceAnswer("");
    setFault(null);
    setBusy(false);
    createCommand.current = null;
  }, [batchId, workspaceId]);

  useEffect(() => {
    if (preview || !batchId || session.status !== "authenticated") return;
    let active = true;
    setBatch(null);
    setBatchFault(null);
    getUploadBatch(workspaceId, batchId)
      .then((result) => {
        if (!active) return;
        setBatch(result.batch);
        setTitle((current) => current || result.batch.title);
        setTaskInstruction((current) => current || result.batch.task_description || "");
      })
      .catch((cause: unknown) => {
        if (!active) return;
        const pageFault = toPageFault(cause);
        setBatchFault(pageFault);
        if (pageFault.kind === "unauthorized") reloadSession();
      });
    return () => {
      active = false;
    };
  }, [batchId, preview, reloadSession, session.status, workspaceId]);

  useEffect(() => {
    if (preview) return;
    if (session.status === "anonymous") router.replace(loginHref(returnTo));
  }, [preview, returnTo, router, session.status]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!title.trim() || (!taskInstruction.trim() && !message.trim()) || busy) return;
    const requestRouteGeneration = routeGeneration.current;
    setBusy(true);
    setFault(null);
    const input = {
      title: title.trim(),
      upload_batch_id: batchId || null,
      task_instruction: taskInstruction.trim() || null,
      message: message.trim() || null,
      reference_answer_text: referenceAnswer.trim() || null,
      source_file_ids: [],
    };
    const fingerprint = JSON.stringify(input);
    if (createCommand.current?.fingerprint !== fingerprint) {
      createCommand.current = { fingerprint, id: commandId("authoring-create") };
    }
    try {
      const result = await createAuthoringConversation(workspaceId, {
        command_id: createCommand.current.id,
        ...input,
      });
      if (requestRouteGeneration !== routeGeneration.current) return;
      router.replace(`/workspaces/${workspaceId}/authoring/${result.conversation.id}`);
    } catch (cause: unknown) {
      if (requestRouteGeneration !== routeGeneration.current) return;
      const pageFault = toPageFault(cause);
      setFault(pageFault);
      if (pageFault.kind === "unauthorized") reloadSession();
    } finally {
      if (requestRouteGeneration === routeGeneration.current) setBusy(false);
    }
  }

  const rail = (
    <DeskRail
      crumbs={[
        { label: "场景", href: "/workspaces" },
        { label: "开始建题" },
      ]}
      right={<UserChip previewName={preview ? "teacher-a" : undefined} session={session} />}
    />
  );
  const previewBar = <PreviewBar states={["loading", "success", "error", "unauthorized"]} />;

  if (!preview && session.status === "loading") {
    return (
      <>
        {rail}
        {previewBar}
        <main className="page page-mid stack-lg">
          <SkeletonLine height={28} width="42%" />
          <section aria-busy="true" className="sheet sheet-pad stack-lg">
            <SkeletonLine height={18} width="65%" />
            <SkeletonLine height={42} />
            <SkeletonLine height={120} />
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

  if (preview === "unauthorized" || (!preview && session.status === "anonymous")) {
    return (
      <>
        {rail}
        {previewBar}
        <main className="page page-mid">
          <StatePanel
            actions={<ButtonLink href={loginHref(returnTo)} variant="primary">去登录</ButtonLink>}
            description="登录后才能开始建题。"
            title="需要登录"
            tone="locked"
          />
        </main>
      </>
    );
  }

  if (batchFault) {
    return (
      <>
        {rail}
        {previewBar}
        <main className="page page-mid">
          <StatePanel
            actions={<ButtonLink href={`/workspaces/${workspaceId}`} variant="primary">回到工作台</ButtonLink>}
            code={batchFault.code}
            description={batchFault.message}
            title="资料批次读取失败"
            tone="fault"
          />
        </main>
      </>
    );
  }

  const loadingBatch = Boolean(batchId && !preview && session.status === "authenticated" && !batch);

  return (
    <>
      {rail}
      {previewBar}
      <main className="page page-mid stack-lg">
        <header className={`${styles.intro} stack-sm`}>
          <span className="section-label">形成一条题</span>
          <h1 className="doc-title">从真实交付开始</h1>
          <p className="secondary">
            先把任务和资料交给 AI 整理，再由你确认题目边界、题目输入和标准答案。
          </p>
        </header>

        {loadingBatch ? (
          <section aria-busy="true" className="sheet sheet-pad stack-lg">
            <SkeletonLine height={18} width="45%" />
            <SkeletonLine height={42} />
            <SkeletonLine height={120} />
          </section>
        ) : (
          <form className="sheet sheet-pad stack-lg" onSubmit={submit}>
            {batch && (
              <div className="inset stack-sm" data-testid="authoring-source-summary">
                <span className="section-label">已绑定资料</span>
                <p>{batch.title}</p>
                <p className="secondary">{batch.files.length} 个文件会作为候选题的证据范围。</p>
              </div>
            )}
            <Field hint="1–200 字" htmlFor="authoring-title" label="会话标题">
              <input
                className="control"
                disabled={busy}
                id="authoring-title"
                maxLength={200}
                onChange={(event) => setTitle(event.target.value)}
                placeholder="客户 A 新闻稿题"
                required
                value={title}
              />
            </Field>
            <Field hint="交付目标、受众和硬约束" htmlFor="authoring-instruction" label="任务说明">
              <AutoTextarea
                className="control"
                disabled={busy}
                id="authoring-instruction"
                maxLength={10_000}
                minRows={4}
                onChange={(event) => setTaskInstruction(event.target.value)}
                placeholder="例如：根据资料形成一份事实准确、可直接供媒体使用的新闻稿。"
                value={taskInstruction}
              />
            </Field>
            <Field hint="可留空；创建后仍可继续补充" htmlFor="authoring-message" label="第一句话">
              <AutoTextarea
                className="control"
                disabled={busy}
                id="authoring-message"
                maxLength={50_000}
                minRows={3}
                onChange={(event) => setMessage(event.target.value)}
                placeholder="告诉 AI 你最希望它先厘清什么。"
                value={message}
              />
            </Field>
            <Field hint="只有老师明确认可的终版才会进入这里" htmlFor="authoring-reference" label="已有标准答案（可选）">
              <AutoTextarea
                className="control"
                disabled={busy}
                id="authoring-reference"
                maxLength={50_000}
                minRows={3}
                onChange={(event) => setReferenceAnswer(event.target.value)}
                placeholder="没有就留空，稍后由会话向你追问。"
                value={referenceAnswer}
              />
            </Field>
            {fault && (
              <Note code={fault.code} title="会话没有创建" tone="fail">
                {fault.message}
              </Note>
            )}
            <div className="row">
              <Button
                busy={busy}
                busyLabel="正在创建…"
                disabled={!title.trim() || (!taskInstruction.trim() && !message.trim())}
                size="lg"
                type="submit"
                variant="primary"
              >
                开始建题
              </Button>
              <ButtonLink href={`/workspaces/${workspaceId}`} variant="quiet">取消</ButtonLink>
            </div>
          </form>
        )}

        <aside className={`${styles.guidance} inset stack-sm`}>
          <span className="section-label">这条会话会做什么</span>
          <p className="secondary">AI 只整理候选，不替你确认任务、标准答案或发布结果。</p>
          <p className="secondary">刷新或断线后，页面以服务端已保存的会话快照继续。</p>
        </aside>
      </main>
    </>
  );
}
