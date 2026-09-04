"use client";

import { Folder } from "lucide-react";
import Link from "next/link";
import { StatusBadge, type StatusTone } from "@/components/ui/status-badge";
import { sceneColorVar } from "../color";
import { CONNECTION_STATUS_LABEL, type ConnectionStatus } from "../connection";
import type { SceneView } from "../api";
import styles from "./folder-card.module.css";

const STATUS_TONE: Record<ConnectionStatus, StatusTone> = {
  unsigned: "neutral",
  issued: "warning",
  connected: "success",
};

export interface FolderCardProps {
  scene: SceneView;
  connection: ConnectionStatus;
}

export function FolderCard({ scene, connection }: FolderCardProps): React.JSX.Element {
  const colorVar = sceneColorVar(scene.id);
  return (
    <Link href={`/evaluation-sets/${scene.id}`} className={styles.card}>
      <div className={styles.tab} style={{ background: colorVar }} aria-hidden="true">
        <Folder size={18} />
      </div>
      <div className={styles.body}>
        <div className={styles.nameRow}>
          <span className={styles.name}>{scene.name}</span>
          <StatusBadge tone={STATUS_TONE[connection]}>
            {CONNECTION_STATUS_LABEL[connection]}
          </StatusBadge>
        </div>
        <p className={styles.description}>{scene.description || "暂无描述"}</p>
        <p className={styles.meta}>{scene.question_count} 道题</p>
      </div>
    </Link>
  );
}
