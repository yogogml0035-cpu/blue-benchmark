import type { Metadata } from "next";
import { Suspense } from "react";

import { PageFallback } from "@/src/components/ui/PageFallback";
import { AuthoringNewPage } from "@/src/features/case-builder/components/AuthoringNewPage";

export const metadata: Metadata = {
  title: "开始建题 · 评测集平台",
  description: "从真实资料或手动输入开始形成一道可复核的题。",
};

export default async function NewAuthoringPage({
  params,
}: {
  params: Promise<{ workspaceId: string }>;
}) {
  const { workspaceId } = await params;
  return (
    <Suspense fallback={<PageFallback />}>
      <AuthoringNewPage workspaceId={workspaceId} />
    </Suspense>
  );
}
