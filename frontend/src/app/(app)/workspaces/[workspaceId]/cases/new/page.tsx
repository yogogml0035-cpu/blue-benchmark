import type { Metadata } from "next";
import { Suspense } from "react";

import { PageFallback } from "@/src/components/ui/PageFallback";
import { CaseUpload } from "@/src/features/case-builder/components/CaseUpload";

export const metadata: Metadata = {
  title: "上传真实案例 · 评测集平台",
  description: "向一个私有场景上传 TXT/Markdown 材料，服务端同步保存并解析。",
};

export default async function NewCasePage({
  params,
}: {
  params: Promise<{ workspaceId: string }>;
}) {
  const { workspaceId } = await params;
  return (
    <Suspense fallback={<PageFallback />}>
      <CaseUpload workspaceId={workspaceId} />
    </Suspense>
  );
}
