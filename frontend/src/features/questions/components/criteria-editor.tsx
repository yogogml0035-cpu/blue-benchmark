"use client";

import { Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { MAX_PASS_SCORE, newManualDraft, type CriterionDraft } from "../criterion-draft";
import styles from "./criteria-editor.module.css";

export interface CriteriaEditorProps {
  drafts: CriterionDraft[];
  onChange: (updater: (drafts: CriterionDraft[]) => CriterionDraft[]) => void;
  /** When true the list is read-only (published question). */
  readOnly?: boolean;
}

export function CriteriaEditor({ drafts, onChange, readOnly = false }: CriteriaEditorProps): React.JSX.Element {
  const selectedCount = drafts.filter((d) => d.selected).length;

  function patchAt(index: number, patch: Partial<CriterionDraft>): void {
    onChange((list) => list.map((d, i) => (i === index ? { ...d, ...patch } : d)));
  }

  function addManual(): void {
    onChange((list) => [...list, newManualDraft(new Set(list.map((d) => d.id)))]);
  }

  return (
    <div className={styles.editor}>
      <div className={styles.summary}>
        已选 {selectedCount} / {drafts.length} 项（最终需 1–20 项）
      </div>

      {drafts.length === 0 ? (
        <p className={styles.empty}>暂无候选维度。{readOnly ? "" : "可点击下方按钮手工新增。"}</p>
      ) : null}

      <ul className={styles.list}>
        {drafts.map((d, i) => (
          <li key={d.id} className={[styles.item, d.selected ? styles.itemSelected : null].join(" ")}>
            <div className={styles.itemHead}>
              <label className={styles.check}>
                <input
                  type="checkbox"
                  checked={d.selected}
                  disabled={readOnly}
                  onChange={(e) => patchAt(i, { selected: e.target.checked })}
                  aria-label={`选择维度 ${d.id}`}
                />
                <span className={styles.source}>{d.source === "ai" ? "AI 候选" : "手工"}</span>
              </label>
              <label className={styles.score}>
                <span className={styles.scoreLabel}>通过分</span>
                <input
                  type="number"
                  min={0}
                  max={MAX_PASS_SCORE}
                  step={1}
                  value={d.pass_score}
                  disabled={readOnly || !d.selected}
                  onChange={(e) => {
                    const n = Number(e.target.value);
                    patchAt(i, { pass_score: Number.isFinite(n) ? Math.round(n) : 0 });
                  }}
                  aria-label={`维度 ${d.id} 的通过分`}
                />
                <span className={styles.scoreMax}>/ {MAX_PASS_SCORE}</span>
              </label>
              {!readOnly ? (
                <Button
                  variant="ghost"
                  onClick={() => onChange((list) => list.filter((_, j) => j !== i))}
                  aria-label={`删除维度 ${d.id}`}
                >
                  <Trash2 size={15} aria-hidden="true" />
                </Button>
              ) : null}
            </div>
            <textarea
              className={styles.criterion}
              value={d.criterion}
              rows={3}
              readOnly={readOnly || !d.selected}
              placeholder="完整、可执行的评分标准…"
              onChange={(e) => patchAt(i, { criterion: e.target.value })}
              aria-label={`维度 ${d.id} 的评分标准`}
            />
          </li>
        ))}
      </ul>

      {!readOnly ? (
        <Button variant="secondary" onClick={addManual}>
          <Plus size={15} aria-hidden="true" />
          手工新增维度
        </Button>
      ) : null}
    </div>
  );
}
