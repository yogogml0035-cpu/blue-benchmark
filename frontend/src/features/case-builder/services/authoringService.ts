import { apiFetch, apiStream } from "@/src/lib/api/client";
import type { components } from "@/src/lib/api/generated";

type Schemas = components["schemas"];

export type AuthoringConversation = Schemas["AuthoringConversationView"];
export type AuthoringConversationResponse = Schemas["AuthoringConversationResponse"];
export type AuthoringConversationCreateRequest = Schemas["AuthoringConversationCreateRequest"];
export type AuthoringMessageRequest = Schemas["AuthoringMessageRequest"];
export type QuestionBoundaryRequest = Schemas["QuestionBoundaryRequest"];
export type InputAnswerPatchRequest = Schemas["InputAnswerPatchRequest"];
export type InputAnswerConfirmationRequest = Schemas["InputAnswerConfirmationRequest"];
export type AuthoringRetryRequest = Schemas["AuthoringRetryRequest"];
export type AuthoringContinuityResetRequest = Schemas["AuthoringContinuityResetRequest"];
// SSE has no JSON response schema in OpenAPI, so keep its small allowlist at
// this transport boundary instead of making the page accept arbitrary text.
export type AuthoringEventKind =
  | "phase_started"
  | "phase_completed"
  | "action_summary"
  | "public_message_ready"
  | "snapshot_changed"
  | "waiting_for_teacher"
  | "failed"
  | "completed";

export type AuthoringStreamEvent = {
  sequence: number;
  kind: AuthoringEventKind;
  payload: Record<string, unknown>;
};

const AUTHORING_EVENT_KINDS = new Set<AuthoringEventKind>([
  "phase_started",
  "phase_completed",
  "action_summary",
  "public_message_ready",
  "snapshot_changed",
  "waiting_for_teacher",
  "failed",
  "completed",
]);

function base(workspaceId: string) {
  return `/api/workspaces/${workspaceId}/authoring-conversations`;
}

export function createAuthoringConversation(
  workspaceId: string,
  input: AuthoringConversationCreateRequest,
) {
  return apiFetch<AuthoringConversationResponse>(base(workspaceId), {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function getAuthoringConversation(workspaceId: string, conversationId: string) {
  return apiFetch<AuthoringConversationResponse>(`${base(workspaceId)}/${conversationId}`);
}

export function postAuthoringMessage(
  workspaceId: string,
  conversationId: string,
  input: AuthoringMessageRequest,
) {
  return apiFetch<AuthoringConversationResponse>(`${base(workspaceId)}/${conversationId}/messages`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function mutateQuestionBoundaries(
  workspaceId: string,
  conversationId: string,
  input: QuestionBoundaryRequest,
) {
  return apiFetch<AuthoringConversationResponse>(
    `${base(workspaceId)}/${conversationId}/question-boundaries`,
    { method: "POST", body: JSON.stringify(input) },
  );
}

export function patchQuestionInputAnswer(
  workspaceId: string,
  conversationId: string,
  draftId: string,
  input: InputAnswerPatchRequest,
) {
  return apiFetch<AuthoringConversationResponse>(
    `${base(workspaceId)}/${conversationId}/question-drafts/${draftId}/input-answer`,
    { method: "PATCH", body: JSON.stringify(input) },
  );
}

export function confirmQuestionInputAnswer(
  workspaceId: string,
  conversationId: string,
  draftId: string,
  input: InputAnswerConfirmationRequest,
) {
  return apiFetch<AuthoringConversationResponse>(
    `${base(workspaceId)}/${conversationId}/question-drafts/${draftId}/input-answer-confirmation`,
    { method: "POST", body: JSON.stringify(input) },
  );
}

export function retryAuthoringConversation(
  workspaceId: string,
  conversationId: string,
  input: AuthoringRetryRequest,
) {
  return apiFetch<AuthoringConversationResponse>(`${base(workspaceId)}/${conversationId}/retry`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function resetAuthoringContinuity(
  workspaceId: string,
  conversationId: string,
  input: AuthoringContinuityResetRequest,
) {
  return apiFetch<AuthoringConversationResponse>(
    `${base(workspaceId)}/${conversationId}/continuity-reset`,
    { method: "POST", body: JSON.stringify(input) },
  );
}

/**
 * Read one finite safe-event window. The server deliberately does not bind
 * Worker lifetime to an HTTP stream; the page always follows this with a
 * fresh conversation snapshot.
 */
export async function readAuthoringEvents(
  workspaceId: string,
  conversationId: string,
  after: number,
  signal?: AbortSignal,
): Promise<AuthoringStreamEvent[]> {
  const streamController = new AbortController();
  const abortExternal = () => streamController.abort();
  signal?.addEventListener("abort", abortExternal, { once: true });
  const streamTimeout = window.setTimeout(() => {
    streamController.abort();
  }, 5_000);
  let response: Response;
  try {
    response = await apiStream(
      `${base(workspaceId)}/${conversationId}/events?after=${encodeURIComponent(String(Math.max(0, after)))}`,
      {
        headers: { Accept: "text/event-stream", "Last-Event-ID": String(Math.max(0, after)) },
        signal: streamController.signal,
      },
    );
  } catch (error) {
    window.clearTimeout(streamTimeout);
    signal?.removeEventListener("abort", abortExternal);
    throw error;
  }
  if (!response.body) {
    window.clearTimeout(streamTimeout);
    signal?.removeEventListener("abort", abortExternal);
    return [];
  }

  const reader = response.body.getReader();
  // The endpoint is a finite replay window, but a reverse proxy or a stalled
  // connection must never hold page recovery forever. Aborting this browser
  // request does not cancel the Worker operation.
  const decoder = new TextDecoder();
  const events: AuthoringStreamEvent[] = [];
  let buffer = "";
  let eventName = "";
  let eventId = "";
  let data: string[] = [];

  function flush() {
    if (eventName && eventId && data.length > 0) {
      const sequence = Number(eventId);
      if (Number.isSafeInteger(sequence) && sequence > Math.max(0, after) && AUTHORING_EVENT_KINDS.has(eventName as AuthoringEventKind)) {
        try {
          const parsed = JSON.parse(data.join("\n")) as unknown;
          if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
            events.push({
              sequence,
              kind: eventName as AuthoringEventKind,
              payload: parsed as Record<string, unknown>,
            });
          }
        } catch {
          // A malformed safe event is ignored; the subsequent snapshot is
          // still authoritative and will surface an explicit state if needed.
        }
      }
    }
    eventName = "";
    eventId = "";
    data = [];
  }

  try {
    while (true) {
      const chunk = await reader.read();
      buffer += decoder.decode(chunk.value ?? new Uint8Array(), { stream: !chunk.done });
      const lines = buffer.split(/\r?\n/);
      buffer = lines.pop() ?? "";
      for (const line of lines) {
        if (!line) {
          flush();
          continue;
        }
        if (line.startsWith(":")) continue;
        const separator = line.indexOf(":");
        const field = separator >= 0 ? line.slice(0, separator) : line;
        const value = separator >= 0 ? line.slice(separator + 1).replace(/^ /, "") : "";
        if (field === "event") eventName = value;
        if (field === "id") eventId = value;
        if (field === "data") data.push(value);
      }
      if (chunk.done) break;
    }
    if (buffer) data.push(buffer);
    flush();
    return events;
  } finally {
    window.clearTimeout(streamTimeout);
    signal?.removeEventListener("abort", abortExternal);
  }
}
