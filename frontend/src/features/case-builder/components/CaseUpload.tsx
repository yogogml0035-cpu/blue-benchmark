"use client";

import { useRouter } from "next/navigation";
import { type DragEvent, type FormEvent, useEffect, useState } from "react";

import { DeskRail } from "@/src/components/shell/DeskRail";
import { Button, ButtonLink } from "@/src/components/ui/Button";
import { Field } from "@/src/components/ui/Field";
import { Cross } from "@/src/components/ui/Glyph";
import { Note } from "@/src/components/ui/Note";
import { SkeletonLine } from "@/src/components/ui/Skeleton";
import { StatePanel } from "@/src/components/ui/StatePanel";
import { UserChip } from "@/src/features/auth/components/UserChip";
import { useSession } from "@/src/features/auth/hooks/useSession";
import { AttachmentStrip } from "@/src/features/case-builder/components/AttachmentStrip";
import { createCase } from "@/src/features/case-builder/services/caseBuilderService";
import { PREVIEW_WORKSPACES } from "@/src/features/workspaces/preview/fixtures";
import {
  getWorkspace,
  type Workspace,
} from "@/src/features/workspaces/services/workspaceService";
import { loginHref, toPageFault, type PageFault } from "@/src/lib/api/pageFault";
import { PREVIEW_ENABLED, PreviewBar, usePreviewState } from "@/src/lib/preview/preview";

import styles from "./caseDetail.module.css";

const ACCEPTED = [".txt", ".md"];

function extensionOf(name: string) {
  const index = name.lastIndexOf(".");
  return index === -1 ? "" : name.slice(index).toLowerCase();
}

export function CaseUpload({ workspaceId }: { workspaceId: string }) {
  const router = useRouter();
  const preview = usePreviewState();
  const session = useSession();

  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [loadFault, setLoadFault] = useState<PageFault | null>(null);
  const [title, setTitle] = useState("");
  const [taskDescription, setTaskDescription] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState("");
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [submitFault, setSubmitFault] = useState<PageFault | null>(null);

  const authenticated = session.status === "authenticated";
  const returnTo = `/workspaces/${workspaceId}/cases/new`;

  useEffect(() => {
    if (preview || !authenticated) return;
    let active = true;
    setLoadFault(null);
    getWorkspace(workspaceId)
      .then((result) => {
        if (active) setWorkspace(result.workspace);
      })
      .catch((cause: unknown) => {
        if (active) setLoadFault(toPageFault(cause));
      });
    return () => {
      active = false;
    };
  }, [authenticated, preview, workspaceId]);

  useEffect(() => {
    if (preview) return;
    if (session.status === "anonymous") router.replace(loginHref(returnTo));
  }, [preview, returnTo, router, session.status]);

  function accept(candidate: File | null | undefined) {
    if (!candidate) return;
    if (!ACCEPTED.includes(extensionOf(candidate.name))) {
      setFile(null);
      setFileError(`只接受 ${ACCEPTED.join(" 或 ")} 文件，这一个是 ${extensionOf(candidate.name) || "未知类型"}。`);
      return;
    }
    setFileError("");
    setFile(candidate);
  }

  function onDrop(event: DragEvent<HTMLLabelElement>) {
    event.preventDefault();
    setDragging(false);
    accept(event.dataTransfer.files?.[0]);
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file) {
      setFileError("请先选择一个 .txt 或 .md 材料。");
      return;
    }
    setBusy(true);
    setSubmitFault(null);
    try {
      const result = await createCase(workspaceId, {
        title: title.trim(),
        taskDescription: taskDescription.trim() || undefined,
        file,
      });
      router.push(`/workspaces/${workspaceId}/cases/${result.case.id}`);
    } catch (cause) {
      setSubmitFault(toPageFault(cause));
      setBusy(false);
    }
  }

  const shownWorkspace = preview ? PREVIEW_WORKSPACES[0] : workspace;
  const rail = (
    <DeskRail
      crumbs={[
        { label: shownWorkspace?.name ?? "场景", href: "/workspaces" },
        { label: "上传真实案例" },
      ]}
      right={
        <UserChip previewName={preview ? "teacher-a" : undefined} session={session} />
      }
    />
  );
  const previewBar = (
    <PreviewBar
      states={["loading", "empty", "success", "error", "unauthorized", "forbidden", "not_found"]}
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
            description="上传前需要登录。"
            title="需要登录才能向这个场景上传"
            tone="locked"
          />
        </main>
      </>
    );
  }

  const fault: PageFault | null =
    preview === "forbidden"
      ? { kind: "forbidden", code: "FORBIDDEN", message: "你无权访问这个场景。" }
      : preview === "not_found"
        ? { kind: "not_found", code: "RESOURCE_NOT_FOUND", message: "场景不存在。" }
        : preview === "error"
          ? { kind: "failed", code: "NETWORK_UNREACHABLE", message: "无法连接后端服务，请确认 FastAPI 已启动后重试。" }
          : !preview && session.status === "failed"
            ? session.fault
            : !preview
              ? loadFault
              : null;

  if (fault && fault.kind !== "conflict") {
    const copy =
      fault.kind === "forbidden"
        ? { title: "这个场景不属于当前账号", body: "场景只对所有者可见。" }
        : fault.kind === "not_found"
          ? { title: "场景不存在", body: "查不到这个场景。" }
          : { title: "读取场景失败", body: fault.message };
    return (
      <>
        {rail}
        {previewBar}
        <main className="page page-mid">
          <StatePanel
            actions={
              <ButtonLink href="/workspaces" variant="primary">
                回到场景
              </ButtonLink>
            }
            code={`${fault.kind === "forbidden" ? "403" : fault.kind === "not_found" ? "404" : "500"} · ${fault.code}`}
            description={copy.body}
            title={copy.title}
            tone="fault"
          />
        </main>
      </>
    );
  }

  const loading =
    preview === "loading" || (!preview && (session.status === "loading" || !workspace));

  return (
    <>
      {rail}
      {previewBar}
      <main className="page page-mid stack-lg">
        <div className="stack-sm">
          <h1 className="doc-title">上传一份真实案例</h1>
          {loading ? (
            <SkeletonLine height={14} width="58%" />
          ) : (
            <p className="secondary">上传到「{shownWorkspace?.name}」。</p>
          )}
        </div>

        {preview === "success" && (
          <Note tone="green" title="已建立真实案例并解析完成">
            <span className="row" style={{ gap: "var(--s-3)" }}>
              <span className="mono">state · ready_for_ai</span>
              <span className="mono faint">201 CaseDetail</span>
            </span>
          </Note>
        )}

        <div className={styles.intake}>
          <section className="sheet">
            <form className="sheet-pad stack" onSubmit={submit}>
              <Field hint="1–200 字" htmlFor="case-title" label="案例标题">
                {loading ? (
                  <SkeletonLine height={40} />
                ) : (
                  <input
                    className="control"
                    disabled={busy}
                    id="case-title"
                    maxLength={200}
                    onChange={(event) => setTitle(event.target.value)}
                    placeholder="客户 A 春季新品新闻稿终稿"
                    required
                    value={title}
                  />
                )}
              </Field>

              <Field
                hint={`可留空 · ${taskDescription.length}/10000`}
                htmlFor="case-task"
                label="任务说明"
              >
                {loading ? (
                  <SkeletonLine height={84} />
                ) : (
                  <textarea
                    className="control"
                    disabled={busy}
                    id="case-task"
                    maxLength={10000}
                    onChange={(event) => setTaskDescription(event.target.value)}
                    placeholder="这项真实任务的约束：Brief 要求、字数、禁用项。"
                    value={taskDescription}
                  />
                )}
              </Field>

              <div className="field">
                <span className="field-label">
                  <span>材料</span>
                  <span className="field-hint">恰好一个 .txt 或 .md</span>
                </span>
                {loading ? (
                  <SkeletonLine height={120} />
                ) : file ? (
                  <AttachmentStrip
                    attachment={{
                      original_name: file.name,
                      media_type: file.type || "text/plain",
                      size_bytes: file.size,
                    }}
                    onRemove={
                      <Button
                        aria-label="移除已选材料"
                        className="btn-icon"
                        disabled={busy}
                        onClick={() => setFile(null)}
                        variant="quiet"
                      >
                        <Cross size={13} />
                      </Button>
                    }
                  />
                ) : (
                  <label
                    className={`${styles.drop}${dragging ? ` ${styles.dropOver}` : ""}${
                      fileError ? ` ${styles.dropInvalid}` : ""
                    }`}
                    onDragLeave={() => setDragging(false)}
                    onDragOver={(event) => {
                      event.preventDefault();
                      setDragging(true);
                    }}
                    onDrop={onDrop}
                  >
                    <input
                      accept=".txt,.md,text/plain,text/markdown"
                      className={styles.fileInput}
                      disabled={busy}
                      onChange={(event) => accept(event.target.files?.[0])}
                      type="file"
                    />
                    <span style={{ fontWeight: 550 }}>
                      {dragging ? "松手即上传" : "把材料拖到这里，或点击选择"}
                    </span>
                    <span className="mono faint">.txt · .md · UTF-8</span>
                  </label>
                )}
                {fileError && (
                  <p className="field-error">
                    <span>{fileError}</span>
                  </p>
                )}
              </div>

              {submitFault && (
                <Note
                  code={submitFault.code}
                  title={
                    submitFault.code === "UNSUPPORTED_FILE_TYPE"
                      ? "服务端不接受这个文件类型"
                      : submitFault.code === "FILE_TOO_LARGE"
                        ? "文件超过大小限制"
                        : "案例没有建立"
                  }
                  tone="fail"
                >
                  {submitFault.message}
                  {submitFault.code === "FILE_TOO_LARGE" && " 请拆分后重新上传。"}
                </Note>
              )}

              <div className="row">
                <Button
                  busy={busy}
                  busyLabel="正在上传并解析…"
                  disabled={loading || !title.trim() || !file}
                  size="lg"
                  type="submit"
                  variant="primary"
                >
                  上传并解析
                </Button>
                <ButtonLink href="/workspaces" variant="quiet">
                  取消
                </ButtonLink>
              </div>
            </form>
          </section>

          <aside className="sheet stack" style={{ padding: "var(--s-5)", gap: "var(--s-4)" }}>
            <div className="stack-sm">
              <span className="section-label">上传须知</span>
              <ul className="stack-sm secondary" style={{ fontSize: "var(--t-13)" }}>
                <li>· 一个案例收一个材料，解析为空不会进入整理。</li>
                <li>· 解析失败不重试，修正材料后重新上传。</li>
              </ul>
            </div>
            {PREVIEW_ENABLED && (
              <>
                <hr className="hair" />
                <div className="stack-sm">
                  <span className="section-label">Stub 分支（仅开发构建）</span>
                  <p className="secondary" style={{ fontSize: "var(--t-13)" }}>
                    当前后端是内存 Stub。在文件内容里写入下面的标记即可复现对应分支：
                  </p>
                  <ul className="stack-sm">
                    <li className="mono">默认 → 先提问一次</li>
                    <li className="mono">[stub:waiting_for_confirmation]</li>
                    <li className="mono">[stub:ai_failed]</li>
                    <li className="mono">空文件 → parse_failed</li>
                  </ul>
                </div>
              </>
            )}
          </aside>
        </div>
      </main>
    </>
  );
}
