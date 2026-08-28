import { NewCaseForm } from "@/src/features/case-builder/components/NewCaseForm";

export default async function NewCasePage({
  params,
}: {
  params: Promise<{ workspaceId: string }>;
}) {
  const { workspaceId } = await params;
  return <NewCaseForm workspaceId={workspaceId} />;
}

