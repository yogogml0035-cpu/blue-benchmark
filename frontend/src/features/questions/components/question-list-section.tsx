"use client";

import { ChevronRight, FileQuestion, Search } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorPanel } from "@/components/ui/error-panel";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusBadge } from "@/components/ui/status-badge";
import { listQuestions, type QuestionListItem, type QuestionStatus } from "@/features/questions/api";
import { applyListOps } from "@/features/questions/list-ops";
import { NEXT_ACTION_LABEL, STATUS_LABEL, STATUS_TONE } from "@/features/questions/state";
import { formatDateTime } from "@/features/evaluation-sets/format";
import { ApiError } from "@/lib/api/client";
import styles from "./question-list-section.module.css";

const STATUS_OPTIONS: { value: QuestionStatus | ""; label: string }[] = [
  { value: "", label: "全部状态" },
  { value: "generating", label: "生成中" },
  { value: "pending_review", label: "待审改" },
  { value: "generation_failed", label: "生成失败" },
  { value: "published", label: "已发布" },
];

export function QuestionListSection({ sceneId }: { sceneId: string }): React.JSX.Element {
  const [items, setItems] = useState<QuestionListItem[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<QuestionStatus | "">("");
  const loadSeqRef = useRef(0);

  const load = useCallback(async () => {
    const seq = ++loadSeqRef.current;
    setLoadError(null);
    try {
      const response = await listQuestions(sceneId);
      if (seq !== loadSeqRef.current) return;
      setItems(response.items);
    } catch (err) {
      if (seq !== loadSeqRef.current) return;
      setItems(null);
      setLoadError(err instanceof ApiError ? err.message : "加载题目失败，请稍后重试。");
    }
  }, [sceneId]);

  useEffect(() => {
    void load();
  }, [load]);

  const visible = items !== null ? applyListOps(items, { query, status: statusFilter || null }) : [];

  return (
    <section className={styles.section}>
      <div className={styles.header}>
        <h2 className={styles.title}>题目</h2>
        <div className={styles.controls}>
          <div className={styles.search}>
            <Search size={15} aria-hidden="true" />
            <input
              type="search"
              className={styles.searchInput}
              placeholder="按标题搜索"
              aria-label="按标题搜索题目"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>
          <select
            className={styles.statusSelect}
            aria-label="按状态筛选题目"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as QuestionStatus | "")}
          >
            {STATUS_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </div>
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

      {items === null && !loadError ? (
        <div aria-busy="true" className={styles.rows}>
          {Array.from({ length: 4 }, (_, i) => (
            <Skeleton key={i} height={48} />
          ))}
        </div>
      ) : null}

      {items !== null && items.length === 0 ? (
        <EmptyState
          icon={FileQuestion}
          title="还没有题目"
          description="题目由已绑定的上传 Skill 提交。请先在评测集凭证面板生成上传凭证并完成绑定。"
        />
      ) : null}

      {items !== null && items.length > 0 && visible.length === 0 ? (
        <EmptyState icon={Search} title="没有匹配的题目" description="调整搜索词或状态筛选后重试。" />
      ) : null}

      {visible.length > 0 ? (
        <ul className={styles.rows}>
          {visible.map((item) => (
            <li key={item.id} className={styles.row}>
              <Link href={`/evaluation-sets/${item.scene_id}/questions/${item.id}`} className={styles.rowLink}>
                <span className={styles.rowTitle}>{item.title}</span>
                <StatusBadge tone={STATUS_TONE[item.status]}>{STATUS_LABEL[item.status]}</StatusBadge>
                <span className={styles.rowMeta}>
                  {item.rubric_criterion_count !== null ? `${item.rubric_criterion_count} 维度` : "无维度"}
                </span>
                <span className={styles.rowMeta}>{formatDateTime(item.updated_at)}</span>
                <span className={styles.rowAction}>{NEXT_ACTION_LABEL[item.next_action]}</span>
                <ChevronRight size={16} aria-hidden="true" className={styles.rowChevron} />
              </Link>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
