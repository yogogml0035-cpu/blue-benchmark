import type { ReactNode } from "react";

import { AutoTextarea } from "@/src/components/ui/AutoTextarea";
import { Button } from "@/src/components/ui/Button";
import { Cross } from "@/src/components/ui/Glyph";
import {
  FieldRow,
  GroupSection,
  ItemText,
  SourceItem,
} from "@/src/features/case-builder/components/SourceGroup";
import type { DraftContent } from "@/src/features/case-builder/services/caseBuilderService";
import type { components } from "@/src/lib/api/generated";

import styles from "./caseDetail.module.css";

type Dimension = components["schemas"]["Dimension"];
type DimensionKind = Dimension["kind"];

const KIND_LABEL: Record<DimensionKind, string> = {
  hard_gate: "硬门槛",
  required_quality: "必要质量",
  diagnostic: "诊断",
};

export const KIND_OPTIONS = [
  { value: "hard_gate" as const, label: "硬门槛" },
  { value: "required_quality" as const, label: "必要质量" },
  { value: "diagnostic" as const, label: "诊断" },
];

/** 维度类型徽记：不表达来源，只用字重与描边区分强弱。 */
function KindBadge({ kind }: { kind: DimensionKind }) {
  return <span className={`${styles.kind} ${styles[`kind_${kind}`]}`}>{KIND_LABEL[kind]}</span>;
}

export type Editable = {
  onChange: (next: DraftContent) => void;
  /** 本次人工新增的条目 id，只存在于页面本地，不进入提交内容。 */
  addedIds: Set<string>;
  onAdded: (id: string) => void;
  busy: boolean;
};

function nextId(prefix: string, existing: { id: string }[]) {
  const used = existing
    .map((item) => Number.parseInt(item.id.replace(/^\D+/, ""), 10))
    .filter((value) => Number.isFinite(value));
  return `${prefix}-${(used.length ? Math.max(...used) : 0) + 1}`;
}

function RemoveButton({ onClick, busy, label }: { onClick: () => void; busy: boolean; label: string }) {
  return (
    <Button
      aria-label={label}
      className="btn-icon"
      disabled={busy}
      onClick={onClick}
      variant="quiet"
    >
      <Cross size={13} />
    </Button>
  );
}

function AddedBadge() {
  return <span className={styles.added}>本次新增</span>;
}

function StringRows({
  values,
  onChange,
  placeholder,
  addLabel,
  busy,
}: {
  values: string[];
  onChange: (next: string[]) => void;
  placeholder: string;
  addLabel: string;
  busy: boolean;
}) {
  return (
    <div className={styles.rows}>
      {values.map((value, index) => (
        <div className={styles.row} key={index}>
          <span className={styles.rowIndex}>{index + 1}</span>
          <input
            aria-label={`${addLabel} ${index + 1}`}
            className="control"
            disabled={busy}
            onChange={(event) => {
              const next = [...values];
              next[index] = event.target.value;
              onChange(next);
            }}
            placeholder={placeholder}
            value={value}
          />
          <RemoveButton
            busy={busy}
            label={`删除第 ${index + 1} 条`}
            onClick={() => onChange(values.filter((_, position) => position !== index))}
          />
        </div>
      ))}
      <div>
        <Button disabled={busy} onClick={() => onChange([...values, ""])} size="sm">
          添加{addLabel}
        </Button>
      </div>
    </div>
  );
}

function StringList({ values, empty }: { values: string[]; empty: string }) {
  if (values.length === 0) return <ItemText>{empty}</ItemText>;
  return (
    <ol className={styles.rows}>
      {values.map((value, index) => (
        <li className={styles.row} key={index} style={{ gridTemplateColumns: "18px 1fr" }}>
          <span className={styles.rowIndex}>{index + 1}</span>
          <span className={styles.fieldText}>{value}</span>
        </li>
      ))}
    </ol>
  );
}

/**
 * 标准草稿：读和改共用同一份结构与字段顺序，
 * 避免确认稿和只读快照长成两个不同的东西。
 */
export function DraftView({
  draft,
  editable,
}: {
  draft: DraftContent;
  editable?: Editable;
}) {
  const busy = editable?.busy ?? false;
  const patch = (next: Partial<DraftContent>) => editable?.onChange({ ...draft, ...next });
  const added = (id: string) => editable?.addedIds.has(id) ?? false;
  const addedBadge = (id: string) => (added(id) ? <AddedBadge /> : undefined);

  const facts = draft.facts ?? [];
  const judgments = draft.teacher_judgments ?? [];
  const proposals = draft.proposed_standards ?? [];
  const unknowns = draft.unknowns ?? [];
  const tags = draft.tags ?? [];

  return (
    <div className={styles.groups}>
      <GroupSection title="任务与要求">
        <FieldRow label="场景摘要" refs={draft.scenario.evidence_refs ?? []}>
          {editable ? (
            <AutoTextarea
              aria-label="场景摘要"
              className="control"
              disabled={busy}
              onChange={(event) =>
                patch({ scenario: { ...draft.scenario, summary: event.target.value } })
              }
              value={draft.scenario.summary}
            />
          ) : (
            <ItemText>{draft.scenario.summary}</ItemText>
          )}
        </FieldRow>

        <FieldRow label="任务目标">
          {editable ? (
            <AutoTextarea
              aria-label="任务目标"
              className="control"
              disabled={busy}
              onChange={(event) => patch({ task_goal: event.target.value })}
              value={draft.task_goal}
            />
          ) : (
            <ItemText>{draft.task_goal}</ItemText>
          )}
        </FieldRow>

        <FieldRow label="材料概述">
          {editable ? (
            <AutoTextarea
              aria-label="材料概述"
              className="control"
              disabled={busy}
              onChange={(event) => patch({ input_summary: event.target.value })}
              value={draft.input_summary}
            />
          ) : (
            <ItemText>{draft.input_summary}</ItemText>
          )}
        </FieldRow>

        <FieldRow label="主要能力">
          {editable ? (
            <input
              aria-label="主要能力"
              className="control"
              disabled={busy}
              onChange={(event) => patch({ primary_capability: event.target.value })}
              value={draft.primary_capability}
            />
          ) : (
            <ItemText>{draft.primary_capability}</ItemText>
          )}
        </FieldRow>

        <FieldRow label="输出要求">
          {editable ? (
            <StringRows
              addLabel="输出要求"
              busy={busy}
              onChange={(next) => patch({ output_requirements: next })}
              placeholder="例如：交付 Markdown 正文"
              values={draft.output_requirements}
            />
          ) : (
            <StringList empty="未列出" values={draft.output_requirements} />
          )}
        </FieldRow>

        <FieldRow label="禁止的错误">
          {editable ? (
            <StringRows
              addLabel="禁止项"
              busy={busy}
              onChange={(next) => patch({ prohibited_errors: next })}
              placeholder="例如：不得编造产品参数"
              values={draft.prohibited_errors ?? []}
            />
          ) : (
            <StringList empty="未列出" values={draft.prohibited_errors ?? []} />
          )}
        </FieldRow>

        <FieldRow label="参考结果" refs={draft.reference_outcome?.evidence_refs ?? []}>
          {editable ? (
            <div className="stack-sm">
              <AutoTextarea
                aria-label="老师认可的结果"
                className="control"
                disabled={busy}
                onChange={(event) =>
                  patch({
                    reference_outcome: {
                      accepted_result: event.target.value,
                      rationale: draft.reference_outcome?.rationale ?? "",
                      evidence_refs: draft.reference_outcome?.evidence_refs ?? [],
                    },
                  })
                }
                placeholder="老师认可的完整结果"
                value={draft.reference_outcome?.accepted_result ?? ""}
              />
              <AutoTextarea
                aria-label="认可原因"
                className="control"
                disabled={busy}
                onChange={(event) =>
                  patch({
                    reference_outcome: {
                      accepted_result: draft.reference_outcome?.accepted_result ?? "",
                      rationale: event.target.value,
                      evidence_refs: draft.reference_outcome?.evidence_refs ?? [],
                    },
                  })
                }
                placeholder="认可或否定的原因"
                value={draft.reference_outcome?.rationale ?? ""}
              />
            </div>
          ) : draft.reference_outcome ? (
            <div className="stack-sm">
              <ItemText>{draft.reference_outcome.accepted_result}</ItemText>
              <p className="secondary" style={{ fontSize: "var(--t-14)" }}>
                因为：{draft.reference_outcome.rationale}
              </p>
            </div>
          ) : (
            <ItemText>尚未确定参考结果。</ItemText>
          )}
        </FieldRow>
      </GroupSection>

      {/* ================= 事实（输入里明确存在） ================= */}
      <GroupSection
        aside={<span className="mono faint">{facts.length} 条</span>}
        title="事实（输入里明确存在）"
      >{facts.length === 0 ? (
          <p className="muted" style={{ fontSize: "var(--t-14)" }}>
            未提取到事实。
          </p>
        ) : (
          facts.map((fact, index) => (
            <SourceItem
              actions={
                editable ? (
                  <RemoveButton
                    busy={busy}
                    label={`删除事实 ${index + 1}`}
                    onClick={() =>
                      patch({ facts: facts.filter((item) => item.id !== fact.id) })
                    }
                  />
                ) : undefined
              }
              badge={addedBadge(fact.id)}
              key={fact.id}
              refs={fact.evidence_refs ?? []}
            >
              {editable ? (
                <AutoTextarea
                  aria-label={`事实 ${index + 1}`}
                  className="control"
                  disabled={busy}
                  onChange={(event) =>
                    patch({
                      facts: facts.map((item) =>
                        item.id === fact.id ? { ...item, text: event.target.value } : item,
                      ),
                    })
                  }
                  value={fact.text}
                />
              ) : (
                <ItemText>{fact.text}</ItemText>
              )}
            </SourceItem>
          ))
        )}
      </GroupSection>

      {/* ================= 你的判断 ================= */}
      <GroupSection
        aside={
          editable && (
            <Button
              disabled={busy}
              onClick={() => {
                const id = nextId("judgment", judgments);
                editable.onAdded(id);
                patch({ teacher_judgments: [...judgments, { id, text: "", evidence_refs: [] }] });
              }}
              size="sm"
            >
              添加判断
            </Button>
          )
        }
        title="你的判断"
      >
        {judgments.length === 0 ? (
          <p className="muted" style={{ fontSize: "var(--t-14)" }}>
            尚无老师判断。
          </p>
        ) : (
          judgments.map((judgment, index) => (
            <SourceItem
              actions={
                editable ? (
                  <RemoveButton
                    busy={busy}
                    label={`删除判断 ${index + 1}`}
                    onClick={() =>
                      patch({
                        teacher_judgments: judgments.filter((item) => item.id !== judgment.id),
                      })
                    }
                  />
                ) : undefined
              }
              badge={addedBadge(judgment.id)}
              key={judgment.id}
              refs={judgment.evidence_refs ?? []}
            >
              {editable ? (
                <AutoTextarea
                  aria-label={`判断 ${index + 1}`}
                  className="control"
                  disabled={busy}
                  onChange={(event) =>
                    patch({
                      teacher_judgments: judgments.map((item) =>
                        item.id === judgment.id ? { ...item, text: event.target.value } : item,
                      ),
                    })
                  }
                  placeholder="你明确表达的判断"
                  value={judgment.text}
                />
              ) : (
                <ItemText>{judgment.text}</ItemText>
              )}
            </SourceItem>
          ))
        )}
      </GroupSection>

      {/* ================= AI 推断的候选标准 ================= */}
      <GroupSection
        aside={<span className="mono faint">等待你取舍</span>}
        title="AI 推断的候选标准"
      >
        {proposals.length === 0 ? (
          <p className="muted" style={{ fontSize: "var(--t-14)" }}>
            AI 没有额外的候选标准。
          </p>
        ) : (
          proposals.map((proposal, index) => (
            <SourceItem
              actions={
                editable ? (
                  <RemoveButton
                    busy={busy}
                    label={`删除候选标准 ${index + 1}`}
                    onClick={() =>
                      patch({
                        proposed_standards: proposals.filter((item) => item.id !== proposal.id),
                      })
                    }
                  />
                ) : undefined
              }
              key={proposal.id}
              refs={proposal.evidence_refs ?? []}
            >
              {editable ? (
                <AutoTextarea
                  aria-label={`候选标准 ${index + 1}`}
                  className="control"
                  disabled={busy}
                  onChange={(event) =>
                    patch({
                      proposed_standards: proposals.map((item) =>
                        item.id === proposal.id ? { ...item, text: event.target.value } : item,
                      ),
                    })
                  }
                  value={proposal.text}
                />
              ) : (
                <ItemText>{proposal.text}</ItemText>
              )}
            </SourceItem>
          ))
        )}
      </GroupSection>

      {/* ================= 证据缺口 ================= */}
      <GroupSection
        aside={<span className="mono faint">保留未知，不伪装成事实</span>}
        title="证据缺口"
      >
        {unknowns.length === 0 ? (
          <p className="muted" style={{ fontSize: "var(--t-14)" }}>
            没有登记的缺口。
          </p>
        ) : (
          unknowns.map((unknown, index) => (
            <SourceItem
              actions={
                editable ? (
                  <RemoveButton
                    busy={busy}
                    label={`移除缺口 ${index + 1}`}
                    onClick={() =>
                      patch({ unknowns: unknowns.filter((item) => item.id !== unknown.id) })
                    }
                  />
                ) : undefined
              }
              badge={
                unknown.blocking ? (
                  <span className="state state-amber">
                    <span className="dot" />
                    阻塞
                  </span>
                ) : undefined
              }
              key={unknown.id}
            >
              {editable ? (
                <div className="stack-sm">
                  <AutoTextarea
                    aria-label={`缺口 ${index + 1}`}
                    className="control"
                    disabled={busy}
                    onChange={(event) =>
                      patch({
                        unknowns: unknowns.map((item) =>
                          item.id === unknown.id ? { ...item, text: event.target.value } : item,
                        ),
                      })
                    }
                    value={unknown.text}
                  />
                  {unknown.blocking && (
                    <p className="field-error">
                      阻塞缺口必须先解决：补进事实或判断后移除这一条，才能确认。
                    </p>
                  )}
                </div>
              ) : (
                <ItemText>{unknown.text}</ItemText>
              )}
            </SourceItem>
          ))
        )}
      </GroupSection>

      {/* ================= 判定维度 ================= */}
      <GroupSection
        aside={
          <span className="row" style={{ gap: "var(--s-3)" }}>
            <span className="mono faint">{draft.dimensions.length} 个</span>
            {editable && (
              <Button
                disabled={busy}
                onClick={() => {
                  const id = nextId("dimension", draft.dimensions);
                  editable.onAdded(id);
                  patch({
                    dimensions: [
                      ...draft.dimensions,
                      { id, name: "", kind: "required_quality", criterion: "", evidence_refs: [] },
                    ],
                  });
                }}
                size="sm"
              >
                新增维度
              </Button>
            )}
          </span>
        }
        title="判定维度"
      >
        {draft.dimensions.map((dimension, index) => (
          <SourceItem
            actions={
              editable ? (
                <RemoveButton
                  busy={busy}
                  label={`删除维度 ${index + 1}`}
                  onClick={() =>
                    patch({
                      dimensions: draft.dimensions.filter((item) => item.id !== dimension.id),
                    })
                  }
                />
              ) : undefined
            }
            badge={
              <>
                <KindBadge kind={dimension.kind} />
                {editable && addedBadge(dimension.id)}
              </>
            }
            key={dimension.id}
            refs={dimension.evidence_refs ?? []}
          >
            {editable ? (
              <div className={styles.dimension}>
                <div className={styles.dimensionHead}>
                  <input
                    aria-label={`维度 ${index + 1} 名称`}
                    className="control"
                    disabled={busy}
                    onChange={(event) =>
                      patch({
                        dimensions: draft.dimensions.map((item) =>
                          item.id === dimension.id ? { ...item, name: event.target.value } : item,
                        ),
                      })
                    }
                    placeholder="维度名称，例如 事实准确性"
                    style={{ flex: "1 1 200px", width: "auto" }}
                    value={dimension.name}
                  />
                  <div className="segmented" role="group">
                    {KIND_OPTIONS.map((option) => (
                      <button
                        aria-pressed={dimension.kind === option.value}
                        className="segmented-item"
                        disabled={busy}
                        key={option.value}
                        onClick={() =>
                          patch({
                            dimensions: draft.dimensions.map((item) =>
                              item.id === dimension.id ? { ...item, kind: option.value } : item,
                            ),
                          })
                        }
                        type="button"
                      >
                        {option.label}
                      </button>
                    ))}
                  </div>
                </div>
                <AutoTextarea
                  aria-label={`维度 ${index + 1} 判定标准`}
                  className="control"
                  disabled={busy}
                  onChange={(event) =>
                    patch({
                      dimensions: draft.dimensions.map((item) =>
                        item.id === dimension.id
                          ? { ...item, criterion: event.target.value }
                          : item,
                      ),
                    })
                  }
                  placeholder="怎样才算通过"
                  value={dimension.criterion}
                />
              </div>
            ) : (
              <div className="stack-sm">
                <span className={styles.fieldText} style={{ fontWeight: 550 }}>
                  {dimension.name || `维度 ${index + 1}`}
                </span>
                <ItemText>{dimension.criterion}</ItemText>
              </div>
            )}
          </SourceItem>
        ))}
      </GroupSection>

      {/* ================= 标签 ================= */}
      <GroupSection title="标签">
        {editable ? (
          <div className={styles.tags}>
            {tags.map((tag, index) => (
              <span className={styles.tag} key={index}>
                {tag}
                <Button
                  aria-label={`删除标签 ${tag}`}
                  className="btn-icon"
                  disabled={busy}
                  onClick={() => patch({ tags: tags.filter((_, position) => position !== index) })}
                  variant="quiet"
                >
                  <Cross size={11} />
                </Button>
              </span>
            ))}
            <input
              aria-label="新增标签"
              className="control"
              disabled={busy}
              onKeyDown={(event) => {
                if (event.key !== "Enter") return;
                event.preventDefault();
                const value = event.currentTarget.value.trim();
                if (!value || tags.includes(value)) return;
                patch({ tags: [...tags, value] });
                event.currentTarget.value = "";
              }}
              placeholder="输入后回车"
              style={{ width: 160 }}
            />
          </div>
        ) : tags.length ? (
          <div className={styles.tags}>
            {tags.map((tag) => (
              <span className={styles.tagRead} key={tag}>
                {tag}
              </span>
            ))}
          </div>
        ) : (
          <p className="muted" style={{ fontSize: "var(--t-14)" }}>
            无标签。
          </p>
        )}
      </GroupSection>
    </div>
  );
}
