"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useEffect, useState } from "react";

import { DeskRail } from "@/src/components/shell/DeskRail";
import { Button, ButtonLink } from "@/src/components/ui/Button";
import { Field } from "@/src/components/ui/Field";
import { Note } from "@/src/components/ui/Note";
import { SkeletonLine } from "@/src/components/ui/Skeleton";
import { StatePanel } from "@/src/components/ui/StatePanel";
import { UserChip } from "@/src/features/auth/components/UserChip";
import { useSession } from "@/src/features/auth/hooks/useSession";
import { logout } from "@/src/features/auth/services/authService";
import { PREVIEW_WORKSPACES } from "@/src/features/workspaces/preview/fixtures";
import {
  createWorkspace,
  listWorkspaces,
  type Workspace,
} from "@/src/features/workspaces/services/workspaceService";
import { loginHref, toPageFault, type PageFault } from "@/src/lib/api/pageFault";
import { stamp } from "@/src/lib/format";
import { PREVIEW_ENABLED, PreviewBar, usePreviewState } from "@/src/lib/preview/preview";

import styles from "./ScenarioShelf.module.css";

type ListState =
  | { status: "loading" }
  | { status: "ready"; items: Workspace[] }
  | { status: "failed"; fault: PageFault };

export function ScenarioShelf() {
  const router = useRouter();
  const preview = usePreviewState();
  const session = useSession();

  const [list, setList] = useState<ListState>({ status: "loading" });
  const [composerOpen, setComposerOpen] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [createFault, setCreateFault] = useState<PageFault | null>(null);
  const [created, setCreated] = useState<Workspace | null>(null);

  const authenticated = session.status === "authenticated";

  useEffect(() => {
    if (preview || !authenticated) return;
    let active = true;
    setList({ status: "loading" });
    listWorkspaces()
      .then((result) => {
        if (active) setList({ status: "ready", items: result.items });
      })
      .catch((cause: unknown) => {
        if (active) setList({ status: "failed", fault: toPageFault(cause) });
      });
    return () => {
      active = false;
    };
  }, [authenticated, preview]);

  // 401 按合同跳登录并保留 returnTo；同屏仍渲染未授权说明，不留白屏。
  const unauthorized =
    preview === "unauthorized" || (!preview && session.status === "anonymous");
  useEffect(() => {
    if (preview) return;
    if (session.status === "anonymous") router.replace(loginHref("/workspaces"));
  }, [preview, router, session.status]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setCreateFault(null);
    try {
      const result = await createWorkspace({
        name: name.trim(),
        description: description.trim() || null,
      });
      setList((current) =>
        current.status === "ready"
          ? { status: "ready", items: [result.workspace, ...current.items] }
          : { status: "ready", items: [result.workspace] },
      );
      setCreated(result.workspace);
      setName("");
      setDescription("");
      setComposerOpen(false);
    } catch (cause) {
      setCreateFault(toPageFault(cause));
    } finally {
      setBusy(false);
    }
  }

  const rail = (
    <DeskRail
      right={
        authenticated || preview ? (
          <>
            <UserChip previewName={preview ? "teacher-a" : undefined} session={session} />
            <Button
              onClick={async () => {
                await logout().catch(() => undefined);
                router.replace("/login");
              }}
              size="sm"
              variant="quiet"
            >
              退出
            </Button>
          </>
        ) : undefined
      }
    />
  );

  if (unauthorized) {
    return (
      <>
        {rail}
        <PreviewBar states={["loading", "empty", "success", "error", "unauthorized"]} />
        <main className="page page-mid">
          <StatePanel
            actions={<ButtonLink href={loginHref("/workspaces")} variant="primary">去登录</ButtonLink>}
            code="401 · AUTH_REQUIRED"
            description="登录后查看你的场景。"
            title="需要登录才能查看场景"
            tone="locked"
          />
        </main>
      </>
    );
  }

  const failure: PageFault | null =
    preview === "error"
      ? { kind: "failed", code: "NETWORK_UNREACHABLE", message: "无法连接后端服务，请确认 FastAPI 已启动后重试。" }
      : !preview && session.status === "failed"
        ? session.fault
        : !preview && list.status === "failed"
          ? list.fault
          : null;

  if (failure) {
    return (
      <>
        {rail}
        <PreviewBar states={["loading", "empty", "success", "error", "unauthorized"]} />
        <main className="page page-mid">
          <StatePanel
            actions={
              <Button onClick={() => session.reload()} variant="primary">
                重新读取
              </Button>
            }
            code={failure.code}
            description={failure.message}
            title="场景列表读取失败"
            tone="fault"
          />
        </main>
      </>
    );
  }

  const loading =
    preview === "loading" || (!preview && (session.status === "loading" || list.status === "loading"));

  const items: Workspace[] =
    preview === "success"
      ? PREVIEW_WORKSPACES
      : preview === "empty"
        ? []
        : !preview && list.status === "ready"
          ? list.items
          : [];

  const empty = !loading && items.length === 0;
  // 还没有场景时，创建表单就是这一屏的焦点；有场景时它退回成一个可展开的动作。
  const composerVisible = empty || composerOpen;

  return (
    <>
      {rail}
      <PreviewBar states={["loading", "empty", "success", "error", "unauthorized"]} />
      <main className="page page-mid stack-lg">
        <div className="row-between">
          <h1 className="doc-title">场景</h1>
          {!empty && !loading && (
            <Button
              onClick={() => setComposerOpen((open) => !open)}
              variant={composerOpen ? "secondary" : "primary"}
            >
              {composerOpen ? "收起" : "新建场景"}
            </Button>
          )}
        </div>

        {created && (
          <Note tone="green" title={`已创建「${created.name}」`}>
            <span className="row" style={{ gap: "var(--s-3)" }}>
              {PREVIEW_ENABLED && <span className="mono">{created.id}</span>}
              <Link href={`/workspaces/${created.id}/cases/new`}>向这个场景上传真实案例 →</Link>
            </span>
          </Note>
        )}

        {composerVisible && (
          <section className="sheet enter">
            <div className="sheet-head">
              <h2 className="doc-title-sm">{empty ? "创建你的第一个场景" : "新建场景"}</h2>
              {empty && (
                <p className="secondary" style={{ marginTop: "var(--s-1)" }}>
                  用客户或任务命名，例如「客户 A 新闻稿」。
                </p>
              )}
            </div>
            <form className="sheet-pad stack" onSubmit={submit}>
              <Field hint="1–100 字" htmlFor="ws-name" label="名称">
                <input
                  className="control"
                  disabled={busy}
                  id="ws-name"
                  maxLength={100}
                  onChange={(event) => setName(event.target.value)}
                  placeholder="客户 A 新闻稿"
                  required
                  value={name}
                />
              </Field>
              <Field
                hint={`可留空 · ${description.length}/2000`}
                htmlFor="ws-desc"
                label="说明"
              >
                <textarea
                  className="control"
                  disabled={busy}
                  id="ws-desc"
                  maxLength={2000}
                  onChange={(event) => setDescription(event.target.value)}
                  placeholder="这个场景要保护什么能力、什么算通过。"
                  style={{ minHeight: 72 }}
                  value={description}
                />
              </Field>
              {createFault && (
                <Note code={createFault.code} title="场景没有创建" tone="fail">
                  {createFault.message}
                </Note>
              )}
              <div className="row">
                <Button
                  busy={busy}
                  busyLabel="正在创建…"
                  disabled={!name.trim()}
                  type="submit"
                  variant="primary"
                >
                  创建场景
                </Button>
                <span className="muted" style={{ fontSize: "var(--t-13)" }}>
                  仅自己可见
                </span>
              </div>
            </form>
          </section>
        )}

        <section className="stack">
          <div className="spread">
            <span className="section-label">我的场景</span>
            <span className="mono faint">{loading ? "…" : `${items.length} 个`}</span>
          </div>

          {loading ? (
            <div aria-busy="true" className={styles.shelf}>
              {[0, 1, 2].map((index) => (
                <div className={styles.card} key={index}>
                  <SkeletonLine height={18} width="58%" />
                  <SkeletonLine height={12} />
                  <SkeletonLine height={12} width="72%" />
                  <div className={styles.cardFoot}>
                    <SkeletonLine height={11} width="120px" />
                  </div>
                </div>
              ))}
            </div>
          ) : empty ? (
            <div className="inset stack-sm" style={{ padding: "var(--s-6)", textAlign: "center" }}>
              <p className="secondary">还没有场景，创建你的第一个业务场景。</p>
              {PREVIEW_ENABLED && <p className="mono faint">GET /api/workspaces → items: []</p>}
            </div>
          ) : (
            <div className={styles.shelf}>
              {items.map((workspace) => (
                <article className={`${styles.card} enter`} key={workspace.id}>
                  <div className={styles.cardHead}>
                    <h3 className={styles.cardName}>{workspace.name}</h3>
                    {workspace.description ? (
                      <p className={styles.cardNote}>{workspace.description}</p>
                    ) : (
                      <p className={styles.cardNote} style={{ color: "var(--text-3)" }}>
                        无说明
                      </p>
                    )}
                  </div>
                  <div className={styles.cardFoot}>
                    <span className="mono faint">
                      私有 · {stamp(workspace.created_at)}
                    </span>
                    <Link
                      className={styles.cardAction}
                      href={`/workspaces/${workspace.id}/cases/new`}
                    >
                      上传真实案例
                    </Link>
                  </div>
                </article>
              ))}
            </div>
          )}
        </section>
      </main>
    </>
  );
}
