import type { Metadata } from "next";
import { Suspense } from "react";

import { PageFallback } from "@/src/components/ui/PageFallback";
import { ScenarioShelf } from "@/src/features/workspaces/components/ScenarioShelf";

export const metadata: Metadata = {
  title: "场景 · 评测集平台",
  description: "当前账号的私有业务场景列表，并可内联创建新的场景。",
};

export default function WorkspacesPage() {
  return (
    <Suspense fallback={<PageFallback />}>
      <ScenarioShelf />
    </Suspense>
  );
}
