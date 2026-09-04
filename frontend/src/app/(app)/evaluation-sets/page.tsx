"use client";

import { FolderPlus, Plus } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorPanel } from "@/components/ui/error-panel";
import { Skeleton } from "@/components/ui/skeleton";
import { getSceneStatus, listScenes, type SceneView } from "@/features/evaluation-sets/api";
import {
  deriveConnectionStatus,
  type ConnectionStatus,
} from "@/features/evaluation-sets/connection";
import { FolderCard } from "@/features/evaluation-sets/components/folder-card";
import { EvaluationSetFormDialog } from "@/features/evaluation-sets/components/form-dialog";
import { ApiError } from "@/lib/api/client";
import styles from "./page.module.css";

export default function EvaluationSetsPage(): React.JSX.Element {
  const router = useRouter();
  const [scenes, setScenes] = useState<SceneView[] | null>(null);
  const [connectionById, setConnectionById] = useState<Record<string, ConnectionStatus>>({});
  const [loadError, setLoadError] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  // Guards against overlapping loads (retry, StrictMode) writing state out of
  // order: only the most recent load may commit its result.
  const loadSeqRef = useRef(0);

  const load = useCallback(async () => {
    const seq = ++loadSeqRef.current;
    setLoadError(null);
    try {
      const response = await listScenes();
      // Derive the precise connection state per scene from its current
      // credential, then commit scenes and badges together so they never
      // disagree mid-load.
      const entries = await Promise.all(
        response.items.map(async (scene) => {
          try {
            const status = await getSceneStatus(scene.id);
            return [scene.id, deriveConnectionStatus(status.credential)] as const;
          } catch {
            return [scene.id, "unsigned"] as const;
          }
        }),
      );
      if (seq !== loadSeqRef.current) return;
      setConnectionById(Object.fromEntries(entries));
      setScenes(response.items);
    } catch (err) {
      if (seq !== loadSeqRef.current) return;
      setScenes(null);
      setLoadError(err instanceof ApiError ? err.message : "加载评测集失败，请稍后重试。");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <div>
          <h1 className={styles.title}>评测集</h1>
          <p className={styles.subtitle}>评测集是题目归属的第一层业务容器。</p>
        </div>
        <Button onClick={() => setCreateOpen(true)}>
          <Plus size={16} aria-hidden="true" />
          创建评测集
        </Button>
      </div>

      {loadError ? (
        <ErrorPanel
          title="加载未成功"
          message={loadError}
          action={
            <Button variant="secondary" onClick={() => void load()}>
              重试
            </Button>
          }
        />
      ) : null}

      {scenes === null && !loadError ? (
        <div className={styles.grid} aria-busy="true">
          {Array.from({ length: 6 }, (_, i) => (
            <Skeleton key={i} variant="block" height={140} />
          ))}
        </div>
      ) : null}

      {scenes !== null && scenes.length === 0 ? (
        <EmptyState
          icon={FolderPlus}
          title="还没有评测集"
          description="创建一个评测集，然后用上传凭证把本地上传 Skill 绑定进来。"
          action={
            <Button onClick={() => setCreateOpen(true)}>
              <Plus size={16} aria-hidden="true" />
              创建评测集
            </Button>
          }
        />
      ) : null}

      {scenes !== null && scenes.length > 0 ? (
        <div className={styles.grid}>
          {scenes.map((scene) => (
            <FolderCard
              key={scene.id}
              scene={scene}
              connection={connectionById[scene.id] ?? "unsigned"}
            />
          ))}
        </div>
      ) : null}

      <EvaluationSetFormDialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onSaved={(saved) => {
          // Enter the new evaluation set's detail; no credential is auto-issued.
          router.push(`/evaluation-sets/${saved.id}`);
        }}
      />
    </div>
  );
}
