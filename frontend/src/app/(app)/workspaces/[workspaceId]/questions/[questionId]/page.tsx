import type { Metadata } from "next";
import { Suspense } from "react";

import { PageFallback } from "@/src/components/ui/PageFallback";
import { QuestionPage } from "@/src/features/case-builder/components/QuestionPage";

export const metadata: Metadata = {
  title: "题稿共创 · 评测集平台",
  description: "一次一个问题，审阅并定稿一道题。",
};

export default async function WorkspaceQuestionPage({
  params,
}: {
  params: Promise<{ workspaceId: string; questionId: string }>;
}) {
  const { workspaceId, questionId } = await params;
  return (
    <Suspense fallback={<PageFallback />}>
      <QuestionPage questionId={questionId} workspaceId={workspaceId} />
    </Suspense>
  );
}
