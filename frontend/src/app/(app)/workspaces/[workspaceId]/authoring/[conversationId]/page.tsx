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
  searchParams,
}: {
  params: Promise<{ workspaceId: string; conversationId: string }>;
  searchParams?: Promise<{ draft?: string }>;
}) {
  const { workspaceId, conversationId } = await params;
  const query = searchParams ? await searchParams : {};
  return (
    <Suspense fallback={<PageFallback />}>
      <AuthoringConversationPage conversationId={conversationId} draftId={query.draft} workspaceId={workspaceId} />
    </Suspense>
  );
}
