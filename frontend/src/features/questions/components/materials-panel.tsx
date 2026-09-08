"use client";

import { ChevronDown, ChevronRight, Pencil } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api/client";
import type { QuestionDetailResponse, QuestionMaterialsPatchRequest } from "../api";
import {
  buildModulePatch,
  moduleBuffer,
  type BadCaseBuffer,
  type MaterialModuleBuffer,
  type MaterialModuleKey,
  type MemoryMaterialBuffer,
  type ReferenceExampleBuffer,
} from "../materials-edit";
import styles from "./materials-panel.module.css";

export interface MaterialsPanelProps {
  detail: QuestionDetailResponse;
  /** False while the question is generating/published/deleting: view-only. */
  canEdit: boolean;
  /**
   * Persist one module's patch (autosave). Rejects on failure so the module
   * keeps its edit state and offers a retry; the parent surfaces
   * STALE_REVISION through the shared conflict banner.
   */
  onSaveModule: (patch: QuestionMaterialsPatchRequest) => Promise<QuestionDetailResponse>;
  /** Reports whether a module edit buffer is open (unload warning guard). */
  onEditingChange?: (open: boolean) => void;
}

export function MaterialsPanel({
  detail,
  canEdit,
  onSaveModule,
  onEditingChange,
}: MaterialsPanelProps): React.JSX.Element {
  const [editingKey, setEditingKey] = useState<MaterialModuleKey | null>(null);
  const [buffer, setBuffer] = useState<MaterialModuleBuffer | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [memoryOpen, setMemoryOpen] = useState(false);

  const editing = (key: MaterialModuleKey): boolean => editingKey === key && buffer !== null;

  // A terminal gate (generation started / published / frozen) invalidates any
  // open buffer: exit instead of letting the next blur 409-loop.
  useEffect(() => {
    if (!canEdit) exitEdit();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [canEdit]);

  useEffect(() => {
    onEditingChange?.(editingKey !== null);
  }, [editingKey, onEditingChange]);

  function enterEdit(key: MaterialModuleKey): void {
    if (!canEdit || saving) return;
    setEditingKey(key);
    setBuffer(moduleBuffer(detail, key));
    setError(null);
  }

  function exitEdit(): void {
    setEditingKey(null);
    setBuffer(null);
    setError(null);
  }

  async function commit(): Promise<void> {
    if (editingKey === null || buffer === null) return;
    const patch = buildModulePatch(detail, editingKey, buffer);
    if (patch === null) {
      // Nothing actually changed: leaving edit state must not fake a save.
      exitEdit();
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await onSaveModule({ content_revision: detail.content_revision, ...patch });
      exitEdit();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "保存失败，请稍后重试。");
    } finally {
      setSaving(false);
    }
  }

  function escapeCancels(e: React.KeyboardEvent<HTMLTextAreaElement>): void {
    if (e.key === "Escape") {
      e.preventDefault();
      exitEdit();
    }
  }

  return (
    <div className={styles.materials}>
      <ModuleFrame
        label="题目"
        moduleKey="task_prompt"
        editable={canEdit}
        editing={editing("task_prompt")}
        saving={saving}
        error={error}
        onEnterEdit={() => enterEdit("task_prompt")}
        onFocusLeave={() => void commit()}
        onCommit={() => void commit()}
        onDiscard={exitEdit}
      >
        {editing("task_prompt") ? (
          <textarea
            className={styles.textarea}
            value={buffer as string}
            rows={7}
            autoFocus
            onChange={(e) => setBuffer(e.target.value)}
            onKeyDown={escapeCancels}
            aria-label="题目内容"
          />
        ) : (
          <div className={styles.maskBox}>
            <p className={styles.text}>{detail.task_prompt}</p>
          </div>
        )}
      </ModuleFrame>

      <ModuleFrame
        label={`参考文本（${detail.reference_examples.length}）`}
        moduleKey="reference_examples"
        editable={canEdit && detail.reference_examples.length > 0}
        editing={editing("reference_examples")}
        saving={saving}
        error={error}
        onEnterEdit={() => enterEdit("reference_examples")}
        onFocusLeave={() => void commit()}
        onCommit={() => void commit()}
        onDiscard={exitEdit}
      >
        {editing("reference_examples") ? (
          (buffer as ReferenceExampleBuffer[]).map((e, i) => (
            <label key={e.client_ref_id || i} className={styles.fieldArea}>
              <span className={styles.fieldAreaLabel}>
                {`样例 ${i + 1}${e.source_name ? ` · ${e.source_name}` : ""}`}
              </span>
              <textarea
                className={styles.textarea}
                value={e.content_text}
                rows={5}
                autoFocus={i === 0}
                onChange={(ev) =>
                  setBuffer((current) =>
                    (current as ReferenceExampleBuffer[]).map((x, j) =>
                      j === i ? { ...x, content_text: ev.target.value } : x,
                    ),
                  )
                }
                onKeyDown={escapeCancels}
                aria-label={`参考文本 ${i + 1} 内容`}
              />
            </label>
          ))
        ) : detail.reference_examples.length === 0 ? (
          <div className={styles.maskBox}>
            <p className={styles.empty}>无参考文本</p>
          </div>
        ) : (
          detail.reference_examples.map((e, i) => (
            <div key={e.client_ref_id || i} className={styles.maskBox}>
              {e.source_name ? <p className={styles.subLabel}>{e.source_name}</p> : null}
              <p className={styles.text}>{e.content_text}</p>
            </div>
          ))
        )}
      </ModuleFrame>

      <ModuleFrame
        label={`Bad case（${detail.bad_cases.length}）`}
        moduleKey="bad_cases"
        editable={canEdit && detail.bad_cases.length > 0}
        editing={editing("bad_cases")}
        saving={saving}
        error={error}
        onEnterEdit={() => enterEdit("bad_cases")}
        onFocusLeave={() => void commit()}
        onCommit={() => void commit()}
        onDiscard={exitEdit}
      >
        {editing("bad_cases") ? (
          (buffer as BadCaseBuffer[]).map((b, i) => (
            <div key={i} className={styles.fieldArea}>
              <span className={styles.fieldAreaLabel}>{`Bad case ${i + 1}`}</span>
              <textarea
                className={styles.textarea}
                value={b.content_text}
                rows={5}
                autoFocus={i === 0}
                onChange={(ev) =>
                  setBuffer((current) =>
                    (current as BadCaseBuffer[]).map((x, j) =>
                      j === i ? { ...x, content_text: ev.target.value } : x,
                    ),
                  )
                }
                onKeyDown={escapeCancels}
                aria-label={`Bad case ${i + 1} 内容`}
              />
              {b.teacher_feedback_texts.map((f, j) => (
                <p key={j} className={styles.feedback}>
                  老师反馈：{f}
                </p>
              ))}
              {b.reason_summary ? <p className={styles.subLabel}>原因：{b.reason_summary}</p> : null}
            </div>
          ))
        ) : detail.bad_cases.length === 0 ? (
          <div className={styles.maskBox}>
            <p className={styles.empty}>无 Bad case</p>
          </div>
        ) : (
          detail.bad_cases.map((b, i) => (
            <div key={i} className={styles.maskBox}>
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
      </ModuleFrame>

      <ModuleFrame
        label="标准答案"
        moduleKey="reference_answer"
        editable={canEdit}
        editing={editing("reference_answer")}
        saving={saving}
        error={error}
        onEnterEdit={() => enterEdit("reference_answer")}
        onFocusLeave={() => void commit()}
        onCommit={() => void commit()}
        onDiscard={exitEdit}
      >
        {editing("reference_answer") ? (
          <textarea
            className={styles.textarea}
            value={buffer as string}
            rows={7}
            autoFocus
            onChange={(e) => setBuffer(e.target.value)}
            onKeyDown={escapeCancels}
            aria-label="标准答案内容"
          />
        ) : (
          <div className={styles.maskBox}>
            <p className={styles.text}>{detail.reference_answer}</p>
          </div>
        )}
      </ModuleFrame>

      <ModuleFrame
        label={`业务记忆（${detail.memory_materials.length}）`}
        moduleKey="memory_materials"
        editable={canEdit && detail.memory_materials.length > 0}
        editing={editing("memory_materials")}
        saving={saving}
        error={error}
        onEnterEdit={() => enterEdit("memory_materials")}
        onFocusLeave={() => void commit()}
        onCommit={() => void commit()}
        onDiscard={exitEdit}
      >
        {editing("memory_materials") ? (
          (buffer as MemoryMaterialBuffer[]).map((m, i) => (
            <label key={m.client_ref_id || i} className={styles.fieldArea}>
              <span className={styles.fieldAreaLabel}>
                {`业务记忆 ${i + 1}${m.source_label ? ` · ${m.source_label}` : ""}`}
              </span>
              <textarea
                className={styles.textarea}
                value={m.content_text}
                rows={4}
                autoFocus={i === 0}
                onChange={(ev) =>
                  setBuffer((current) =>
                    (current as MemoryMaterialBuffer[]).map((x, j) =>
                      j === i ? { ...x, content_text: ev.target.value } : x,
                    ),
                  )
                }
                onKeyDown={escapeCancels}
                aria-label={`业务记忆 ${i + 1} 内容`}
              />
            </label>
          ))
        ) : (
          <>
            <button
              type="button"
              className={styles.memoryToggle}
              onClick={() => setMemoryOpen((v) => !v)}
              aria-expanded={memoryOpen}
            >
              {memoryOpen ? (
                <ChevronDown size={15} aria-hidden="true" />
              ) : (
                <ChevronRight size={15} aria-hidden="true" />
              )}
              展开/收起业务记忆列表
            </button>
            <p className={styles.memoryNote}>由 Agent 自动筛选，上传时未逐条确认。</p>
            {memoryOpen ? (
              detail.memory_materials.length === 0 ? (
                <div className={styles.maskBox}>
                  <p className={styles.empty}>无业务记忆</p>
                </div>
              ) : (
                detail.memory_materials.map((m, i) => (
                  <div key={m.client_ref_id || i} className={styles.maskBox}>
                    <p className={styles.text}>{m.content_text}</p>
                  </div>
                ))
              )
            ) : null}
          </>
        )}
      </ModuleFrame>
    </div>
  );
}

interface ModuleFrameProps {
  label: string;
  moduleKey: MaterialModuleKey;
  /**
   * Whether the edit affordance is offered at all: false for empty list
   * modules (adding entries is out of scope) and gated-off questions.
   */
  editable: boolean;
  editing: boolean;
  saving: boolean;
  error: string | null;
  onEnterEdit: () => void;
  onFocusLeave: () => void;
  onCommit: () => void;
  onDiscard: () => void;
}

/**
 * One material module: hover highlights the frame and reveals the edit
 * affordance, double-click is a shortcut, and leaving the frame (blur to
 * outside) triggers the autosave commit. Focus moves INSIDE the frame never
 * commit mid-edit; the frame itself is focusable (tabIndex=-1) so clicks on
 * plain text inside stay internal and focus returns here after a save.
 */
function ModuleFrame({
  label,
  moduleKey,
  editable,
  editing,
  saving,
  error,
  onEnterEdit,
  onFocusLeave,
  onCommit,
  onDiscard,
  children,
}: React.PropsWithChildren<ModuleFrameProps>): React.JSX.Element {
  const frameRef = useRef<HTMLDivElement | null>(null);
  const wasEditingRef = useRef(false);

  // Restore focus to the frame when the textarea unmounts (autosave, Escape,
  // discard) so keyboard users keep their place.
  useEffect(() => {
    if (wasEditingRef.current && !editing) frameRef.current?.focus();
    wasEditingRef.current = editing;
  }, [editing]);

  function handleBlur(event: React.FocusEvent<HTMLDivElement>): void {
    if (!editing || saving) return;
    const next = event.relatedTarget;
    if (next instanceof Node && frameRef.current?.contains(next)) return;
    onFocusLeave();
  }

  return (
    <div
      ref={frameRef}
      tabIndex={-1}
      className={[styles.materialBlock, editing ? styles.blockEditing : null].join(" ")}
      data-module={moduleKey}
      data-editing={editing || undefined}
      onDoubleClick={() => {
        if (editable && !editing) onEnterEdit();
      }}
      onBlur={handleBlur}
    >
      <div className={styles.blockHead}>
        <h3 className={styles.blockLabel}>{label}</h3>
        {editable && !editing ? (
          <Button
            variant="ghost"
            className={styles.editButton}
            onClick={onEnterEdit}
            aria-label={`编辑${label}`}
            data-testid={`module-edit-${moduleKey}`}
          >
            <Pencil size={13} aria-hidden="true" />
            编辑
          </Button>
        ) : null}
      </div>
      {children}
      {editing ? (
        <div className={styles.moduleFooter}>
          {saving ? (
            <span className={styles.savingNote} role="status">
              保存中…
            </span>
          ) : null}
          {error && !saving ? (
            <>
              <span className={styles.errorNote} role="alert">
                {error}
              </span>
              <Button variant="ghost" onClick={onCommit} data-testid="module-retry">
                重试
              </Button>
              <Button variant="ghost" onClick={onDiscard}>
                放弃
              </Button>
            </>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
