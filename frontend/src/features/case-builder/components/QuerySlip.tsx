import { type FormEvent, useState } from "react";

import { AutoTextarea } from "@/src/components/ui/AutoTextarea";
import { Button } from "@/src/components/ui/Button";
import { Note } from "@/src/components/ui/Note";
import type { components } from "@/src/lib/api/generated";
import type { PageFault } from "@/src/lib/api/pageFault";

import styles from "./caseBuilder.module.css";

type PendingQuestion = components["schemas"]["PendingQuestion"];

/**
 * 追问单：任一时刻只允许一个待答问题，所以这张单子上永远只有一个问题、
 * 一条提问原因和一个回答框。提交期间输入和按钮一起禁用，避免重复恢复同一个会话。
 */
export function QuerySlip({
  question,
  busy,
  fault,
  onSubmit,
}: {
  question: PendingQuestion;
  busy: boolean;
  fault: PageFault | null;
  onSubmit: (answer: string) => void;
}) {
  const [answer, setAnswer] = useState("");
  const ready = answer.trim().length > 0;

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!ready) return;
    onSubmit(answer.trim());
  }

  return (
    <section className={`${styles.slip} enter`}>
      <div className={styles.slipHead}>
        <div className="spread">
          <span className="state state-gap">
            <span className="dot pulse-dot" />
            AI 提出一个问题
          </span>
          <span className="mono" style={{ color: "rgb(125 86 22 / 70%)" }}>
            {question.id.slice(0, 8)}
          </span>
        </div>
        <h2 className={styles.slipQuestion}>{question.text}</h2>
        <p className={styles.slipReason}>为什么问：{question.reason}</p>
      </div>
      <form className={styles.slipBody} onSubmit={submit}>
        <label className="field">
          <span className="field-label">
            <span>你的回答</span>
            <span className="field-hint">
              1–10000 字 · {answer.trim().length}
            </span>
          </span>
          <AutoTextarea
            autoFocus
            className="control control-doc"
            disabled={busy}
            maxLength={10000}
            minRows={3}
            onChange={(event) => setAnswer(event.target.value)}
            placeholder="直接写清楚哪一个结果是你最终认可的，以及为什么。"
            style={{ background: "var(--paper-raised)" }}
            value={answer}
          />
        </label>
        {fault && (
          <Note code={fault.code} title="这条回答没有被接受" tone="fail">
            {fault.message}
          </Note>
        )}
        <div className="row">
          <Button
            busy={busy}
            busyLabel="正在提交回答…"
            disabled={!ready}
            type="submit"
            variant="primary"
          >
            提交回答并继续起草
          </Button>
          <span className="mono faint">回答会作为 teacher_answer 引注写进草案</span>
        </div>
      </form>
    </section>
  );
}
