import type { Metadata } from "next";
import { Suspense } from "react";

import { PageFallback } from "@/src/components/ui/PageFallback";
import { UploadPage } from "@/src/features/workspaces/components/UploadPage";

export const metadata: Metadata = {
  title: "上传资料 · 评测集平台",
  description: "上传真实交付材料，开始形成标准。",
};

export default async function WorkspaceUploadPage({
  params,
}: {
  params: Promise<{ workspaceId: string }>;
}) {
  const { workspaceId } = await params;
  return (
    <Suspense fallback={<PageFallback />}>
      <UploadPage workspaceId={workspaceId} />
    </Suspense>
  );
}
