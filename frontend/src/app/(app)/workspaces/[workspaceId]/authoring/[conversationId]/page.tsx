import type { Metadata } from "next";
import { Suspense } from "react";

import { PageFallback } from "@/src/components/ui/PageFallback";
import { AuthoringConversationPage } from "@/src/features/case-builder/components/AuthoringConversationPage";

export const metadata: Metadata = {
  title: "建题会话 · 评测集平台",
  description: "在一条可恢复的会话里形成题目输入和标准答案。",
};

export default async function AuthoringConversationRoute({
  params,
}: {
  params: Promise<{ workspaceId: string; conversationId: string }>;
}) {
  const { workspaceId, conversationId } = await params;
  return (
    <Suspense fallback={<PageFallback />}>
      <AuthoringConversationPage conversationId={conversationId} workspaceId={workspaceId} />
    </Suspense>
  );
}
