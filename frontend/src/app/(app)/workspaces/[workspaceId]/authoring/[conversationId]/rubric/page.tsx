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
  searchParams,
}: {
  params: Promise<{ workspaceId: string; conversationId: string }>;
  searchParams?: Promise<{ started?: string }>;
}) {
  const { workspaceId, conversationId } = await params;
  const query = searchParams ? await searchParams : {};
  return (
    <Suspense fallback={<PageFallback />}>
      <AuthoringRubricPage conversationId={conversationId} startedFromConfirmation={query.started === "1"} workspaceId={workspaceId} />
    </Suspense>
  );
}
