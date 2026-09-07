"use client";

/**
 * Real generation timeline: live SSE subscription over the persisted public
 * event log, plus a static replay mode for completed runs.
 *
 * Contract notes:
 * - the stream NEVER owns or starts the job: disconnects and refreshes only
 *   move the read cursor (after_sequence), reconnects resume idempotently;
 * - connection state, waiting-for-model, retry, failure and completion are
 *   visually distinct — no timers, fake percentages or typing animations;
 * - the full public transcript stays available after completion (replay),
 *   not just a final summary.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "@/lib/api/client";
import { getRunEvents, runEventsStreamUrl, type RunEventView } from "../api";
import styles from "./generation-timeline.module.css";

type ConnectionState =
  | "connecting" | "open" | "reconnecting" | "closed"
  | "frozen" | "gone" | "unavailable" | "error";

const CONNECTION_LABEL: Record<ConnectionState, string> = {
  connecting: "连接中…",
  open: "已连接",
  reconnecting: "连接中断，重连中…（生成在后台继续）",
  closed: "运行已结束",
  frozen: "题目删除清理中，记录已冻结",
  gone: "题目已删除",
  unavailable: "记录不可用（运行已被取代或题目已冻结）",
  error: "连接失败",
};

const STAGE_LABEL: Record<string, string> = {
  model_call_started: "模型推理中",
  graph_completed: "结果校验与保存",
  fake_generation_started: "生成开始（测试模式）",
  fake_generation_completed: "生成完成（测试模式）",
  thread_state_new: "新建运行线程",
  thread_state_incomplete: "从检查点恢复运行",
  thread_state_complete: "复用已完成的运行结果",
  citations_repaired: "引用已自动校正为材料原文",
  revision_requested: "校验未通过，进入修订轮",
  model: "模型输出",
  tools: "工具执行",
};

function stageLabel(stage: string | null | undefined): string {
  if (!stage) return "阶段更新";
  return STAGE_LABEL[stage] ?? stage;
}

interface DisplayBlock {
  key: string;
  kind: "stage" | "text" | "tool" | "failed" | "interrupted" | "completed";
  label?: string;
  text?: string;
  attempt: number;
}

/** Merge consecutive message deltas into one growing text block. */
function toBlocks(events: RunEventView[]): DisplayBlock[] {
  const blocks: DisplayBlock[] = [];
  for (const event of events) {
    if (event.kind === "message_delta") {
      const last = blocks[blocks.length - 1];
      if (last && last.kind === "text" && last.attempt === event.attempt) {
        last.text = (last.text ?? "") + (event.text ?? "");
        continue;
      }
      blocks.push({
        key: `text-${event.attempt}-${event.sequence}`,
        kind: "text",
        text: event.text ?? "",
        attempt: event.attempt,
      });
      continue;
    }
    if (event.kind === "tool_started") {
      blocks.push({
        key: `tool-${event.attempt}-${event.sequence}`,
        kind: "tool",
        label: event.detail ? `${event.tool}（${event.detail}）` : (event.tool ?? "工具"),
        attempt: event.attempt,
      });
      continue;
    }
    if (event.kind === "tool_finished" || event.kind === "stage") {
      if (event.kind === "tool_finished") continue; // started line already shows it
      blocks.push({
        key: `stage-${event.attempt}-${event.sequence}`,
        kind: "stage",
        label: stageLabel(event.stage),
        attempt: event.attempt,
      });
      continue;
    }
    if (event.kind === "tool_failed") {
      blocks.push({
        key: `toolfail-${event.attempt}-${event.sequence}`,
        kind: "tool",
        label: `${event.tool ?? "工具"} 调用未成功（已按失败处理）`,
        attempt: event.attempt,
      });
      continue;
    }
    if (event.kind === "run_failed") {
      blocks.push({
        key: `failed-${event.attempt}-${event.sequence}`,
        kind: "failed",
        label: event.detail === "superseded" ? "本轮运行已被新一轮任务取代" : "本轮运行失败",
        attempt: event.attempt,
      });
      continue;
    }
    if (event.kind === "interrupted") {
      blocks.push({
        key: `int-${event.attempt}-${event.sequence}`,
        kind: "interrupted",
        label: "运行已暂停（等待恢复）",
        attempt: event.attempt,
      });
      continue;
    }
    if (event.kind === "run_completed") {
      blocks.push({
        key: `done-${event.attempt}-${event.sequence}`,
        kind: "completed",
        label: "生成结果已保存",
        attempt: event.attempt,
      });
    }
  }
  return blocks;
}

export interface GenerationTimelineProps {
  questionId: string;
  operationId: string;
  /** true: subscribe to SSE; false: one-shot replay of the persisted log. */
  live: boolean;
  onDone?: (status: string) => void;
  onGone?: () => void;
  onFrozen?: () => void;
  /** Accessible label for the region. */
  ariaLabel?: string;
}

export function GenerationTimeline({
  questionId,
  operationId,
  live,
  onDone,
  onGone,
  onFrozen,
  ariaLabel = "生成过程",
}: GenerationTimelineProps): React.JSX.Element {
  const [events, setEvents] = useState<RunEventView[]>([]);
  const [connection, setConnection] = useState<ConnectionState>(live ? "connecting" : "closed");
  const [elapsedMs, setElapsedMs] = useState(0);
  const lastSequenceRef = useRef(0);
  const startedAtRef = useRef<number>(Date.now());
  const stickToBottomRef = useRef(true);
  const lastAnnounceRef = useRef(0);
  const sourceRef = useRef<EventSource | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const statusRef = useRef<HTMLParagraphElement | null>(null);
  const doneFiredRef = useRef(false);

  const appendEvents = useCallback((incoming: RunEventView[]) => {
    if (incoming.length === 0) return;
    setEvents((prev) => {
      const seen = new Set(prev.map((e) => e.sequence));
      const fresh = incoming.filter((e) => !seen.has(e.sequence));
      if (fresh.length === 0) return prev;
      lastSequenceRef.current = Math.max(
        lastSequenceRef.current,
        ...fresh.map((e) => e.sequence),
      );
      // Calibrate the elapsed clock on the first persisted event: a page
      // refreshed mid-run must not restart the timer from zero.
      const firstCreated = Date.parse(fresh[0].created_at);
      if (prev.length === 0 && Number.isFinite(firstCreated) && firstCreated < startedAtRef.current) {
        startedAtRef.current = firstCreated;
      }
      return [...prev, ...fresh];
    });
  }, []);

  // A different operation is a different log: reset cursor, events and flags.
  useEffect(() => {
    setEvents([]);
    lastSequenceRef.current = 0;
    doneFiredRef.current = false;
    startedAtRef.current = Date.now();
    setElapsedMs(0);
    setConnection(live ? "connecting" : "closed");
  }, [operationId, live]);

  // Elapsed timer while live and not finished.
  useEffect(() => {
    if (!live || connection === "closed" || connection === "gone" || connection === "frozen") return;
    const timer = setInterval(() => setElapsedMs(Date.now() - startedAtRef.current), 1000);
    return () => clearInterval(timer);
  }, [live, connection]);

  // History replay: page through the persisted log once.
  useEffect(() => {
    if (live) return;
    let cancelled = false;
    const loadAll = async () => {
      let after = 0;
      for (;;) {
        const page = await getRunEvents(questionId, operationId, { afterSequence: after });
        if (cancelled) return;
        appendEvents(page.events);
        if (page.events.length === 0 || page.last_sequence <= after) return;
        after = page.last_sequence;
      }
    };
    loadAll().catch((err: unknown) => {
      if (err instanceof ApiError &&
          ["OPERATION_SUPERSEDED", "QUESTION_DELETING", "RESOURCE_NOT_FOUND"].includes(err.code)) {
        setConnection("unavailable");
      } else {
        setConnection("error");
      }
    });
    return () => {
      cancelled = true;
    };
  }, [live, questionId, operationId, appendEvents]);

  // Live SSE subscription with manual cursor-based reconnect.
  useEffect(() => {
    if (!live) return;
    let disposed = false;

    const open = () => {
      if (disposed) return;
      const source = new EventSource(
        runEventsStreamUrl(questionId, operationId, lastSequenceRef.current),
      );
      sourceRef.current = source;
      source.onopen = () => setConnection("open");
      source.onmessage = (message) => {
        let payload: Record<string, unknown>;
        try {
          payload = JSON.parse(message.data);
        } catch {
          return;
        }
        const type = payload.type as string;
        if (type === "event") {
          const { type: _t, ...event } = payload as unknown as RunEventView & { type: string };
          appendEvents([event]);
          return;
        }
        if (type === "done") {
          setConnection("closed");
          source.close();
          if (!doneFiredRef.current) {
            doneFiredRef.current = true;
            onDone?.(String(payload.status ?? ""));
          }
          return;
        }
        if (type === "frozen") {
          setConnection("frozen");
          source.close();
          onFrozen?.();
          return;
        }
        if (type === "gone") {
          setConnection("gone");
          source.close();
          onGone?.();
          return;
        }
        // "ended" (transient): fall through to reconnect with the cursor.
        source.close();
        scheduleReconnect();
      };
      source.onerror = () => {
        source.close();
        if (disposed) return;
        scheduleReconnect();
      };
    };

    const scheduleReconnect = () => {
      if (disposed) return;
      setConnection("reconnecting");
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = setTimeout(open, 1500);
    };

    open();
    return () => {
      disposed = true;
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
      sourceRef.current?.close();
      sourceRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [live, questionId, operationId]);

  // Follow the tail only while the teacher is at the bottom. Stickiness is
  // tracked from scroll events (measured BEFORE new content lands), so a big
  // batch of new lines never permanently loses the follow position — and
  // scrolling up to read older feedback is never stolen back.
  useEffect(() => {
    if (!stickToBottomRef.current) return;
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [events]);

  // Screen-reader status: at most one update per 3s, but continuous streaming
  // can never starve it (leading edge fires immediately, trailing catches up).
  useEffect(() => {
    const el = statusRef.current;
    if (!el) return;
    const announce = () => {
      lastAnnounceRef.current = Date.now();
      const lastStage = [...events].reverse().find((e) => e.kind === "stage");
      el.textContent = lastStage
        ? `当前阶段：${stageLabel(lastStage.stage)}`
        : connection === "open"
          ? "生成进行中"
          : CONNECTION_LABEL[connection];
    };
    const since = Date.now() - lastAnnounceRef.current;
    if (since >= 3000) {
      announce();
      return;
    }
    const timer = setTimeout(announce, 3000 - since);
    return () => clearTimeout(timer);
  }, [events, connection]);

  const blocks = toBlocks(events);
  const elapsed = Math.floor(elapsedMs / 1000);

  return (
    <div className={styles.timeline} role="region" aria-label={ariaLabel}>
      <div className={styles.head}>
        <span className={`${styles.dot} ${styles[`dot_${connection}`] ?? ""}`} aria-hidden="true" />
        <span className={styles.connection} data-testid="timeline-connection">
          {CONNECTION_LABEL[connection]}
        </span>
        {live && (connection === "open" || connection === "connecting" || connection === "reconnecting") ? (
          <span className={styles.elapsed} data-testid="timeline-elapsed">
            已用 {Math.floor(elapsed / 60)} 分 {elapsed % 60} 秒
          </span>
        ) : null}
      </div>
      <p ref={statusRef} className={styles.srStatus} aria-live="polite" />
      <div
        className={styles.body}
        ref={scrollRef}
        data-testid="timeline-body"
        onScroll={() => {
          const el = scrollRef.current;
          if (el) stickToBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 32;
        }}
      >
        {blocks.length === 0 ? (
          <p className={styles.empty}>
            {live ? "等待第一批过程反馈…（模型响应前会显示真实等待状态）" : "本次运行没有公开过程记录。"}
          </p>
        ) : null}
        {blocks.map((block) => {
          if (block.kind === "text") {
            return (
              <pre key={block.key} className={styles.streamText} data-testid="timeline-stream">
                {block.text}
              </pre>
            );
          }
          if (block.kind === "tool") {
            return (
              <p key={block.key} className={styles.toolLine} data-testid="timeline-tool">
                <span className={styles.toolBadge} aria-hidden="true">工具</span>
                {block.label}
              </p>
            );
          }
          const cls =
            block.kind === "failed"
              ? styles.failLine
              : block.kind === "completed"
                ? styles.doneLine
                : styles.stageLine;
          return (
            <p key={block.key} className={cls} data-testid={`timeline-${block.kind}`}>
              {block.label}
            </p>
          );
        })}
      </div>
    </div>
  );
}
