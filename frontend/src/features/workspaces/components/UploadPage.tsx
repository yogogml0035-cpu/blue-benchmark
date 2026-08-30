"use client";

import { useRouter } from "next/navigation";
import { type FormEvent, useEffect, useState } from "react";

import { DeskRail } from "@/src/components/shell/DeskRail";
import { Button, ButtonLink } from "@/src/components/ui/Button";
import { Field } from "@/src/components/ui/Field";
import { Cross } from "@/src/components/ui/Glyph";
import { Note } from "@/src/components/ui/Note";
import { SkeletonLine } from "@/src/components/ui/Skeleton";
import { StatePanel } from "@/src/components/ui/StatePanel";
import { AutoTextarea } from "@/src/components/ui/AutoTextarea";
import { Sheet } from "@/src/components/ui/Sheet";
import { UserChip } from "@/src/features/auth/components/UserChip";
import { useSession } from "@/src/features/auth/hooks/useSession";
import { AttachmentStrip } from "@/src/features/case-builder/components/AttachmentStrip";
import { createUploadBatch } from "@/src/features/workspaces/services/studioService";
import { loginHref, toPageFault, type PageFault } from "@/src/lib/api/pageFault";
import { PREVIEW_ENABLED, PreviewBar, usePreviewState } from "@/src/lib/preview/preview";

const ACCEPTED = [".txt", ".md", ".json", ".jsonl", ".zip"];

function extensionOf(name: string) {
  const index = name.lastIndexOf(".");
  return index === -1 ? "" : name.slice(index).toLowerCase();
}

export function UploadPage({ workspaceId }: { workspaceId: string }) {
  const router = useRouter();
  const preview = usePreviewState();
  const session = useSession();

  const [title, setTitle] = useState("");
  const [taskDescription, setTaskDescription] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [fileError, setFileError] = useState("");
  const [busy, setBusy] = useState(false);
  const [submitFault, setSubmitFault] = useState<PageFault | null>(null);
  const [showHelp, setShowHelp] = useState(false);

  const authenticated = session.status === "authenticated";
  const returnTo = `/workspaces/${workspaceId}`;

  useEffect(() => {
    if (preview) return;
    if (session.status === "anonymous") router.replace(loginHref(returnTo));
  }, [preview, returnTo, router, session.status]);

  function accept(candidate: File | null | undefined) {
    if (!candidate) return;
    if (!ACCEPTED.includes(extensionOf(candidate.name))) {
      setFileError(`只接受 ${ACCEPTED.join("、")} 文件，这一个是 ${extensionOf(candidate.name) || "未知类型"}。`);
      return;
    }
    setFileError("");
    setFiles((current) => [...current, candidate]);
  }

  function removeFile(index: number) {
    setFiles((current) => current.filter((_, i) => i !== index));
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (files.length === 0) {
      setFileError("请至少选择一个文件。");
      return;
    }
    setBusy(true);
    setSubmitFault(null);
    try {
      const result = await createUploadBatch(workspaceId, {
        title: title.trim(),
        taskDescription: taskDescription.trim() || null,
        files,
      });
      router.push(`/workspaces/${workspaceId}?batch=${result.batch.id}`);
    } catch (cause) {
      setSubmitFault(toPageFault(cause));
      setBusy(false);
    }
  }

  const rail = (
    <DeskRail
      crumbs={[
        { label: "场景", href: "/workspaces" },
        { label: "上传资料" },
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
          : null;

  if (fault) {
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

  const loading = preview === "loading";

  return (
    <>
      {rail}
      {previewBar}
      <main className="page page-mid stack-lg">
        <div className="stack-sm">
          <h1 className="doc-title">上传资料</h1>
          <p className="secondary">
            上传真实交付材料，AI 会帮你分析任务边界和场景标准。
          </p>
        </div>

        <div className="stack-lg">
          <section className="sheet">
            <form className="sheet-pad stack" onSubmit={submit}>
              <Field hint="1–200 字" htmlFor="batch-title" label="批次标题">
                {loading ? (
                  <SkeletonLine height={40} />
                ) : (
                  <input
                    className="control"
                    disabled={busy}
                    id="batch-title"
                    maxLength={200}
                    onChange={(event) => setTitle(event.target.value)}
                    placeholder="客户 A 春季新品资料"
                    required
                    value={title}
                  />
                )}
              </Field>

              <Field
                hint={`可留空 · ${taskDescription.length}/10000`}
                htmlFor="batch-task"
                label="任务说明"
              >
                {loading ? (
                  <SkeletonLine height={84} />
                ) : (
                  <textarea
                    className="control"
                    disabled={busy}
                    id="batch-task"
                    maxLength={10000}
                    onChange={(event) => setTaskDescription(event.target.value)}
                    placeholder="这项真实任务的约束：Brief 要求、字数、禁用项。"
                    value={taskDescription}
                  />
                )}
              </Field>

              <div className="field">
                <span className="field-label">
                  <span>资料文件</span>
                  <span className="field-hint">{ACCEPTED.join(" · ")}</span>
                </span>
                {loading ? (
                  <SkeletonLine height={120} />
                ) : (
                  <>
                    <label
                      className={`drop-zone${fileError ? " drop-zone-error" : ""}`}
                      onDragLeave={(event) => event.preventDefault()}
                      onDragOver={(event) => event.preventDefault()}
                      onDrop={(event) => {
                        event.preventDefault();
                        accept(event.dataTransfer.files?.[0]);
                      }}
                    >
                      <input
                        accept={ACCEPTED.join(",")}
                        className="file-input"
                        disabled={busy}
                        multiple
                        onChange={(event) => {
                          const list = event.target.files;
                          if (!list) return;
                          for (const file of Array.from(list)) {
                            accept(file);
                          }
                        }}
                        type="file"
                      />
                      <span style={{ fontWeight: 550 }}>
                        {files.length > 0 ? `已选择 ${files.length} 个文件` : "把文件拖到这里，或点击选择"}
                      </span>
                      <span className="mono faint">.txt · .md · .json · .jsonl · .zip</span>
                    </label>
                    {files.length > 0 && (
                      <div className="stack-sm" style={{ marginTop: "var(--s-3)" }}>
                        {files.map((file, index) => (
                          <AttachmentStrip
                            attachment={{
                              original_name: file.name,
                              media_type: file.type || "application/octet-stream",
                              size_bytes: file.size,
                            }}
                            key={`${file.name}-${index}`}
                            onRemove={
                              <Button
                                aria-label={`移除 ${file.name}`}
                                className="btn-icon"
                                disabled={busy}
                                onClick={() => removeFile(index)}
                                variant="quiet"
                              >
                                <Cross size={13} />
                              </Button>
                            }
                          />
                        ))}
                      </div>
                    )}
                    {fileError && (
                      <p className="field-error">
                        <span>{fileError}</span>
                      </p>
                    )}
                  </>
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
                        : "上传失败"
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
                  busyLabel="正在上传…"
                  disabled={loading || !title.trim() || files.length === 0}
                  size="lg"
                  type="submit"
                  variant="primary"
                >
                  上传并开始分析
                </Button>
                <ButtonLink href={`/workspaces/${workspaceId}`} variant="quiet">
                  取消
                </ButtonLink>
              </div>
            </form>
          </section>

          <aside className="sheet stack" style={{ padding: "var(--s-5)", gap: "var(--s-4)" }}>
            <div className="stack-sm">
              <span className="section-label">上传须知</span>
              <ul className="stack-sm secondary" style={{ fontSize: "var(--t-13)" }}>
                <li>· 支持多文件上传，建议一次上传一个完整任务的所有材料。</li>
                <li>· ZIP 文件会被安全解包，内部仍按白名单检查。</li>
                <li>· 上传后 AI 会在后台分析，不需要等待。</li>
              </ul>
            </div>
            {PREVIEW_ENABLED && (
              <>
                <hr className="hair" />
                <div className="stack-sm">
                  <span className="section-label">开发提示</span>
                  <p className="secondary" style={{ fontSize: "var(--t-13)" }}>
                    上传成功后进入场景工作台的「当前」页，查看资料整理进度。
                  </p>
                </div>
              </>
            )}
          </aside>
        </div>
      </main>
    </>
  );
}
