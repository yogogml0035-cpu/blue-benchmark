"use client";

import { useRouter } from "next/navigation";
import { type ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Button, ButtonLink } from "@/src/components/ui/Button";
import { Note } from "@/src/components/ui/Note";
import { StatePanel } from "@/src/components/ui/StatePanel";
import { useSession } from "@/src/features/auth/hooks/useSession";
import { UserChip } from "@/src/features/auth/components/UserChip";
import { DeskRail } from "@/src/components/shell/DeskRail";
import {
  getStudioProjection,
  type StudioProjection,
  type VersionSummary,
  listVersions,
  updateFileDisposition,
  retryBatchAnalysis,
  getUploadBatch,
} from "@/src/features/workspaces/services/studioService";
import { loginHref, toPageFault, type PageFault } from "@/src/lib/api/pageFault";
import { stamp } from "@/src/lib/format";
import { PreviewBar, usePreviewState } from "@/src/lib/preview/preview";
import { PREVIEW_STUDIO_SUCCESS } from "@/src/features/workspaces/preview/studioFixtures";
import { listQuestions, type QuestionListResponse } from "@/src/features/case-builder/services/authoringService";

import styles from "./studio.module.css";

export type StudioSection = "current" | "questions" | "versions";

type Load =
  | { status: "loading" }
  | { status: "ready"; projection: StudioProjection }
  | { status: "failed"; fault: PageFault };

const SECTION_LABEL: Record<StudioSection, string> = {
  current: "当前",
  questions: "题",
  versions: "版本",
};

const SECTION_ORDER: StudioSection[] = ["current", "questions", "versions"];

export function StudioShell({
  workspaceId,
  workspaceName,
  section,
  children,
  batchId,
  onRefresh,
  busy,
}: {
  workspaceId: string;
  workspaceName?: string | null;
  section: StudioSection;
  children: ReactNode;
  batchId?: string | null;
  onRefresh?: () => void;
  busy?: boolean;
}) {
  const router = useRouter();
  const preview = usePreviewState();
  const session = useSession();
  const [menuOpen, setMenuOpen] = useState(false);
  const menuButtonRef = useRef<HTMLButtonElement>(null);
  const firstMenuItemRef = useRef<HTMLButtonElement>(null);
  const returnTo = `/workspaces/${workspaceId}`;

  useEffect(() => {
    if (preview) return;
    if (session.status === "anonymous") router.replace(loginHref(returnTo));
  }, [preview, returnTo, router, session.status]);

  useEffect(() => {
    if (!menuOpen) return;
    firstMenuItemRef.current?.focus();
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key !== "Escape") return;
      setMenuOpen(false);
      menuButtonRef.current?.focus();
    }
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [menuOpen]);

  const rail = (
    <DeskRail
      crumbs={[
        { label: "场景", href: "/workspaces" },
        { label: workspaceName ?? "…" },
      ]}
      right={
        <>
          <Button
            aria-label="切换工作区导航"
            aria-expanded={menuOpen}
            className="btn-quiet btn-sm"
            onClick={() => setMenuOpen((open) => !open)}
            buttonRef={menuButtonRef}
            variant="quiet"
          >
            {SECTION_LABEL[section]}
            <span aria-hidden="true" style={{ marginLeft: 4 }}>▾</span>
          </Button>
          <UserChip previewName={preview ? "teacher-a" : undefined} session={session} />
        </>
      }
    />
  );

  return (
    <>
      {rail}
      <PreviewBar
        states={[
          "loading",
          "empty",
          "success",
          "error",
          "unauthorized",
          "forbidden",
          "not_found",
          "question",
          "review",
        ]}
      />
      {menuOpen && (
        <div aria-modal="true" className={styles.mobileNav} role="dialog" aria-label="场景导航">
          <div className={styles.mobileNavPanel}>
            {SECTION_ORDER.map((key, index) => (
              <button
                aria-current={section === key ? "page" : undefined}
                className={styles.mobileNavItem}
                data-active={section === key}
                key={key}
                onClick={() => {
                  setMenuOpen(false);
                  router.push(`/workspaces/${workspaceId}?section=${key}${batchId ? `&batch=${batchId}` : ""}`);
                }}
                ref={index === 0 ? firstMenuItemRef : undefined}
                type="button"
              >
                {SECTION_LABEL[key]}
              </button>
            ))}
          </div>
        </div>
      )}
      <div className={styles.layout}>
        <aside className={styles.sideNav}>
          <nav aria-label="场景工作台">
            {SECTION_ORDER.map((key) => (
              <button
                aria-current={section === key ? "page" : undefined}
                className={styles.sideNavItem}
                data-active={section === key}
                key={key}
                onClick={() =>
                  router.push(`/workspaces/${workspaceId}?section=${key}${batchId ? `&batch=${batchId}` : ""}`)
                }
                type="button"
              >
                {SECTION_LABEL[key]}
              </button>
            ))}
          </nav>
          {onRefresh && (
            <div className={styles.sideNavFoot}>
              <Button
                busy={busy}
                busyLabel="读取中…"
                onClick={onRefresh}
                size="sm"
                variant="quiet"
              >
                刷新
              </Button>
            </div>
          )}
        </aside>
        <main className={styles.canvas}>
          {children}
        </main>
      </div>
    </>
  );
}

/** 场景工作台数据层：加载 StudioProjection。 */
export function useStudioData(workspaceId: string, batchId?: string | null, enabled = true) {
  const preview = usePreviewState();
  const session = useSession();
  const reloadSession = session.reload;
  const [load, setLoad] = useState<Load>({ status: "loading" });
  const [refreshing, setRefreshing] = useState(false);
  const requestGeneration = useRef(0);

  const read = useCallback(
    async (silent: boolean) => {
      const generation = ++requestGeneration.current;
      if (silent) setRefreshing(true);
      try {
        const projection = await getStudioProjection(workspaceId, batchId ?? null);
        if (generation !== requestGeneration.current) return null;
        setLoad({ status: "ready", projection });
        return projection;
      } catch (cause) {
        if (generation !== requestGeneration.current) return null;
        const fault = toPageFault(cause);
        if (fault.kind === "unauthorized" || fault.kind === "forbidden" || fault.kind === "not_found") {
          setLoad({ status: "failed", fault });
          if (fault.kind === "unauthorized") reloadSession();
        } else {
          setLoad((current) =>
            current.status === "ready" && silent ? current : { status: "failed", fault },
          );
        }
        return null;
      } finally {
        if (generation === requestGeneration.current) setRefreshing(false);
      }
    },
    [batchId, reloadSession, workspaceId],
  );

  useEffect(() => {
    return () => {
      requestGeneration.current += 1;
    };
  }, [batchId, preview, session.status, workspaceId]);

  useEffect(() => {
    if (!enabled) {
      setLoad({ status: "ready", projection: PREVIEW_STUDIO_SUCCESS });
      return;
    }
    if (preview) {
      setLoad({ status: "ready", projection: PREVIEW_STUDIO_SUCCESS });
      return;
    }
    if (session.status !== "authenticated") return;
    setLoad({ status: "loading" });
    void read(false);
  }, [enabled, preview, session.status, read]);

  useEffect(() => {
    if (preview || load.status !== "ready") return;
    const operation = load.projection.active_operation;
    if (!operation || (operation.status !== "queued" && operation.status !== "running")) return;
    const timer = setTimeout(() => void read(true), 1500);
    return () => clearTimeout(timer);
  }, [load, preview, read]);

  return { load, read, refreshing, preview, session };
}

function operationLabel(kind: string): string {
  const map: Record<string, string> = {
    batch_analysis: "资料整理",
    cocreation_start: "题目边界整理",
    cocreation_resume: "题目边界整理",
    cocreation_reproject: "题目边界整理",
    coverage_review: "覆盖审查",
    freeze_package: "历史版本形成",
  };
  return map[kind] ?? kind;
}

function ReceiptNote({ receipt }: { receipt: StudioProjection["latest_receipt"] }) {
  if (!receipt) return null;
  if (receipt.status === "failed") {
    return (
      <Note tone="fail" title="处理失败">
        {receipt.message}
      </Note>
    );
  }
  if (receipt.status === "superseded") {
    return (
      <Note tone="amber" title="已过期">
        {receipt.message}
      </Note>
    );
  }
  return (
    <Note tone="green" title="处理完成">
      {receipt.message}
    </Note>
  );
}

/** 当前区：上传、资料整理、角色确认、分组确认。 */
export function CurrentSection({
  workspaceId,
  projection,
  onRefresh,
  refreshing,
}: {
  workspaceId: string;
  projection: StudioProjection;
  onRefresh: () => void;
  refreshing: boolean;
}) {
  return (
    <div className="stack-lg">
      <div className="stack-sm">
        <h1 className="doc-title">当前</h1>
        <p className="secondary">
          这里是场景工作台。上传资料、确认任务边界、回答 AI 的问题，一步一步形成标准。
        </p>
      </div>
      <CurrentWorkspace workspaceId={workspaceId} projection={projection} onRefresh={onRefresh} refreshing={refreshing} />
    </div>
  );
}

function CurrentWorkspace({
  workspaceId,
  projection,
  onRefresh,
  refreshing,
}: {
  workspaceId: string;
  projection: StudioProjection;
  onRefresh: () => void;
  refreshing: boolean;
}) {
  const { next_action, active_operation, latest_receipt, blocking_issues } = projection;

  if (active_operation) {
    return (
      <div className="stack">
        <section className="sheet sheet-pad stack" aria-live="polite">
          <div className="row" style={{ gap: "var(--s-2)" }}>
            <span className="state state-active">
              <span className="dot pulse-dot" />
              正在处理
            </span>
            <span className="secondary">{operationLabel(active_operation.kind)}</span>
          </div>
          <p className="secondary">
            {active_operation.status === "queued"
              ? "已排队，等待后台开始处理。"
              : active_operation.status === "running"
                ? "正在处理，完成后会自动更新。"
                : active_operation.status === "failed"
                  ? "处理失败，可以重试。"
                  : "正在整理结果，马上更新。"}
          </p>
          {(active_operation.status === "failed" || active_operation.status === "projection_pending") && (
            <RetryOperation workspaceId={workspaceId} projection={projection} onRefresh={onRefresh} />
          )}
        </section>
        {latest_receipt && <ReceiptNote receipt={latest_receipt} />}
      </div>
    );
  }

  if (latest_receipt) {
    return (
      <div className="stack">
        <ReceiptNote receipt={latest_receipt} />
        {next_action.kind === "confirm_file_roles" && (
          <FileRoleConfirmation workspaceId={workspaceId} projection={projection} onRefresh={onRefresh} />
        )}
        {next_action.kind === "retry_processing" && (
          <section className="sheet sheet-pad stack">
            <h2 className="doc-title-sm">整理失败</h2>
            <p className="secondary">后台整理资料时遇到问题，可以重试。</p>
            <RetryOperation workspaceId={workspaceId} projection={projection} onRefresh={onRefresh} />
          </section>
        )}
        {next_action.kind === "wait_for_processing" && (
          <section className="sheet sheet-pad stack" aria-live="polite">
            <p className="secondary">正在等待后台处理完成。</p>
          </section>
        )}
        {next_action.kind === "none" && (
          <NextStepPanel workspaceId={workspaceId} projection={projection} onRefresh={onRefresh} />
        )}
      </div>
    );
  }

  if (blocking_issues && blocking_issues.length > 0) {
    return (
      <section className="sheet sheet-pad stack">
        <Note tone="amber" title="有阻塞项">
          <ul className="stack-sm">
            {blocking_issues.map((issue) => (
              <li key={issue}>{issue}</li>
            ))}
          </ul>
        </Note>
      </section>
    );
  }

  if (next_action.kind === "confirm_file_roles") {
    return <FileRoleConfirmation workspaceId={workspaceId} projection={projection} onRefresh={onRefresh} />;
  }

  if (next_action.kind === "retry_processing") {
    return (
      <section className="sheet sheet-pad stack">
        <h2 className="doc-title-sm">整理失败</h2>
        <p className="secondary">后台整理资料时遇到问题，可以重试。</p>
        <RetryOperation workspaceId={workspaceId} projection={projection} onRefresh={onRefresh} />
      </section>
    );
  }

  if (next_action.kind === "wait_for_processing") {
    return (
      <section className="sheet sheet-pad stack" aria-live="polite">
        <p className="secondary">正在等待后台处理完成。</p>
      </section>
    );
  }

  return (
    <section className="sheet sheet-pad stack">
      <h2 className="doc-title-sm">上传资料</h2>
      <p className="secondary">上传真实交付材料，AI 会帮你分析可独立验收的题目边界。</p>
      <div className="row">
        <ButtonLink href={`/workspaces/${workspaceId}/upload`} variant="primary">
          上传资料
        </ButtonLink>
        <ButtonLink href={`/workspaces/${workspaceId}/authoring/new`} variant="quiet">
          直接手动建题
        </ButtonLink>
      </div>
    </section>
  );
}

/** 失败重试：调用后端 retry 端点重新排队，而不是只刷新。 */
function RetryOperation({
  workspaceId,
  projection,
  onRefresh,
}: {
  workspaceId: string;
  projection: StudioProjection;
  onRefresh: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<PageFault | null>(null);

  return (
    <div className="stack-sm">
      {error && (
        <Note tone="fail" title="重试失败">
          {error.message}
        </Note>
      )}
      <div className="row">
        <Button
          busy={busy}
          busyLabel="正在重试…"
          onClick={async () => {
            if (!projection.batch_id) return;
            setBusy(true);
            setError(null);
            try {
              const { batch } = await getUploadBatch(workspaceId, projection.batch_id);
              await retryBatchAnalysis(workspaceId, projection.batch_id, {
                commandId: `retry-${projection.batch_id}-${Date.now()}`,
                batchRevision: batch.revision,
              });
              onRefresh();
            } catch (cause) {
              setError(toPageFault(cause));
            } finally {
              setBusy(false);
            }
          }}
          variant="primary"
        >
          重试整理
        </Button>
      </div>
    </div>
  );
}

/** 资料已确认后的下一步：进入题目形成。 */
function NextStepPanel({
  workspaceId,
  projection,
  onRefresh,
}: {
  workspaceId: string;
  projection: StudioProjection;
  onRefresh: () => void;
}) {
  const router = useRouter();
  return (
    <section className="sheet sheet-pad stack">
      <h2 className="doc-title-sm">{projection.next_action.label}</h2>
      <p className="secondary">资料用途已确认。现在可以从真实交付形成一条独立题目。</p>
      <div className="row">
        <Button
          onClick={() =>
            router.push(`/workspaces/${workspaceId}/authoring/new${projection.batch_id ? `?batch=${projection.batch_id}` : ""}`)
          }
          variant="primary"
        >
          开始形成题目
        </Button>
        <Button onClick={onRefresh} variant="quiet">
          刷新
        </Button>
      </div>
    </section>
  );
}

type FileRole = "brief" | "runtime" | "judge" | "provenance" | "unknown";

const ROLE_LABEL: Record<FileRole, string> = {
  brief: "任务说明",
  runtime: "运行材料",
  judge: "评分依据",
  provenance: "形成记录",
  unknown: "未确定",
};

/** 角色决定默认可见性：任务说明和运行材料交给被测 Skill，评分依据只给评分，形成记录只留档。 */
const ROLE_VISIBILITY: Record<FileRole, "runtime" | "judge" | "provenance" | "unconfirmed"> = {
  brief: "runtime",
  runtime: "runtime",
  judge: "judge",
  provenance: "provenance",
  unknown: "unconfirmed",
};

function FileRoleConfirmation({
  workspaceId,
  projection,
  onRefresh,
}: {
  workspaceId: string;
  projection: StudioProjection;
  onRefresh: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<PageFault | null>(null);
  const files = useMemo(() => projection.files ?? [], [projection.files]);
  const [roles, setRoles] = useState<Record<string, FileRole>>(() =>
    Object.fromEntries(files.map((file) => [file.id, file.role as FileRole])),
  );
  const [required, setRequired] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(files.map((file) => [file.id, file.required])),
  );

  async function submit() {
    if (!projection.batch_id) return;
    setBusy(true);
    setError(null);
    try {
      // 每次 disposition 都会推进 batch revision，逐个提交并跟随最新 revision
      let revision = (await getUploadBatch(workspaceId, projection.batch_id)).batch.revision;
      for (const file of files) {
        const role = roles[file.id] ?? "unknown";
        await updateFileDisposition(workspaceId, projection.batch_id, file.id, {
          role,
          required: required[file.id] ?? false,
          ignored: false,
          visibility: ROLE_VISIBILITY[role],
          batch_revision: revision,
        });
        revision += 1;
      }
      onRefresh();
    } catch (cause) {
      setError(toPageFault(cause));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="sheet sheet-pad stack">
      <h2 className="doc-title-sm">确认资料用途</h2>
      <p className="secondary">
        请确认每个文件的角色。任务说明和运行材料会交给被测 Skill，评分依据只用于评分，形成记录只留档。
      </p>
      <div className="stack">
        {files.map((file) => (
          <div className="row-between" key={file.id} style={{ padding: "var(--s-3) 0", borderBottom: "1px solid var(--hair-soft)" }}>
            <div className="stack-sm" style={{ flex: 1, minWidth: 0 }}>
              <span style={{ fontWeight: 550, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {file.original_name}
              </span>
              <span className="mono faint" style={{ fontSize: "var(--t-12)" }}>
                {file.media_type} · {file.size_bytes} B
              </span>
            </div>
            <div className="row" style={{ gap: "var(--s-2)" }}>
              <select
                aria-label={`${file.original_name} 角色`}
                className="control"
                disabled={busy}
                onChange={(event) =>
                  setRoles((current) => ({ ...current, [file.id]: event.target.value as FileRole }))
                }
                style={{ width: "auto", padding: "6px var(--s-2)" }}
                value={roles[file.id] ?? "unknown"}
              >
                {(Object.keys(ROLE_LABEL) as FileRole[]).map((role) => (
                  <option key={role} value={role}>
                    {ROLE_LABEL[role]}
                  </option>
                ))}
              </select>
              <label className="row" style={{ gap: "var(--s-1)", fontSize: "var(--t-13)" }}>
                <input
                  checked={required[file.id] ?? false}
                  disabled={busy}
                  onChange={(event) =>
                    setRequired((current) => ({ ...current, [file.id]: event.target.checked }))
                  }
                  type="checkbox"
                />
                必需
              </label>
            </div>
          </div>
        ))}
      </div>
      {error && (
        <Note tone="fail" title="确认失败">
          {error.message}
        </Note>
      )}
      <div className="row">
        <Button busy={busy} busyLabel="正在确认…" onClick={submit} variant="primary">
          确认资料用途
        </Button>
      </div>
    </section>
  );
}

/** 题区：只展示题目生命周期，不再编排任务包或手动冻结。 */
export function QuestionsSection({ workspaceId }: { workspaceId: string }) {
  const preview = usePreviewState();
  const [load, setLoad] = useState<{ status: "loading" | "ready" | "failed"; data?: QuestionListResponse }>({ status: "loading" });

  const read = useCallback(() => {
    if (preview) {
      setLoad({ status: "ready", data: { workspace_id: workspaceId, questions: [] } });
      return;
    }
    setLoad({ status: "loading" });
    void listQuestions(workspaceId)
      .then((data) => setLoad({ status: "ready", data }))
      .catch(() => setLoad({ status: "failed" }));
  }, [preview, workspaceId]);

  useEffect(() => {
    read();
  }, [read]);

  if (load.status === "loading") {
    return <div className="stack-lg"><h1 className="doc-title">题</h1><section aria-busy="true" className="sheet sheet-pad stack"><div className="skeleton" style={{ height: 20, width: "60%" }} /><div className="skeleton" style={{ height: 72 }} /></section></div>;
  }
  if (load.status === "failed") {
    return <div className="stack-lg"><h1 className="doc-title">题</h1><StatePanel actions={<Button onClick={read} variant="primary">重新读取</Button>} description="题目列表暂时无法读取。" title="题目读取失败" tone="fault" /></div>;
  }
  const questions = load.data?.questions ?? [];
  return (
    <div className="stack-lg">
      <div className="stack-sm"><h1 className="doc-title">题</h1><p className="secondary">每道题都是一条独立的业务标准；发布后自动进入当前评测集。</p></div>
      {questions.length === 0 ? (
        <section className="sheet sheet-pad stack"><h2 className="doc-title-sm">还没有题</h2><p className="secondary">先从一次真实交付开始形成题目输入、标准答案和评分规则。</p><ButtonLink href={`/workspaces/${workspaceId}/authoring/new`} variant="primary">开始建题</ButtonLink></section>
      ) : (
        <div className="stack">
          {questions.map((question) => {
            const deleted = question.lifecycle_status === "deleted";
            const disabled = question.lifecycle_status === "disabled";
            return (
              <article className="sheet sheet-pad stack" data-testid={`question-${question.id}`} key={question.id}>
                <div className="row-between"><div className="stack-sm"><span className="section-label">{question.lifecycle_status === "active" ? "当前题" : disabled ? "已停用" : deleted ? "已删除" : "题稿"}</span><h2 className="doc-title-sm">{question.title}</h2></div><span className={deleted ? "state state-red" : disabled ? "state state-amber" : question.lifecycle_status === "active" ? "state state-green" : "state state-neutral"}><span className="dot" />{question.lifecycle_status === "active" ? "已发布" : disabled ? "停用" : deleted ? "删除" : "待确认"}</span></div>
                <p className="secondary">{question.summary}</p>
                <div className="row"><span className="mono faint">{question.bad_samples?.length ?? 0} 个坏样本</span><span className="mono faint">{question.input.materials?.length ?? 0} 份材料</span></div>
                <div className="row"><ButtonLink href={`/workspaces/${workspaceId}/authoring/${question.conversation_id}`} variant="primary">{deleted ? "查看历史" : disabled ? "查看并恢复" : question.lifecycle_status === "active" ? "管理题目" : "继续审阅"}</ButtonLink>{question.active_revision_id && !disabled && !deleted && <ButtonLink href={`/workspaces/${workspaceId}/question-revisions/${question.active_revision_id}/submissions/new`} variant="quiet">提交待评结果</ButtonLink>}</div>
              </article>
            );
          })}
        </div>
      )}
    </div>
  );
}

/** 新主流程的版本区：只读历史，发布动作已经自动进入当前评测集。 */
export function AutomaticVersionsSection({ workspaceId }: { workspaceId: string }) {
  const preview = usePreviewState();
  const [versions, setVersions] = useState<VersionSummary[]>([]);
  const [state, setState] = useState<"loading" | "ready" | "failed">("loading");

  const load = useCallback(() => {
    if (preview) {
      setVersions([]);
      setState("ready");
      return;
    }
    setState("loading");
    void listVersions(workspaceId)
      .then((result) => {
        setVersions(result.versions);
        setState("ready");
      })
      .catch(() => setState("failed"));
  }, [preview, workspaceId]);

  useEffect(() => {
    load();
  }, [load]);

  if (state === "loading") {
    return <div className="stack-lg"><h1 className="doc-title">版本</h1><section aria-busy="true" className="sheet sheet-pad stack"><div className="skeleton" style={{ height: 20, width: "60%" }} /></section></div>;
  }
  if (state === "failed") {
    return <div className="stack-lg"><h1 className="doc-title">版本</h1><StatePanel actions={<Button onClick={load} variant="primary">重新读取</Button>} description="历史版本暂时无法读取。" title="版本读取失败" tone="fault" /></div>;
  }
  return (
    <div className="stack-lg">
      <div className="stack-sm">
        <h1 className="doc-title">版本</h1>
        <p className="secondary">每次发布、停用或恢复都会自动留下不可变历史；这里不再编排下一版。</p>
      </div>
      <section className="stack" aria-label="历史版本">
        <div className="spread"><span className="section-label">不可变历史</span><span className="mono faint">{versions.length} 个</span></div>
        {versions.length === 0 ? (
          <div className="inset" style={{ padding: "var(--s-6)", textAlign: "center" }}><p className="secondary">发布第一道题后，这里会出现版本历史。</p></div>
        ) : versions.map((version) => (
          <div className="sheet sheet-pad-sm row-between" key={version.id}>
            <div className="stack-sm"><span style={{ fontWeight: 600 }}>版本 {version.version_number}</span><span className="secondary">自动形成 · {stamp(version.frozen_at)}</span></div>
            <div className="row"><ButtonLink href={`/workspaces/${workspaceId}/versions/${version.id}`} size="sm" variant="quiet">查看</ButtonLink><Button onClick={() => window.open(`/api/workspaces/${workspaceId}/evaluation-sets/versions/${version.id}/download`, "_blank")} size="sm" variant="quiet">下载</Button></div>
          </div>
        ))}
      </section>
    </div>
  );
}
