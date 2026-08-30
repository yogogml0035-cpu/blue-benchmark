"use client";

import { useRouter } from "next/navigation";
import { type ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Button, ButtonLink } from "@/src/components/ui/Button";
import { Sheet } from "@/src/components/ui/Sheet";
import { Note } from "@/src/components/ui/Note";
import { useSession } from "@/src/features/auth/hooks/useSession";
import { UserChip } from "@/src/features/auth/components/UserChip";
import { DeskRail } from "@/src/components/shell/DeskRail";
import {
  getStudioProjection,
  type StudioProjection,
  type TaskPackageSummary,
  type WorkingSetDraftView,
  type DraftMemberView,
  type VersionSummary,
  listTaskPackages,
  listVersions,
  getTaskPackage,
  createWorkingDraft,
  getWorkingDraft,
  requestCoverageReview,
  confirmCoverage,
  freezeDraft,
  updateFileDisposition,
  confirmTaskGroups,
  retryBatchAnalysis,
  getUploadBatch,
} from "@/src/features/workspaces/services/studioService";
import { loginHref, toPageFault, type PageFault } from "@/src/lib/api/pageFault";
import { stamp } from "@/src/lib/format";
import { PREVIEW_ENABLED, PreviewBar, usePreviewState, type PreviewState } from "@/src/lib/preview/preview";
import { PREVIEW_STUDIO_SUCCESS } from "@/src/features/workspaces/preview/studioFixtures";

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
  const returnTo = `/workspaces/${workspaceId}`;

  useEffect(() => {
    if (preview) return;
    if (session.status === "anonymous") router.replace(loginHref(returnTo));
  }, [preview, returnTo, router, session.status]);

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
        <div className={styles.mobileNav} role="dialog" aria-label="场景导航">
          <div className={styles.mobileNavPanel}>
            {SECTION_ORDER.map((key) => (
              <button
                aria-current={section === key ? "page" : undefined}
                className={styles.mobileNavItem}
                data-active={section === key}
                key={key}
                onClick={() => {
                  setMenuOpen(false);
                  router.push(`/workspaces/${workspaceId}?section=${key}${batchId ? `&batch=${batchId}` : ""}`);
                }}
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
export function useStudioData(workspaceId: string, batchId?: string | null) {
  const preview = usePreviewState();
  const session = useSession();
  const [load, setLoad] = useState<Load>({ status: "loading" });
  const [refreshing, setRefreshing] = useState(false);

  const read = useCallback(
    async (silent: boolean) => {
      if (silent) setRefreshing(true);
      try {
        const projection = await getStudioProjection(workspaceId, batchId ?? null);
        setLoad({ status: "ready", projection });
        return projection;
      } catch (cause) {
        const fault = toPageFault(cause);
        setLoad((current) =>
          current.status === "ready" && silent ? current : { status: "failed", fault },
        );
        return null;
      } finally {
        setRefreshing(false);
      }
    },
    [workspaceId, batchId],
  );

  useEffect(() => {
    if (preview) {
      setLoad({ status: "ready", projection: PREVIEW_STUDIO_SUCCESS });
      return;
    }
    if (session.status !== "authenticated") return;
    setLoad({ status: "loading" });
    void read(false);
  }, [preview, session.status, read]);

  return { load, read, refreshing, preview, session };
}

function operationLabel(kind: string): string {
  const map: Record<string, string> = {
    batch_analysis: "资料整理",
    cocreation_start: "场景标准整理",
    cocreation_resume: "场景标准整理",
    cocreation_reproject: "场景标准整理",
    coverage_review: "覆盖审查",
    freeze_package: "版本冻结",
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
          {active_operation.status === "failed" && (
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
      <p className="secondary">上传真实交付材料，AI 会帮你分析任务边界和场景标准。</p>
      <div className="row">
        <ButtonLink href={`/workspaces/${workspaceId}/upload`} variant="primary">
          上传资料
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

/** 资料已确认后的下一步：确认任务分组。 */
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
      <p className="secondary">资料用途已确认。去「题」确认任务分组，开始共创。</p>
      <div className="row">
        <Button
          onClick={() =>
            router.push(`/workspaces/${workspaceId}?section=questions${projection.batch_id ? `&batch=${projection.batch_id}` : ""}`)
          }
          variant="primary"
        >
          去确认任务分组
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

/** 题区：任务包列表与共创状态。 */
export function QuestionsSection({
  workspaceId,
  projection,
  onRefresh,
}: {
  workspaceId: string;
  projection: StudioProjection;
  onRefresh: () => void;
}) {
  const [packages, setPackages] = useState<TaskPackageSummary[]>([]);
  const [batchRevision, setBatchRevision] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<PageFault | null>(null);

  const loadPackages = useCallback(() => {
    if (!projection.batch_id) {
      setLoading(false);
      return;
    }
    setLoadError(null);
    listTaskPackages(workspaceId, projection.batch_id)
      .then((result) => {
        setPackages(result.task_packages);
        setBatchRevision(result.batch_revision);
      })
      .catch((cause) => setLoadError(toPageFault(cause)))
      .finally(() => setLoading(false));
  }, [workspaceId, projection.batch_id]);

  useEffect(() => {
    setLoading(true);
    loadPackages();
  }, [loadPackages]);

  if (loading) {
    return (
      <div className="stack-lg">
        <h1 className="doc-title">题</h1>
        <div className="sheet sheet-pad stack" aria-busy="true">
          <div className="skeleton" style={{ height: 20, width: "60%" }} />
          <div className="skeleton" style={{ height: 14, width: "80%" }} />
        </div>
      </div>
    );
  }

  if (loadError) {
    return (
      <div className="stack-lg">
        <h1 className="doc-title">题</h1>
        <Note tone="fail" title="任务列表读取失败">
          {loadError.message}
        </Note>
        <div className="row">
          <Button onClick={loadPackages} variant="primary">
            重试
          </Button>
        </div>
      </div>
    );
  }

  if (packages.length === 0) {
    return (
      <div className="stack-lg">
        <h1 className="doc-title">题</h1>
        <div className="sheet sheet-pad stack">
          <p className="secondary">还没有确认的任务。先在「当前」完成资料上传和任务分组确认。</p>
        </div>
      </div>
    );
  }

  const proposed = packages.filter((pkg) => pkg.status === "proposed");
  const confirmed = packages.filter((pkg) => pkg.status !== "proposed");

  return (
    <div className="stack-lg">
      <div className="stack-sm">
        <h1 className="doc-title">题</h1>
        <p className="secondary">
          确认的任务会在这里形成题稿。每一道题都来自真实交付的沉淀。
        </p>
      </div>
      {proposed.length > 0 && projection.batch_id && (
        <TaskGroupConfirmation
          batchId={projection.batch_id}
          batchRevision={batchRevision}
          onConfirmed={() => {
            loadPackages();
            onRefresh();
          }}
          packages={proposed}
          workspaceId={workspaceId}
        />
      )}
      <div className="stack">
        {confirmed.map((pkg) => (
          <TaskPackageCard key={pkg.id} workspaceId={workspaceId} pkg={pkg} onRefresh={onRefresh} />
        ))}
      </div>
    </div>
  );
}

/** 任务分组确认：AI 提议的分组，老师确认后任务包进入已定稿流程。 */
function TaskGroupConfirmation({
  workspaceId,
  batchId,
  batchRevision,
  packages,
  onConfirmed,
}: {
  workspaceId: string;
  batchId: string;
  batchRevision: number;
  packages: TaskPackageSummary[];
  onConfirmed: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<PageFault | null>(null);

  return (
    <section className="sheet sheet-pad stack">
      <div className="stack-sm">
        <span className="section-label">待确认</span>
        <h2 className="doc-title-sm">确认任务分组</h2>
        <p className="secondary">
          AI 从资料中提议了 {packages.length} 组任务。确认后开始逐题共创。
        </p>
      </div>
      <div className="stack-sm">
        {packages.map((pkg) => (
          <div className="inset" key={pkg.id} style={{ padding: "var(--s-3)" }}>
            <p style={{ fontWeight: 550 }}>{pkg.title}</p>
            <p className="mono faint" style={{ fontSize: "var(--t-12)" }}>
              {pkg.evidence_file_ids.length} 个资料文件
            </p>
          </div>
        ))}
      </div>
      {error && (
        <Note tone="fail" title="确认失败">
          {error.message}
        </Note>
      )}
      <div className="row">
        <Button
          busy={busy}
          busyLabel="正在确认…"
          onClick={async () => {
            setBusy(true);
            setError(null);
            try {
              await confirmTaskGroups(workspaceId, batchId, {
                commandId: `confirm-groups-${batchId}-${Date.now()}`,
                batchRevision,
                groups: packages.map((pkg) => ({
                  title: pkg.title,
                  summary: "老师确认的真实任务分组。",
                  evidence_file_ids: pkg.evidence_file_ids,
                  initialization_only: pkg.initialization_only ?? false,
                })),
              });
              onConfirmed();
            } catch (cause) {
              setError(toPageFault(cause));
            } finally {
              setBusy(false);
            }
          }}
          variant="primary"
        >
          确认分组
        </Button>
      </div>
    </section>
  );
}

function TaskPackageCard({
  workspaceId,
  pkg,
  onRefresh,
}: {
  workspaceId: string;
  pkg: TaskPackageSummary;
  onRefresh: () => void;
}) {
  const router = useRouter();

  return (
    <article className="sheet sheet-pad stack">
      <div className="spread">
        <h2 className="doc-title-sm">{pkg.title}</h2>
        <span className={`state ${pkg.status === "confirmed" ? "state-green" : pkg.status === "proposed" ? "state-amber" : "state-neutral"}`}>
          <span className="dot" />
          {pkg.status === "confirmed" ? "已定稿" : pkg.status === "proposed" ? "待确认" : "已替换"}
        </span>
      </div>
      {pkg.attempts && pkg.attempts.length > 0 && (
        <p className="secondary">
          {pkg.attempts.length} 次尝试
        </p>
      )}
      <div className="row">
        <Button
          onClick={() => router.push(`/workspaces/${workspaceId}/questions/${pkg.id}`)}
          variant="primary"
        >
          {pkg.has_judgment_package ? "继续共创" : "开始共创"}
        </Button>
        <Button variant="quiet" onClick={onRefresh}>
          刷新
        </Button>
      </div>
    </article>
  );
}

/** 版本区：下一版草稿与历史版本。 */
export function VersionsSection({
  workspaceId,
  projection,
  onRefresh,
}: {
  workspaceId: string;
  projection: StudioProjection;
  onRefresh: () => void;
}) {
  const [versions, setVersions] = useState<VersionSummary[]>([]);
  const [draft, setDraft] = useState<WorkingSetDraftView | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<PageFault | null>(null);

  const load = useCallback(async () => {
    setLoadError(null);
    try {
      const versionList = await listVersions(workspaceId);
      setVersions(versionList.versions);
      // 后端不支持按 workspace 查当前草稿；先尝试创建（幂等），失败则说明已有草稿但无法直接定位，
      // 此时历史版本列表已足以让用户继续工作。
      const draftResult = await createWorkingDraft(workspaceId, {
        commandId: `draft-get-or-create-${Date.now()}`,
      }).catch(() => null);
      setDraft(draftResult?.draft ?? null);
    } catch (cause) {
      setLoadError(toPageFault(cause));
    } finally {
      setLoading(false);
    }
  }, [workspaceId]);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) {
    return (
      <div className="stack-lg">
        <h1 className="doc-title">版本</h1>
        <div className="sheet sheet-pad stack" aria-busy="true">
          <div className="skeleton" style={{ height: 20, width: "60%" }} />
        </div>
      </div>
    );
  }

  if (loadError) {
    return (
      <div className="stack-lg">
        <h1 className="doc-title">版本</h1>
        <Note tone="fail" title="版本读取失败">
          {loadError.message}
        </Note>
        <div className="row">
          <Button onClick={() => void load()} variant="primary">
            重试
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="stack-lg">
      <div className="stack-sm">
        <h1 className="doc-title">版本</h1>
        <p className="secondary">
          下一版正在形成中，冻结后成为不可变的历史版本。
        </p>
      </div>

      <DraftPanel
        draft={draft}
        onRefresh={() => {
          void load();
          onRefresh();
        }}
        workspaceId={workspaceId}
      />

      <section className="stack">
        <div className="spread">
          <span className="section-label">历史版本</span>
          <span className="mono faint">{versions.length} 个</span>
        </div>
        {versions.length === 0 ? (
          <div className="inset" style={{ padding: "var(--s-6)", textAlign: "center" }}>
            <p className="secondary">还没有冻结的版本。</p>
          </div>
        ) : (
          <div className="stack">
            {versions.map((version) => (
              <div className="sheet sheet-pad-sm row-between" key={version.id}>
                <div className="stack-sm">
                  <span style={{ fontWeight: 600 }}>版本 {version.version_number}</span>
                  <span className="mono faint">{stamp(version.frozen_at)}</span>
                </div>
                <div className="row">
                  <ButtonLink
                    href={`/workspaces/${workspaceId}/versions/${version.id}`}
                    size="sm"
                    variant="quiet"
                  >
                    查看
                  </ButtonLink>
                  <Button
                    onClick={() => window.open(`/api/workspaces/${workspaceId}/evaluation-sets/versions/${version.id}/download`, "_blank")}
                    size="sm"
                    variant="quiet"
                  >
                    下载
                  </Button>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

/** 草稿成员标签：显示任务包标题而非裸 ID。 */
function MemberLabel({ member, workspaceId }: { member: DraftMemberView; workspaceId: string }) {
  const [title, setTitle] = useState<string | null>(null);
  useEffect(() => {
    getTaskPackage(workspaceId, member.task_package_id)
      .then((result) => setTitle(result.task_package.title))
      .catch(() => setTitle(null));
  }, [workspaceId, member.task_package_id]);
  return (
    <span style={{ fontSize: "var(--t-13)" }}>
      {title ?? member.task_package_id.slice(0, 8) + "…"}
      {member.review_status === "review_required" && (
        <span className="state state-amber" style={{ marginLeft: "var(--s-2)", fontSize: "var(--t-12)" }}>
          <span className="dot" />
          待复核
        </span>
      )}
    </span>
  );
}

/** 下一版工作草稿：成员管理、覆盖审查、冻结。 */
function DraftPanel({
  workspaceId,
  draft,
  onRefresh,
}: {
  workspaceId: string;
  draft: WorkingSetDraftView | null;
  onRefresh: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<PageFault | null>(null);
  const [note, setNote] = useState("");

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await action();
      onRefresh();
    } catch (cause) {
      setError(toPageFault(cause));
    } finally {
      setBusy(false);
    }
  }

  if (!draft) {
    return (
      <section className="sheet sheet-pad stack">
        <div className="spread">
          <h2 className="doc-title-sm">下一版</h2>
          <span className="state state-neutral">
            <span className="dot" />
            未开始
          </span>
        </div>
        <p className="secondary">确认任务后开始组建下一版评测集。</p>
        <div className="row">
          <Button
            busy={busy}
            busyLabel="正在创建…"
            onClick={() => run(() => createWorkingDraft(workspaceId, { commandId: `draft-${Date.now()}` }))}
            variant="primary"
          >
            创建工作草稿
          </Button>
        </div>
        {error && <Note tone="fail" title="创建失败">{error.message}</Note>}
      </section>
    );
  }

  const included = (draft.members ?? []).filter((m) => m.status === "included");
  const coverage = draft.coverage;
  const discarded = draft.status === "discarded";

  return (
    <section className="sheet sheet-pad stack">
      <div className="spread">
        <h2 className="doc-title-sm">下一版</h2>
        <span className={`state ${discarded ? "state-neutral" : "state-active"}`}>
          <span className="dot" />
          {discarded ? "已废弃" : "工作草稿"}
        </span>
      </div>

      <div className="stack-sm">
        <span className="section-label">已收任务</span>
        {included.length === 0 ? (
          <p className="secondary">还没有收进任务。去「题」完成共创后任务会自动加入。</p>
        ) : (
          <ul className="stack-sm">
            {included.map((member) => (
              <li key={member.id}>
                <MemberLabel member={member} workspaceId={workspaceId} />
              </li>
            ))}
          </ul>
        )}
      </div>

      {coverage && (
        <div className="stack-sm">
          <span className="section-label">覆盖审查</span>
          <div className="inset stack-sm" style={{ padding: "var(--s-3)" }}>
            {(coverage.warnings ?? []).length > 0 && (
              <ul className="stack-sm">
                {(coverage.warnings ?? []).map((w) => (
                  <li key={w} className="secondary" style={{ fontSize: "var(--t-13)" }}>⚠ {w}</li>
                ))}
              </ul>
            )}
            {(coverage.blank_areas ?? []).length > 0 && (
              <ul className="stack-sm">
                {(coverage.blank_areas ?? []).map((area) => (
                  <li key={area} className="secondary" style={{ fontSize: "var(--t-13)" }}>空白：{area}</li>
                ))}
              </ul>
            )}
            {(coverage.warnings ?? []).length === 0 && (coverage.blank_areas ?? []).length === 0 && (
              <p className="secondary" style={{ fontSize: "var(--t-13)" }}>覆盖良好，没有发现明显缺口。</p>
            )}
            {!coverage.confirmed_at && (
              <div className="stack-sm" style={{ marginTop: "var(--s-2)" }}>
                <input
                  aria-label="覆盖风险确认说明"
                  className="control"
                  onChange={(event) => setNote(event.target.value)}
                  placeholder="确认说明（必填）：为什么接受当前覆盖范围"
                  value={note}
                />
                <Button
                  busy={busy}
                  disabled={!note.trim()}
                  onClick={() =>
                    run(() =>
                      confirmCoverage(workspaceId, draft.id, {
                        commandId: `cov-confirm-${draft.id}-${Date.now()}`,
                        draftRevision: draft.revision,
                        confirmed: true,
                        note: note.trim(),
                      })
                    )
                  }
                  variant="secondary"
                >
                  确认覆盖范围
                </Button>
              </div>
            )}
            {coverage.confirmed_at && (
              <p className="state state-green" style={{ fontSize: "var(--t-12)" }}>
                <span className="dot" />
                覆盖范围已确认
              </p>
            )}
          </div>
        </div>
      )}

      {error && <Note tone="fail" title="操作失败">{error.message}</Note>}

      {!discarded && (
        <div className="row">
          {!coverage && (
            <Button
              busy={busy}
              busyLabel="正在审查…"
              disabled={included.length === 0}
              onClick={() =>
                run(() =>
                  requestCoverageReview(workspaceId, draft.id, {
                    commandId: `coverage-${draft.id}-${Date.now()}`,
                    draftRevision: draft.revision,
                  })
                )
              }
              variant="secondary"
            >
              开始覆盖审查
            </Button>
          )}
          {coverage?.confirmed_at && (
            <Button
              busy={busy}
              busyLabel="正在冻结…"
              onClick={() =>
                run(() =>
                  freezeDraft(workspaceId, draft.id, {
                    commandId: `freeze-${draft.id}-${Date.now()}`,
                    draftRevision: draft.revision,
                  })
                )
              }
              variant="primary"
            >
              冻结版本
            </Button>
          )}
        </div>
      )}
      {draft.active_operation && (
        <p className="secondary" aria-live="polite" style={{ fontSize: "var(--t-13)" }}>
          {operationLabel(draft.active_operation.kind)} 正在处理中…
        </p>
      )}
    </section>
  );
}
