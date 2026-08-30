"use client";

import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { StatePanel } from "@/src/components/ui/StatePanel";
import { ButtonLink } from "@/src/components/ui/Button";
import { getWorkspace, type Workspace } from "@/src/features/workspaces/services/workspaceService";
import {
  CurrentSection,
  QuestionsSection,
  StudioSection,
  StudioShell,
  useStudioData,
  VersionsSection,
} from "@/src/features/workspaces/components/StudioShell";
import { PREVIEW_WORKSPACES } from "@/src/features/workspaces/preview/fixtures";
import { toPageFault, type PageFault } from "@/src/lib/api/pageFault";

export function StudioPage({ workspaceId }: { workspaceId: string }) {
  const searchParams = useSearchParams();
  const sectionParam = searchParams.get("section") as StudioSection | null;
  const section: StudioSection = sectionParam && ["current", "questions", "versions"].includes(sectionParam)
    ? sectionParam
    : "current";

  const batchId = searchParams.get("batch");
  const { load, read, refreshing, preview, session } = useStudioData(workspaceId, batchId);
  const [workspace, setWorkspace] = useState<Workspace | null>(null);

  useEffect(() => {
    if (preview) {
      setWorkspace(PREVIEW_WORKSPACES[0]);
      return;
    }
    if (session.status !== "authenticated") return;
    let active = true;
    setWorkspace(null);
    getWorkspace(workspaceId)
      .then((result) => {
        if (active) setWorkspace(result.workspace);
      })
      .catch(() => {
        if (active) setWorkspace(null);
      });
    return () => {
      active = false;
    };
  }, [preview, session.status, workspaceId]);

  if (load.status === "loading") {
    return (
      <StudioShell
        section={section}
        workspaceId={workspaceId}
        workspaceName={workspace?.name}
      >
        <div aria-busy="true" className="stack-lg">
          <div className="skeleton" style={{ height: 28, width: "40%" }} />
          <div className="sheet sheet-pad stack">
            <div className="skeleton" style={{ height: 20, width: "60%" }} />
            <div className="skeleton" style={{ height: 40 }} />
          </div>
        </div>
      </StudioShell>
    );
  }

  if (load.status === "failed") {
    const fault = load.fault;
    return (
      <StudioShell
        section={section}
        workspaceId={workspaceId}
        workspaceName={workspace?.name}
      >
        <StatePanel
          actions={
            <ButtonLink href="/workspaces" variant="primary">
              回到场景
            </ButtonLink>
          }
          code={fault.code}
          description={fault.message}
          title="工作台读取失败"
          tone="fault"
        />
      </StudioShell>
    );
  }

  const projection = load.projection;

  return (
    <StudioShell
      batchId={batchId}
      busy={refreshing}
      onRefresh={() => void read(true)}
      section={section}
      workspaceId={workspaceId}
      workspaceName={workspace?.name}
    >
      {section === "current" && (
        <CurrentSection
          onRefresh={() => void read(true)}
          projection={projection}
          refreshing={refreshing}
          workspaceId={workspaceId}
        />
      )}
      {section === "questions" && (
        <QuestionsSection
          onRefresh={() => void read(true)}
          projection={projection}
          workspaceId={workspaceId}
        />
      )}
      {section === "versions" && (
        <VersionsSection
          onRefresh={() => void read(true)}
          projection={projection}
          workspaceId={workspaceId}
        />
      )}
    </StudioShell>
  );
}
