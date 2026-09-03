"use client";

import { FolderKanban } from "lucide-react";
import { EmptyState } from "@/components/ui/empty-state";

/**
 * Placeholder route so the shell has a mountable destination in this task.
 * The real folder grid, metadata editing and credential lifecycle land in the
 * evaluation-set UI task.
 */
export default function EvaluationSetsPage(): React.JSX.Element {
  return (
    <div>
      <h1 style={{ fontSize: 18, fontWeight: 800, margin: "0 0 4px" }}>评测集</h1>
      <p style={{ margin: "0 0 20px", color: "var(--aura-muted)", fontSize: 13 }}>
        评测集是题目归属的第一层业务容器。
      </p>
      <EmptyState
        icon={FolderKanban}
        title="评测集列表即将上线"
        description="创建、重命名与凭证管理将在评测集管理界面任务中提供。当前壳层已连接到真实会话。"
      />
    </div>
  );
}
