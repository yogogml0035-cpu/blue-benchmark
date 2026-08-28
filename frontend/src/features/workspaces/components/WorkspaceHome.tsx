"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { ApiError } from "@/src/lib/api/client";
import { getCurrentUser, logout } from "@/src/features/auth/services/authService";
import { createWorkspace, listWorkspaces, Workspace } from "@/src/features/workspaces/services/workspaceService";

export function WorkspaceHome() {
  const router = useRouter();
  const [user, setUser] = useState<{ username: string } | null>(null);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const current = await getCurrentUser();
        if (!active) return;
        setUser(current.user);
        const result = await listWorkspaces();
        if (active) setWorkspaces(result.items);
      } catch (cause) {
        if (!active) return;
        if (cause instanceof ApiError && cause.status === 401) {
          router.replace("/login?returnTo=/workspaces");
          return;
        }
        setError(cause instanceof ApiError ? cause.message : "加载失败，请稍后重试。");
      } finally {
        if (active) setLoading(false);
      }
    }
    void load();
    return () => { active = false; };
  }, [router]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const result = await createWorkspace({ name, description: description || null });
      setWorkspaces((items) => [result.workspace, ...items]);
      setName("");
      setDescription("");
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "创建失败，请稍后重试。");
    } finally {
      setBusy(false);
    }
  }

  async function signOut() {
    await logout();
    router.replace("/login");
  }

  if (loading) return <main><p className="muted">正在加载当前账号…</p></main>;
  if (!user) return null;

  return (
    <main className="stack">
      <div className="toolbar">
        <div><h1>私有场景</h1><p className="muted">当前用户：{user.username}</p></div>
        <button className="secondary" type="button" onClick={() => void signOut()}>退出</button>
      </div>
      <section className="card stack">
        <h2>创建场景</h2>
        <form className="stack" onSubmit={submit}>
          <label>名称<input required maxLength={100} value={name} onChange={(event) => setName(event.target.value)} /></label>
          <label>说明（可选）<textarea maxLength={2000} value={description} onChange={(event) => setDescription(event.target.value)} /></label>
          {error && <div className="error">{error}</div>}
          <button disabled={busy} type="submit">{busy ? "创建中…" : "创建私有场景"}</button>
        </form>
      </section>
      <section className="stack">
        <h2>我的场景</h2>
        {workspaces.length === 0 ? <p className="muted">还没有场景。</p> : workspaces.map((workspace) => (
          <article className="card" key={workspace.id}>
            <div className="toolbar">
              <div><h3>{workspace.name}</h3><p className="muted">{workspace.description || "无说明"}</p></div>
              <span className="badge">{workspace.visibility}</span>
            </div>
            <Link href={`/workspaces/${workspace.id}/cases/new`}>上传案例 →</Link>
          </article>
        ))}
      </section>
    </main>
  );
}

