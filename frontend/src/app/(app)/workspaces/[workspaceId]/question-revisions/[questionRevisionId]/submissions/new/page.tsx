import type { Metadata } from "next";
import { Suspense } from "react";

import { PageFallback } from "@/src/components/ui/PageFallback";
import { SubmissionEntryPage } from "@/src/features/human-scoring/components/HumanScoringPage";

export const metadata: Metadata = {
  title: "提交答卷 · 评测集平台",
  description: "提交一份答卷，依据已发布题目修订进行人工评分。",
};

export default async function SubmissionEntryRoute({
  params,
}: {
  params: Promise<{ workspaceId: string; questionRevisionId: string }>;
}) {
  const { workspaceId, questionRevisionId } = await params;
  return (
    <Suspense fallback={<PageFallback />}>
      <SubmissionEntryPage questionRevisionId={questionRevisionId} workspaceId={workspaceId} />
    </Suspense>
  );
}
