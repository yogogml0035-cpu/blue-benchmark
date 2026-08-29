"use client";

import { useEffect, useMemo, useState } from "react";

import { Button } from "@/src/components/ui/Button";
import { Note } from "@/src/components/ui/Note";
import {
  DraftView,
  type DraftSection,
  type Editable,
} from "@/src/features/case-builder/components/DraftView";
import type { DraftContent } from "@/src/features/case-builder/services/caseBuilderService";
import type { PageFault } from "@/src/lib/api/pageFault";

import styles from "./caseDetail.module.css";

type Requirement = { key: string; label: string; ok: boolean };

/** 定稿完整性来自 case-builder 合同 §4.2；不满足时只在定稿按钮下写一句缺什么。 */
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
      label: "每个维度都有名称和判定标准",
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

type SectionKey = DraftSection | "sign";

const SECTIONS: { key: SectionKey; label: string }[] = [
  { key: "summary", label: "场景摘要" },
  { key: "goal", label: "任务与要求" },
  { key: "outcome", label: "参考结果" },
  { key: "sources", label: "来源 · 事实与判断" },
  { key: "dimensions", label: "判定维度" },
  { key: "gaps", label: "证据缺口" },
  { key: "tags", label: "标签" },
  { key: "sign", label: "定稿" },
];

/**
 * 聚焦阅读器：题稿一屏一节，最后一节是定稿卡。
 * 刻度可点，→/空格 下一节，← 上一节。读和改同构（DraftView），
 * 修改发生在当前节内，不打断节奏。
 */
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
  const [index, setIndex] = useState(0);
  const [jsonOpen, setJsonOpen] = useState(false);
  const [jsonText, setJsonText] = useState("");
  const [jsonError, setJsonError] = useState("");

  // 服务端换了修订号就意味着换了一份题稿，本地修改不跨修订号残留。
  useEffect(() => {
    setDraft(serverDraft);
    setAddedIds(new Set());
    setJsonText(JSON.stringify(serverDraft, null, 2));
    setJsonError("");
    setIndex(0);
  }, [serverDraft, draftRevision]);

  const requirements = useMemo(() => requirementsFor(draft), [draft]);
  const complete = requirements.every((item) => item.ok);
  const missing = requirements.filter((item) => !item.ok).map((item) => item.label);
  const stale = fault?.code === "STALE_DRAFT" || fault?.code === "CASE_ALREADY_CONFIRMED";

  const section = SECTIONS[index];
  const editable: Editable = useMemo(
    () => ({
      busy,
      addedIds,
      onAdded: (id) => setAddedIds((current) => new Set(current).add(id)),
      onChange: setDraft,
    }),
    [addedIds, busy],
  );

  // 键盘：→/空格 下一节，← 上一节。输入框聚焦时不抢按键。
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement;
      if (/^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName) || target.isContentEditable) return;
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      if (event.key === "ArrowRight" || event.key === " ") {
        event.preventDefault();
        setIndex((i) => Math.min(i + 1, SECTIONS.length - 1));
      } else if (event.key === "ArrowLeft") {
        event.preventDefault();
        setIndex((i) => Math.max(i - 1, 0));
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  return (
    <section className={styles.focus} aria-label="题稿审读">
      <nav aria-label="阅读进度" className={styles.ticks}>
        {SECTIONS.map((item, i) => (
          <button
            aria-current={i === index || undefined}
            aria-label={item.label}
            className={styles.tick}
            data-state={i < index ? "done" : i === index ? "active" : "pending"}
            key={item.key}
            onClick={() => setIndex(i)}
            type="button"
          />
        ))}
      </nav>

      <div className={styles.focusCard} key={section.key}>
        <p className={styles.focusCount}>
          {index + 1} / {SECTIONS.length}
        </p>
        <h2 className={styles.focusTitle}>{section.label}</h2>

        {section.key !== "sign" ? (
          <div className={styles.focusBody}>
            <DraftView draft={draft} editable={editable} section={section.key} />
          </div>
        ) : (
          <div className={styles.focusBody}>
            <p className={styles.signLead}>
              以上 {SECTIONS.length - 1} 节，题 v{draftRevision}。
            </p>
            <p className={styles.signSub}>读完了，就把这份题收进场景，往后每次改版拿它对照。</p>

            {fault && (
              <Note
                code={fault.code}
                title={stale ? "这份题稿已经不是最新的" : "定稿没有被接受"}
                tone="fail"
              >
                {fault.message}
                {stale && (
                  <span style={{ display: "block", marginTop: "var(--s-2)" }}>
                    <Button onClick={onReload} size="sm">
                      重新读取案例
                    </Button>
                  </span>
                )}
              </Note>
            )}

            <details
              className={styles.jsonEscape}
              onToggle={(event) => setJsonOpen(event.currentTarget.open)}
              open={jsonOpen}
            >
              <summary>直接编辑 JSON（提交的就是这份内容）</summary>
              <textarea
                aria-label="题稿 JSON"
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
                      setJsonError("这段内容不是合法 JSON，题稿没有改动。");
                    }
                  }}
                  size="sm"
                >
                  应用到题稿
                </Button>
                <Button
                  disabled={busy}
                  onClick={() => setJsonText(JSON.stringify(draft, null, 2))}
                  size="sm"
                  variant="quiet"
                >
                  从题稿重新载入
                </Button>
                {jsonError && <span className="field-error">{jsonError}</span>}
              </div>
            </details>

            <div className={styles.signLine}>
              <span className={styles.signHint}>
                {complete ? "读完了，定稿。" : `还差：${missing.join("、")}`}
              </span>
              <Button
                busy={busy}
                busyLabel="正在定稿…"
                disabled={!complete}
                onClick={() => onConfirm(normalize(draft))}
                size="lg"
                variant="primary"
              >
                定稿
              </Button>
            </div>
          </div>
        )}

        <footer className={styles.focusFoot}>
          {index > 0 ? (
            <button className={styles.focusQuiet} onClick={() => setIndex(index - 1)} type="button">
              上一节
            </button>
          ) : (
            <span />
          )}
          {section.key !== "sign" && (
            <button className={styles.focusNext} onClick={() => setIndex(index + 1)} type="button">
              {index === SECTIONS.length - 2 ? "读完，去定稿" : "下一节"}
            </button>
          )}
        </footer>
      </div>
    </section>
  );
}
