import type { Metadata } from "next";
import { redirect } from "next/navigation";

export const metadata: Metadata = { title: "题 · 评测集平台" };

export default async function WorkspaceQuestionPage({
  params,
}: {
  params: Promise<{ workspaceId: string; questionId: string }>;
}) {
  const { workspaceId } = await params;
  redirect(`/workspaces/${workspaceId}?section=questions`);
}
