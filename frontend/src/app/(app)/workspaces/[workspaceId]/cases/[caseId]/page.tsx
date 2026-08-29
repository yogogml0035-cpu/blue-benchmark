import type { Metadata } from "next";
import { Suspense } from "react";

import { PageFallback } from "@/src/components/ui/PageFallback";
import { CaseFile } from "@/src/features/case-builder/components/CaseFile";

export const metadata: Metadata = {
  title: "校样 · 审校台",
  description: "查看解析与 AI 状态、回答缺口追问、修改并确认草案，最后展示候选用例。",
};

export default async function CaseDetailPage({
  params,
}: {
  params: Promise<{ workspaceId: string; caseId: string }>;
}) {
  const { workspaceId, caseId } = await params;
  return (
    <Suspense fallback={<PageFallback width="page-wide" />}>
      <CaseFile caseId={caseId} workspaceId={workspaceId} />
    </Suspense>
  );
}
