import type { Metadata } from "next";
import { Suspense } from "react";

import { PageFallback } from "@/src/components/ui/PageFallback";
import { VersionPage } from "@/src/features/workspaces/components/VersionPage";

export const metadata: Metadata = {
  title: "历史版本 · 评测集平台",
  description: "查看不可变历史版本与下载完整包。",
};

export default async function WorkspaceVersionPage({
  params,
}: {
  params: Promise<{ workspaceId: string; versionId: string }>;
}) {
  const { workspaceId, versionId } = await params;
  return (
    <Suspense fallback={<PageFallback />}>
      <VersionPage versionId={versionId} workspaceId={workspaceId} />
    </Suspense>
  );
}
