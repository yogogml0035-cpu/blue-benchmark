"use client";

import { ChevronDown, ChevronRight } from "lucide-react";
import { useState } from "react";
import { TextField } from "@/components/ui/text-field";
import type { MaterialDraft } from "../material-draft";
import styles from "./materials-panel.module.css";

export interface MaterialsPanelProps {
  draft: MaterialDraft;
  editing: boolean;
  onChange: (updater: (draft: MaterialDraft) => MaterialDraft) => void;
}

export function MaterialsPanel({ draft, editing, onChange }: MaterialsPanelProps): React.JSX.Element {
  const [memoryOpen, setMemoryOpen] = useState(false);

  if (!editing) {
    return (
      <div className={[styles.materials, styles.view].join(" ")}>
        <MaterialBlock label="题目">
          <p className={styles.text}>{draft.task_prompt}</p>
        </MaterialBlock>

        <MaterialBlock label={`参考文本（${draft.reference_examples.length}）`}>
          {draft.reference_examples.length === 0 ? (
            <p className={styles.empty}>无参考文本</p>
          ) : (
            draft.reference_examples.map((e, i) => (
              <div key={e.client_ref_id || i} className={styles.subItem}>
                {e.source_name ? <p className={styles.subLabel}>{e.source_name}</p> : null}
                <p className={styles.text}>{e.content_text}</p>
              </div>
            ))
          )}
        </MaterialBlock>

        <MaterialBlock label={`Bad case（${draft.bad_cases.length}）`}>
          {draft.bad_cases.length === 0 ? (
            <p className={styles.empty}>无 Bad case</p>
          ) : (
            draft.bad_cases.map((b, i) => (
              <div key={i} className={styles.subItem}>
                <p className={styles.text}>{b.content_text}</p>
                {b.teacher_feedback_texts.map((f, j) => (
                  <p key={j} className={styles.feedback}>
                    老师反馈：{f}
                  </p>
                ))}
                {b.reason_summary ? <p className={styles.subLabel}>原因：{b.reason_summary}</p> : null}
              </div>
            ))
          )}
        </MaterialBlock>

        <MaterialBlock label="标准答案">
          <p className={styles.text}>{draft.reference_answer}</p>
        </MaterialBlock>

        <div className={[styles.materialBlock, memoryOpen ? null : styles.memoryClosed].join(" ")}>
          <button
            type="button"
            className={styles.memoryToggle}
            onClick={() => setMemoryOpen((v) => !v)}
            aria-expanded={memoryOpen}
          >
            {memoryOpen ? <ChevronDown size={15} aria-hidden="true" /> : <ChevronRight size={15} aria-hidden="true" />}
            用户记忆（{draft.memory_materials.length}）
          </button>
          <p className={styles.memoryNote}>由 Agent 自动筛选，上传时未逐条确认。</p>
          {memoryOpen ? (
            <div className={styles.blockScroll}>
              {draft.memory_materials.length === 0 ? (
                <p className={styles.empty}>无用户记忆</p>
              ) : (
                draft.memory_materials.map((m, i) => (
                  <div key={m.client_ref_id || i} className={styles.subItem}>
                    {m.source_label ? <p className={styles.subLabel}>{m.source_label}</p> : null}
                    <p className={styles.text}>{m.content_text}</p>
                  </div>
                ))
              )}
            </div>
          ) : null}
        </div>
      </div>
    );
  }

  // Edit mode.
  return (
    <div className={styles.materials}>
      <TextField
        label="用例标题"
        value={draft.title}
        onChange={(e) => onChange((d) => ({ ...d, title: e.target.value }))}
      />
      <FieldArea
        label="题目"
        value={draft.task_prompt}
        onChange={(v) => onChange((d) => ({ ...d, task_prompt: v }))}
      />
      <FieldArea
        label="标准答案"
        value={draft.reference_answer}
        onChange={(v) => onChange((d) => ({ ...d, reference_answer: v }))}
      />

      <MaterialBlock label={`参考文本（${draft.reference_examples.length}）`}>
        {draft.reference_examples.map((e, i) => (
          <FieldArea
            key={e.client_ref_id || i}
            label={`样例 ${i + 1}${e.source_name ? ` · ${e.source_name}` : ""}`}
            value={e.content_text}
            onChange={(v) =>
              onChange((d) => ({
                ...d,
                reference_examples: d.reference_examples.map((x, j) =>
                  j === i ? { ...x, content_text: v } : x,
                ),
              }))
            }
          />
        ))}
      </MaterialBlock>

      <MaterialBlock label={`Bad case（${draft.bad_cases.length}）`}>
        {draft.bad_cases.map((b, i) => (
          <FieldArea
            key={i}
            label={`Bad case ${i + 1}`}
            value={b.content_text}
            onChange={(v) =>
              onChange((d) => ({
                ...d,
                bad_cases: d.bad_cases.map((x, j) => (j === i ? { ...x, content_text: v } : x)),
              }))
            }
          />
        ))}
      </MaterialBlock>

      <MaterialBlock label={`用户记忆（${draft.memory_materials.length}）`}>
        {draft.memory_materials.map((m, i) => (
          <FieldArea
            key={m.client_ref_id || i}
            label={`记忆 ${i + 1}${m.source_label ? ` · ${m.source_label}` : ""}`}
            value={m.content_text}
            onChange={(v) =>
              onChange((d) => ({
                ...d,
                memory_materials: d.memory_materials.map((x, j) =>
                  j === i ? { ...x, content_text: v } : x,
                ),
              }))
            }
          />
        ))}
      </MaterialBlock>
    </div>
  );
}

function MaterialBlock({ label, children }: { label: string; children: React.ReactNode }): React.JSX.Element {
  return (
    <div className={styles.materialBlock}>
      <h3 className={styles.blockLabel}>{label}</h3>
      <div className={styles.blockScroll}>{children}</div>
    </div>
  );
}

function FieldArea({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
}): React.JSX.Element {
  return (
    <label className={styles.fieldArea}>
      <span className={styles.fieldAreaLabel}>{label}</span>
      <textarea
        className={styles.textarea}
        value={value}
        rows={4}
        onChange={(e) => onChange(e.target.value)}
      />
    </label>
  );
}
