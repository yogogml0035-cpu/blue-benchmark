import type { Metadata } from "next";
import { Suspense } from "react";

import { PageFallback } from "@/src/components/ui/PageFallback";
import { HumanScoringPage } from "@/src/features/human-scoring/components/HumanScoringPage";

export const metadata: Metadata = {
  title: "人工评分 · 评测集平台",
  description: "阅读一份答卷，依据已发布规则完成可追溯的人工评分。",
};

export default async function HumanScoringRoute({
  params,
}: {
  params: Promise<{ workspaceId: string; submissionId: string }>;
}) {
  const { workspaceId, submissionId } = await params;
  return (
    <Suspense fallback={<PageFallback />}>
      <HumanScoringPage submissionId={submissionId} workspaceId={workspaceId} />
    </Suspense>
  );
}
