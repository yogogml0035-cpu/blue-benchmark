import { redirect } from "next/navigation";

export default async function CaseRedirectPage({
  params,
}: {
  params: Promise<{ workspaceId: string; caseId: string }>;
}) {
  const { workspaceId, caseId } = await params;
  redirect(`/workspaces/${workspaceId}/questions/${caseId}`);
}
