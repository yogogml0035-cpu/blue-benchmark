import { bytes } from "@/src/lib/format";
import type { components } from "@/src/lib/api/generated";
import type { ReactNode } from "react";

import styles from "./attachment.module.css";

type Attachment = components["schemas"]["Attachment"];

/**
 * 材料条：安静的文件名 + 大小。类型从扩展名可知、磁盘键由服务端生成，
 * 界面上不再单独摆图标和类型徽记。
 */
export function AttachmentStrip({
  attachment,
  onRemove,
}: {
  attachment: Pick<Attachment, "original_name" | "media_type" | "size_bytes">;
  onRemove?: ReactNode;
}) {
  return (
    <div className={styles.attach}>
      <span className={styles.attachName} title={attachment.original_name}>
        {attachment.original_name}
      </span>
      <span className="mono faint" style={{ whiteSpace: "nowrap" }}>
        {bytes(attachment.size_bytes)}
      </span>
      {onRemove && <span style={{ marginLeft: "auto" }}>{onRemove}</span>}
    </div>
  );
}
