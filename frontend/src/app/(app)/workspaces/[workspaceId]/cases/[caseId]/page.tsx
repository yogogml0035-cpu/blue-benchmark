import type { Metadata } from "next";
import { Suspense } from "react";

import { PageFallback } from "@/src/components/ui/PageFallback";
import { CaseDetail } from "@/src/features/case-builder/components/CaseDetail";

export const metadata: Metadata = {
  title: "案例详情 · 评测集平台",
  description: "查看解析与 AI 整理状态、回答需要补充的问题、修改并确认标准草稿，最后收录为候选标准案例。",
};

export default async function CaseDetailPage({
  params,
}: {
  params: Promise<{ workspaceId: string; caseId: string }>;
}) {
  const { workspaceId, caseId } = await params;
  return (
    <Suspense fallback={<PageFallback width="page-wide" />}>
      <CaseDetail caseId={caseId} workspaceId={workspaceId} />
    </Suspense>
  );
}
