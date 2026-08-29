import type { Metadata } from "next";
import { Suspense } from "react";

import { PageFallback } from "@/src/components/ui/PageFallback";
import { CaseIntake } from "@/src/features/case-builder/components/CaseIntake";

export const metadata: Metadata = {
  title: "收件 · 审校台",
  description: "向一份私有卷宗提交 TXT/Markdown 原件，服务端同步保存并解析。",
};

export default async function NewCasePage({
  params,
}: {
  params: Promise<{ workspaceId: string }>;
}) {
  const { workspaceId } = await params;
  return (
    <Suspense fallback={<PageFallback />}>
      <CaseIntake workspaceId={workspaceId} />
    </Suspense>
  );
}
