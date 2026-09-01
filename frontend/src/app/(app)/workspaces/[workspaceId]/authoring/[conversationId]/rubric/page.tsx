import type { Metadata } from "next";
import { Suspense } from "react";

import { PageFallback } from "@/src/components/ui/PageFallback";
import { AuthoringRubricPage } from "@/src/features/evaluation-sets/components/AuthoringRubricPage";

export const metadata: Metadata = {
  title: "评分规则 · 评测集平台",
  description: "审阅、确认并发布一套 100 分制 Benchmark 打分规则。",
};

export default async function AuthoringRubricRoute({
  params,
}: {
  params: Promise<{ workspaceId: string; conversationId: string }>;
}) {
  const { workspaceId, conversationId } = await params;
  return (
    <Suspense fallback={<PageFallback />}>
      <AuthoringRubricPage conversationId={conversationId} workspaceId={workspaceId} />
    </Suspense>
  );
}
