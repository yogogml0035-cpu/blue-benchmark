import type { Metadata } from "next";
import { Suspense } from "react";

import { PageFallback } from "@/src/components/ui/PageFallback";
import { WorkspaceShelf } from "@/src/features/workspaces/components/WorkspaceShelf";

export const metadata: Metadata = {
  title: "卷宗架 · 审校台",
  description: "当前账号的私有场景列表，并可内联建立新的私有卷宗。",
};

export default function WorkspacesPage() {
  return (
    <Suspense fallback={<PageFallback />}>
      <WorkspaceShelf />
    </Suspense>
  );
}
