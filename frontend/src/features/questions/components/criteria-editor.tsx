"use client";

import { ChevronDown, ChevronRight, Plus, Trash2 } from "lucide-react";
import { useLayoutEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  MAX_ANCHORS,
  MAX_PASS_SCORE,
  hasStaleExplanation,
  newManualDraft,
  type CriterionDraft,
} from "../criterion-draft";
import type { BasisClaimView, CriterionPatchRequest, CriterionView, QuestionDetailResponse } from "../api";
import styles from "./criteria-editor.module.css";

/** Field-level autosave payload (the caller adds content_revision). */
export type CriterionFieldPatch = Omit<CriterionPatchRequest, "content_revision">;

/**
 * Textarea that always grows to fit its full content, so a criterion is never
 * hidden behind a fixed-height scroll box. Re-measures on value changes and on
 * element resizes (e.g. the sidebar width transition re-wrapping text).
 */
function AutoGrowTextarea({ value, ...rest }: React.TextareaHTMLAttributes<HTMLTextAreaElement>): React.JSX.Element {
  const ref = useRef<HTMLTextAreaElement | null>(null);

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const grow = () => {
      el.style.height = "auto";
      const border = el.offsetHeight - el.clientHeight;
      el.style.height = `${el.scrollHeight + border}px`;
    };
    grow();
    const observer = new ResizeObserver(grow);
    observer.observe(el);
    return () => observer.disconnect();
  }, [value]);

  return <textarea ref={ref} value={value} {...rest} />;
}

function ClaimRow({ claim }: { claim: BasisClaimView }): React.JSX.Element {
  return (
    <li className={styles.claim}>
      <span
        className={claim.kind === "teacher_explicit" ? styles.claimTeacher : styles.claimInferred}
      >
        {claim.kind === "teacher_explicit" ? "老师明确要求" : "AI 推定"}
      </span>
      <span className={styles.claimText}>{claim.claim}</span>
      {claim.citation ? (
        <span className={styles.citation}>
          <code className={styles.citationLocator}>{claim.citation.locator}</code>
          <span className={styles.citationQuote}>“{claim.citation.quote}”</span>
        </span>
      ) : null}
    </li>
  );
}

export interface CriteriaEditorProps {
  drafts: CriterionDraft[];
  /** Current server truth; the autosave baseline for every field. */
  detail: QuestionDetailResponse;
  onChange: (updater: (drafts: CriterionDraft[]) => CriterionDraft[]) => void;
  /** Marks the SELECTION as needing the explicit 保存维度 commit. */
  onSelectionDirty: () => void;
  /**
   * Field autosave for AI criteria (blur-triggered). Manual criteria are not
   * persisted yet (404) and ride the next 保存维度 instead.
   */
  onSaveFields: (criterionId: string, patch: CriterionFieldPatch) => Promise<void>;
  /** Per-criterion autosave error messages, keyed by criterion id. */
  fieldErrors?: Record<string, string | null>;
  /** When true the list is read-only (published question). */
  readOnly?: boolean;
}

export function CriteriaEditor({
  drafts,
  detail,
  onChange,
  onSelectionDirty,
  onSaveFields,
  fieldErrors,
  readOnly = false,
}: CriteriaEditorProps): React.JSX.Element {
  const selectedCount = drafts.filter((d) => d.selected).length;
  const [basisOpen, setBasisOpen] = useState<Record<string, boolean>>({});

  function patchAt(index: number, patch: Partial<CriterionDraft>): void {
    onChange((list) => list.map((d, i) => (i === index ? { ...d, ...patch } : d)));
  }

  function addManual(): void {
    onChange((list) => [...list, newManualDraft(new Set(list.map((d) => d.id)))]);
    onSelectionDirty();
  }

  function removeCriterion(index: number): void {
    onChange((list) => list.filter((_, j) => j !== index));
    onSelectionDirty();
  }

  function baselineFor(id: string): CriterionView | undefined {
    return detail.criteria?.find((c) => c.id === id);
  }

  /**
   * Selection never gates editing (checkbox = binding only). AI criteria
   * autosave their edited fields on blur; manual criteria have no server row
   * yet and ride the explicit 保存维度 commit.
   */
  function commitText(d: CriterionDraft): void {
    if (readOnly) return;
    if (d.source !== "ai") {
      onSelectionDirty();
      return;
    }
    const base = baselineFor(d.id);
    if (base && base.criterion === d.criterion) return;
    void onSaveFields(d.id, { criterion: d.criterion });
  }

  function commitScore(d: CriterionDraft): void {
    if (readOnly) return;
    if (d.source !== "ai") {
      onSelectionDirty();
      return;
    }
    const base = baselineFor(d.id);
    if (base && base.pass_score === d.pass_score) return;
    void onSaveFields(d.id, { pass_score: d.pass_score });
  }

  function commitAnchors(d: CriterionDraft, list?: CriterionDraft["score_anchors"]): void {
    if (readOnly) return;
    if (d.source !== "ai") {
      onSelectionDirty();
      return;
    }
    const anchors = list ?? d.score_anchors;
    // Blank descriptions are invalid server-side; keep them local until the
    // teacher fills them in (validateSelected reports them on 保存维度).
    if (anchors.some((a) => !a.description.trim())) return;
    const base = baselineFor(d.id);
    if (
      base &&
      JSON.stringify(base.score_anchors) === JSON.stringify(anchors)
    ) {
      return;
    }
    void onSaveFields(d.id, {
      score_anchors: anchors.map((a) => ({ score: a.score, description: a.description })),
    });
  }

  function patchAnchor(index: number, anchorIndex: number, patch: { score?: number; description?: string }): void {
    onChange((list) =>
      list.map((d, i) =>
        i === index
          ? {
              ...d,
              score_anchors: d.score_anchors.map((a, j) => (j === anchorIndex ? { ...a, ...patch } : a)),
            }
          : d,
      ),
    );
  }

  function addAnchor(index: number): void {
    onChange((list) =>
      list.map((d, i) => {
        if (i !== index) return d;
        const used = new Set(d.score_anchors.map((a) => a.score));
        let score = 0;
        while (used.has(score) && score <= MAX_PASS_SCORE) score += 1;
        return { ...d, score_anchors: [...d.score_anchors, { score: Math.min(score, MAX_PASS_SCORE), description: "" }] };
      }),
    );
    // A brand-new anchor has a blank description, which the backend rejects:
    // it stays local until filled in and committed by the next blur.
  }

  function removeAnchor(index: number, anchorIndex: number): void {
    // Compute the remaining list from the CURRENT drafts synchronously — a
    // setState updater is not guaranteed to run before the lines below, and
    // reading it lazily could autosave an empty anchor list (server-side wipe).
    const draft = drafts[index];
    const remaining = draft.score_anchors.filter((_, j) => j !== anchorIndex);
    onChange((list) =>
      list.map((d, i) => (i === index ? { ...d, score_anchors: remaining } : d)),
    );
    if (draft.source === "ai" && !readOnly && !remaining.some((a) => !a.description.trim())) {
      void onSaveFields(draft.id, {
        score_anchors: remaining.map((a) => ({ score: a.score, description: a.description })),
      });
    } else if (draft.source !== "ai") {
      onSelectionDirty();
    }
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
        {drafts.map((d, i) => {
          const stale = hasStaleExplanation(d);
          const open = basisOpen[d.id] ?? false;
          const hasBasis = d.criterion_basis !== null || d.pass_score_basis !== null;
          return (
            <li key={d.id} className={[styles.item, d.selected ? styles.itemSelected : null].join(" ")}>
              <div className={styles.itemHead}>
                <label className={styles.check}>
                  <input
                    type="checkbox"
                    checked={d.selected}
                    disabled={readOnly || d.source === "manual"}
                    onChange={(e) => {
                      patchAt(i, { selected: e.target.checked });
                      onSelectionDirty();
                    }}
                    aria-label={`选择维度 ${d.id}`}
                  />
                  <span className={styles.source}>
                    {d.source === "ai" ? "AI 候选" : "手工（不参与勾选，删除即移除）"}
                  </span>
                </label>
                <label className={styles.score}>
                  <span className={styles.scoreLabel}>通过分</span>
                  <input
                    type="number"
                    min={0}
                    max={MAX_PASS_SCORE}
                    step={1}
                    value={d.pass_score}
                    disabled={readOnly}
                    onChange={(e) => {
                      const n = Number(e.target.value);
                      patchAt(i, { pass_score: Number.isFinite(n) ? Math.round(n) : 0 });
                    }}
                    onBlur={() => commitScore(d)}
                    aria-label={`维度 ${d.id} 的通过分`}
                  />
                  <span className={styles.scoreMax}>/ {MAX_PASS_SCORE}</span>
                </label>
                {!readOnly ? (
                  <Button
                    variant="ghost"
                    className={styles.deleteButton}
                    onClick={() => removeCriterion(i)}
                    aria-label={`删除维度 ${d.id}`}
                  >
                    <Trash2 size={14} aria-hidden="true" />
                  </Button>
                ) : null}
              </div>

              {stale ? (
                <p className={styles.staleNote} role="status">
                  原通过分依据对应 {d.pass_score_basis?.explained_score} 分，当前通过分为 {d.pass_score}{" "}
                  分；已保留原说明，请核对并按需修改依据或锚点。
                </p>
              ) : null}

              {fieldErrors?.[d.id] ? (
                <p className={styles.fieldError} role="alert">
                  {fieldErrors[d.id]}
                </p>
              ) : null}

              <AutoGrowTextarea
                className={styles.criterion}
                value={d.criterion}
                readOnly={readOnly}
                placeholder="完整、可执行的评分标准…"
                onChange={(e) => patchAt(i, { criterion: e.target.value })}
                onBlur={() => commitText(d)}
                aria-label={`维度 ${d.id} 的评分标准`}
              />

              <section className={styles.anchors} aria-label={`维度 ${d.id} 的分数说明`}>
                <div className={styles.sectionHead}>
                  <h3 className={styles.sectionTitle}>分数表现说明</h3>
                  {!readOnly && d.score_anchors.length < MAX_ANCHORS ? (
                    <Button variant="ghost" className={styles.addAnchor} onClick={() => addAnchor(i)}>
                      <Plus size={13} aria-hidden="true" />
                      添加分数说明
                    </Button>
                  ) : null}
                </div>
                {d.score_anchors.length === 0 ? (
                  <p className={styles.empty}>
                    暂无分数说明{d.pass_score_basis ? "（依据仍可解释建议分）" : ""}。锚点只是辅助理解，通过分可填任意 0–10 整数。
                  </p>
                ) : null}
                <ul className={styles.anchorList}>
                  {d.score_anchors.map((anchor, j) => (
                    <li key={`${d.id}-anchor-${j}`} className={styles.anchorRow}>
                      <label className={styles.anchorScore}>
                        <input
                          type="number"
                          min={0}
                          max={MAX_PASS_SCORE}
                          step={1}
                          value={anchor.score}
                          disabled={readOnly}
                          onChange={(e) => {
                            const n = Number(e.target.value);
                            patchAnchor(i, j, { score: Number.isFinite(n) ? Math.round(n) : 0 });
                          }}
                          onBlur={() => commitAnchors(d)}
                          aria-label={`维度 ${d.id} 锚点 ${j + 1} 的分数`}
                        />
                        <span className={styles.scoreMax}>分</span>
                      </label>
                      <AutoGrowTextarea
                        className={styles.anchorDescription}
                        value={anchor.description}
                        readOnly={readOnly}
                        placeholder="该分数对应的可观察表现…"
                        onChange={(e) => patchAnchor(i, j, { description: e.target.value })}
                        onBlur={() => commitAnchors(d)}
                        aria-label={`维度 ${d.id} 锚点 ${j + 1} 的表现描述`}
                      />
                      {!readOnly ? (
                        <Button
                          variant="ghost"
                          className={styles.deleteButton}
                          onClick={() => removeAnchor(i, j)}
                          aria-label={`删除维度 ${d.id} 的锚点 ${j + 1}`}
                        >
                          <Trash2 size={13} aria-hidden="true" />
                        </Button>
                      ) : null}
                    </li>
                  ))}
                </ul>
              </section>

              {hasBasis ? (
                <section className={styles.basis}>
                  <button
                    type="button"
                    className={styles.basisToggle}
                    aria-expanded={open}
                    onClick={() => setBasisOpen((prev) => ({ ...prev, [d.id]: !open }))}
                  >
                    {open ? <ChevronDown size={14} aria-hidden="true" /> : <ChevronRight size={14} aria-hidden="true" />}
                    查看依据
                  </button>
                  {open ? (
                    <div className={styles.basisBody}>
                      {d.criterion_basis ? (
                        <div className={styles.basisBlock}>
                          <h4 className={styles.basisTitle}>为什么设这个维度</h4>
                          <p className={styles.basisExplanation}>{d.criterion_basis.explanation}</p>
                          <ul className={styles.claims}>
                            {d.criterion_basis.claims.map((claim, j) => (
                              <ClaimRow key={`${d.id}-cb-${j}`} claim={claim} />
                            ))}
                          </ul>
                        </div>
                      ) : null}
                      {d.pass_score_basis ? (
                        <div className={styles.basisBlock}>
                          <h4 className={styles.basisTitle}>
                            为什么建议 {d.pass_score_basis.explained_score} 分
                            {d.pass_score_basis.explained_score !== d.pass_score
                              ? `（当前通过分已改为 ${d.pass_score} 分，请核对）`
                              : null}
                          </h4>
                          <p className={styles.basisExplanation}>{d.pass_score_basis.explanation}</p>
                          <ul className={styles.claims}>
                            {d.pass_score_basis.claims.map((claim, j) => (
                              <ClaimRow key={`${d.id}-pb-${j}`} claim={claim} />
                            ))}
                          </ul>
                        </div>
                      ) : null}
                    </div>
                  ) : null}
                </section>
              ) : null}
            </li>
          );
        })}
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
