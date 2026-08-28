import { CaseDetailView } from "@/src/features/case-builder/components/CaseDetailView";

export default async function CasePage({
  params,
}: {
  params: Promise<{ workspaceId: string; caseId: string }>;
}) {
  const { workspaceId, caseId } = await params;
  return <CaseDetailView workspaceId={workspaceId} caseId={caseId} />;
}

