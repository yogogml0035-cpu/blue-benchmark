"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";

import { ApiError } from "@/src/lib/api/client";
import { createCase } from "@/src/features/case-builder/services/caseBuilderService";

export function NewCaseForm({ workspaceId }: { workspaceId: string }) {
  const router = useRouter();
  const [title, setTitle] = useState("");
  const [taskDescription, setTaskDescription] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file) {
      setError("请选择一个 .txt 或 .md 文件。");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const result = await createCase(workspaceId, { title, taskDescription, file });
      router.push(`/workspaces/${workspaceId}/cases/${result.case.id}`);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "上传失败，请稍后重试。");
      setBusy(false);
    }
  }

  return (
    <main>
      <section className="card stack">
        <div className="toolbar"><div><h1>上传案例</h1><p className="muted">上传后详情页会自动调用一次 Stub 草案生成。</p></div><Link href="/workspaces">返回场景</Link></div>
        <form className="stack" onSubmit={submit}>
          <label>标题<input required maxLength={200} value={title} onChange={(event) => setTitle(event.target.value)} /></label>
          <label>任务说明（可选）<textarea maxLength={10000} value={taskDescription} onChange={(event) => setTaskDescription(event.target.value)} /></label>
          <label>TXT/Markdown 文件<input required accept=".txt,.md,text/plain,text/markdown" type="file" onChange={(event) => setFile(event.target.files?.[0] ?? null)} /></label>
          <div className="muted">Stub 分支：默认会追问一次；在文件内容中加入 <code>[stub:waiting_for_confirmation]</code> 可直接进入待确认；加入 <code>[stub:ai_failed]</code> 可复现 AI 失败后重试。</div>
          {error && <div className="error">{error}</div>}
          <button disabled={busy} type="submit">{busy ? "正在上传并解析…" : "上传案例"}</button>
        </form>
      </section>
    </main>
  );
}

