"use client";

import { useEffect, useMemo, useState } from "react";

import { Button } from "@/src/components/ui/Button";
import { Check, Refresh } from "@/src/components/ui/Glyph";
import { Note } from "@/src/components/ui/Note";
import { ProvenanceLegend } from "@/src/features/case-builder/components/ClaimBlock";
import { DraftView } from "@/src/features/case-builder/components/DraftView";
import type { DraftContent } from "@/src/features/case-builder/services/caseBuilderService";
import type { PageFault } from "@/src/lib/api/pageFault";

import styles from "./caseBuilder.module.css";

type Requirement = { key: string; label: string; ok: boolean };

/** 确认完整性来自 case-builder 合同 §4.2，逐条在页脚显示，未满足就不放开确认按钮。 */
function requirementsFor(draft: DraftContent): Requirement[] {
  const filled = (value: string | undefined | null) => Boolean(value && value.trim());
  return [
    { key: "scenario", label: "场景摘要", ok: filled(draft.scenario.summary) },
    { key: "goal", label: "任务目标", ok: filled(draft.task_goal) },
    {
      key: "outcome",
      label: "老师认可的参考结果",
      ok: filled(draft.reference_outcome?.accepted_result),
    },
    { key: "capability", label: "主要能力", ok: filled(draft.primary_capability) },
    {
      key: "output",
      label: "至少一条输出要求",
      ok: draft.output_requirements.some((item) => filled(item)),
    },
    {
      key: "dimension",
      label: "至少一个带判定标准的维度",
      ok:
        draft.dimensions.length > 0 &&
        draft.dimensions.every((item) => filled(item.criterion) && filled(item.name)),
    },
    {
      key: "gap",
      label: "没有阻塞缺口",
      ok: (draft.unknowns ?? []).every((item) => !item.blocking),
    },
  ];
}

/** 提交前只做去空白和丢弃空行，不补内容；同一份稿子重复提交必须字节一致以命中幂等。 */
function normalize(draft: DraftContent): DraftContent {
  const keep = (values: string[] | undefined) =>
    (values ?? []).map((value) => value.trim()).filter(Boolean);
  const keepItems = <T extends { text: string }>(items: T[] | undefined) =>
    (items ?? [])
      .map((item) => ({ ...item, text: item.text.trim() }))
      .filter((item) => item.text.length > 0);

  return {
    ...draft,
    scenario: { ...draft.scenario, summary: draft.scenario.summary.trim() },
    task_goal: draft.task_goal.trim(),
    input_summary: draft.input_summary.trim(),
    output_requirements: keep(draft.output_requirements),
    prohibited_errors: keep(draft.prohibited_errors),
    reference_outcome: draft.reference_outcome
      ? {
          ...draft.reference_outcome,
          accepted_result: draft.reference_outcome.accepted_result.trim(),
          rationale: draft.reference_outcome.rationale.trim(),
        }
      : null,
    facts: keepItems(draft.facts),
    teacher_judgments: keepItems(draft.teacher_judgments),
    proposed_standards: keepItems(draft.proposed_standards),
    unknowns: keepItems(draft.unknowns),
    primary_capability: draft.primary_capability.trim(),
    dimensions: draft.dimensions.map((item) => ({
      ...item,
      name: item.name.trim(),
      criterion: item.criterion.trim(),
    })),
    tags: keep(draft.tags),
  };
}

export function DraftEditor({
  draft: serverDraft,
  draftRevision,
  busy,
  fault,
  onConfirm,
  onReload,
}: {
  draft: DraftContent;
  draftRevision: number;
  busy: boolean;
  fault: PageFault | null;
  onConfirm: (content: DraftContent) => void;
  onReload: () => void;
}) {
  const [draft, setDraft] = useState<DraftContent>(serverDraft);
  const [addedIds, setAddedIds] = useState<Set<string>>(new Set());
  const [jsonText, setJsonText] = useState("");
  const [jsonError, setJsonError] = useState("");

  // 服务端换了修订号就意味着换了一份校样，本地修改不能跨修订号残留。
  useEffect(() => {
    setDraft(serverDraft);
    setAddedIds(new Set());
    setJsonText(JSON.stringify(serverDraft, null, 2));
    setJsonError("");
  }, [serverDraft, draftRevision]);

  const requirements = useMemo(() => requirementsFor(draft), [draft]);
  const complete = requirements.every((item) => item.ok);
  const stale = fault?.code === "STALE_DRAFT" || fault?.code === "CASE_ALREADY_CONFIRMED";

  return (
    <section className="sheet">
      <div className="sheet-head">
        <div className="row-between">
          <div className="stack-sm">
            <h2 className="doc-title-sm">校样：逐条审阅，可直接改</h2>
            <p className="secondary" style={{ fontSize: "var(--t-13)" }}>
              AI 只能提出带出处的草案。左侧墨线说明每一条是谁说的，右侧是它的引注。
            </p>
          </div>
          <span className={styles.revStamp}>第 {draftRevision} 校</span>
        </div>
        <div style={{ paddingTop: "var(--s-3)" }}>
          <ProvenanceLegend />
        </div>
      </div>

      <div style={{ padding: "var(--s-2) var(--s-5) var(--s-5)" }}>
        <DraftView
          draft={draft}
          editable={{
            busy,
            addedIds,
            onAdded: (id) => setAddedIds((current) => new Set(current).add(id)),
            onChange: setDraft,
          }}
        />

        <details className={styles.jsonEscape} style={{ marginTop: "var(--s-6)" }}>
          <summary>▸ 直接编辑 JSON（提交的就是这份内容）</summary>
          <textarea
            className={styles.jsonArea}
            disabled={busy}
            onChange={(event) => setJsonText(event.target.value)}
            spellCheck={false}
            value={jsonText}
          />
          <div className="row" style={{ marginTop: "var(--s-2)" }}>
            <Button
              disabled={busy}
              onClick={() => {
                try {
                  setDraft(JSON.parse(jsonText) as DraftContent);
                  setJsonError("");
                } catch {
                  setJsonError("这段内容不是合法 JSON，表单没有改动。");
                }
              }}
              size="sm"
            >
              应用到上面的校样
            </Button>
            <Button
              disabled={busy}
              onClick={() => setJsonText(JSON.stringify(draft, null, 2))}
              size="sm"
              variant="quiet"
            >
              从校样重新载入
            </Button>
            {jsonError && <span className="field-error">{jsonError}</span>}
          </div>
        </details>
      </div>

      <div className="sheet-foot stack">
        {fault && (
          <Note
            code={fault.code}
            title={stale ? "这份校样已经不是最新的" : "确认没有被接受"}
            tone="fail"
          >
            {fault.message}
            {stale && (
              <span style={{ display: "block", marginTop: "var(--s-2)" }}>
                <Button onClick={onReload} size="sm">
                  <Refresh size={13} />
                  重新读取案例
                </Button>
              </span>
            )}
          </Note>
        )}
        <div className={styles.confirmFoot}>
          <div className="stack-sm">
            <span className="section-label">确认前必须满足</span>
            <div className={styles.checklist}>
              {requirements.map((item) => (
                <div className={styles.checkItem} key={item.key}>
                  <span
                    aria-hidden="true"
                    style={{ color: item.ok ? "var(--prov-cleared)" : "var(--ink-faint)" }}
                  >
                    {item.ok ? <Check size={13} /> : "○"}
                  </span>
                  <span style={{ color: item.ok ? "var(--ink-secondary)" : "var(--ink-muted)" }}>
                    {item.label}
                  </span>
                </div>
              ))}
            </div>
          </div>
          <div className="stack-sm" style={{ justifyItems: "start" }}>
            <Button
              busy={busy}
              busyLabel="正在确认并保存…"
              disabled={!complete}
              onClick={() => onConfirm(normalize(draft))}
              size="lg"
              variant="primary"
            >
              确认并落章
            </Button>
            <span className="mono faint">
              {complete ? "将保存一条候选用例" : "还有必填项没有满足"}
            </span>
          </div>
        </div>
      </div>
    </section>
  );
}
