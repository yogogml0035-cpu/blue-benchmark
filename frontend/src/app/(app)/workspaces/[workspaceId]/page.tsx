import type { Metadata } from "next";
import { Suspense } from "react";

import { PageFallback } from "@/src/components/ui/PageFallback";
import { StudioPage } from "@/src/features/workspaces/components/StudioPage";

export const metadata: Metadata = {
  title: "场景工作台 · 评测集平台",
  description: "当前、题和版本都在这一个工作台里。",
};

export default async function WorkspaceStudioPage({
  params,
  searchParams,
}: {
  params: Promise<{ workspaceId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { workspaceId } = await params;
  await searchParams;
  return (
    <Suspense fallback={<PageFallback />}>
      <StudioPage workspaceId={workspaceId} />
    </Suspense>
  );
}
