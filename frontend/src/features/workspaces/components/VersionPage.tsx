"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { DeskRail } from "@/src/components/shell/DeskRail";
import { Button, ButtonLink } from "@/src/components/ui/Button";
import { Note } from "@/src/components/ui/Note";
import { SkeletonLine } from "@/src/components/ui/Skeleton";
import { StatePanel } from "@/src/components/ui/StatePanel";
import { TechnicalDisclosure } from "@/src/components/ui/Sheet";
import { UserChip } from "@/src/features/auth/components/UserChip";
import { useSession } from "@/src/features/auth/hooks/useSession";
import {
  getManifest,
  getDownloadUrl,
  type ManifestResponse,
} from "@/src/features/workspaces/services/studioService";
import { loginHref, toPageFault, type PageFault } from "@/src/lib/api/pageFault";
import { stamp } from "@/src/lib/format";
import { PREVIEW_ENABLED, PreviewBar, usePreviewState } from "@/src/lib/preview/preview";

type Load =
  | { status: "loading" }
  | { status: "ready"; manifest: ManifestResponse }
  | { status: "failed"; fault: PageFault };

export function VersionPage({
  workspaceId,
  versionId,
}: {
  workspaceId: string;
  versionId: string;
}) {
  const router = useRouter();
  const preview = usePreviewState();
  const session = useSession();

  const [load, setLoad] = useState<Load>({ status: "loading" });

  const authenticated = session.status === "authenticated";
  const returnTo = `/workspaces/${workspaceId}/versions/${versionId}`;

  useEffect(() => {
    if (preview) return;
    if (session.status === "anonymous") router.replace(loginHref(returnTo));
  }, [preview, returnTo, router, session.status]);

  useEffect(() => {
    if (preview || !authenticated) return;
    let active = true;
    setLoad({ status: "loading" });
    getManifest(workspaceId, versionId)
      .then((result) => {
        if (active) setLoad({ status: "ready", manifest: result });
      })
      .catch((cause: unknown) => {
        if (active) setLoad({ status: "failed", fault: toPageFault(cause) });
      });
    return () => {
      active = false;
    };
  }, [preview, authenticated, workspaceId, versionId]);

  const rail = (
    <DeskRail
      crumbs={[
        { label: "场景", href: "/workspaces" },
        { label: "历史版本" },
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
            description="登录后才能查看这个版本。"
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
              <ButtonLink href={`/workspaces/${workspaceId}?section=versions`} variant="primary">
                回到版本列表
              </ButtonLink>
            }
            code={fault.code}
            description={fault.message}
            title="版本读取失败"
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
            </div>
          </div>
        </main>
      </>
    );
  }

  const { manifest } = load;
  const version = manifest.version;

  return (
    <>
      {rail}
      {previewBar}
      <main className="page page-mid stack-lg">
        <div className="stack-sm">
          <div className="spread">
            <h1 className="doc-title">版本 {version.version_number}</h1>
            <span className="state state-green">
              <span className="dot" />
              已冻结
            </span>
          </div>
          <p className="secondary">
            冻结于 {stamp(version.frozen_at)} · 不可修改
          </p>
        </div>

        <section className="sheet sheet-pad stack">
          <h2 className="doc-title-sm">下载完整包</h2>
          <p className="secondary">
            完整包包含三个分区：给 Skill 的材料、评分依据、形成记录。
            评分依据和形成记录不能交给被测 Skill。
          </p>
          <div className="row">
            <Button
              onClick={() => window.open(getDownloadUrl(workspaceId, versionId), "_blank")}
              variant="primary"
            >
              下载完整包
            </Button>
          </div>
        </section>

        <section className="sheet sheet-pad stack">
          <h2 className="doc-title-sm">版本信息</h2>
          <div className="stack-sm">
            <div className="row-between">
              <span className="secondary">版本号</span>
              <span className="mono">{version.version_number}</span>
            </div>
            <div className="row-between">
              <span className="secondary">冻结时间</span>
              <span className="mono">{stamp(version.frozen_at)}</span>
            </div>
            <div className="row-between">
              <span className="secondary">状态</span>
              <span className="state state-green">
                <span className="dot" />
                已冻结
              </span>
            </div>
          </div>
        </section>

        <TechnicalDisclosure label="技术详情">
          <div className="stack-sm">
            <div className="row-between">
              <span>Manifest SHA-256</span>
              <span className="mono" style={{ fontSize: "var(--t-12)" }}>
                {version.overall_sha256.slice(0, 16)}…
              </span>
            </div>
            <div className="row-between">
              <span>版本 ID</span>
              <span className="mono" style={{ fontSize: "var(--t-12)" }}>
                {version.id}
              </span>
            </div>
          </div>
        </TechnicalDisclosure>
      </main>
    </>
  );
}
