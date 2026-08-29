# Deep Agents Adversarial Review

Checked again against live LangChain/Deep Agents docs on 2026-08-30, including Checkpointers, interrupts, context engineering, HITL, the official custom-middleware page, and local `langchain-dev-guide` references. The third persistence review overturns the earlier blanket “no cross-turn Checkpointer” conclusion.

## Finding 1 — “Read-only” needs two independent controls

- `FilesystemMiddleware` tool allowlist needs `deepagents>=0.7`.
- Filesystem permission rules are first-match-wins and default to allow when unmatched.
- M0 must both expose only `ls/read_file/glob/grep` and apply ordered permissions: allow read under `/evidence/**`, deny all other reads, deny all writes.
- `FilesystemBackend` must use `virtual_mode=True`; custom/MCP tools are outside filesystem permissions, so M0 should register none.
- The default general-purpose subagent and `task` tool must be disabled through a HarnessProfile; do not attempt to remove required middleware.

## Finding 2 — One universal large schema is an avoidable failure mode

- Live Deep Agents supports `response_format=` and returns validated data in `state["structured_response"]`.
- `langchain-dev-guide` shows that provider-native, ToolStrategy and model-wrapper methods have different compatibility behavior. OpenAI-compatible transport does not prove native JSON Schema or forced `tool_choice` support.
- Weak or mismatched models fail more often with large schemas and malformed tool calls.
- Replace one universal schema with three named agents using the same AI Profile: `batch_analyzer`, `standard_cocreator`, `coverage_reviewer`. They are independent instances, not subagents and do not expose delegation.
- Each has a small Pydantic response schema. The model/strategy combination is selected only after a live capability test.

## Finding 3 — ChatOpenAI compatibility is not a production proof

- Current backend has no LangChain/Deep Agents dependency.
- Existing future docs assume `LLM_BASE_URL`, `LLM_MODEL` and `langchain-openai`, but the real provider and request capability are not verified.
- The Spike must test: normal tool calls, specific/forced `tool_choice`, provider-native JSON Schema, ToolStrategy, malformed tool calls, empty tools, non-streaming invoke, multi-turn tool/message roundtrip and Deep Agents real-sample behavior.
- If no supported structured-output strategy passes, stop and revise the AI Profile/adapter. Do not silently fall back to free-form JSON in production.
- M0 does not display or depend on `reasoning_content`; private reasoning is never a business artifact.

## Finding 4 — The file reader silently truncates long evidence by default

- Built-in `read_file` defaults to 100 lines.
- Real M0 files include 310-record JSONL and 424-line Markdown; material feedback can occur near the tail.
- The static system prompt must require reading the manifest, using explicit `limit`, paginating with `offset`, and proving EOF/coverage before claiming a file was understood.
- Acceptance must place decisive feedback after line 100 and verify its locator appears in output.

## Finding 5 — Agent attempt and business retry have different semantics

- Batch analysis has no human interrupt and should be all-or-nothing. Each background job attempt gets a fresh internal thread/attempt ID; a crashed attempt is rerun, and only a fully validated result is committed.
- Coverage review has the same all-or-nothing shape and does not need a stable thread.
- Contract/question co-creation is different: it is intentionally multi-turn, asks one question, waits for a teacher who may return later, and benefits from exact short-term message/tool continuity. It should own one stable Checkpointer thread per `CoCreationSession`.
- Retrying an identical answer must return the existing turn projection; a different answer for the same accepted turn conflicts.
- Model transport retry stays within one AgentRunAttempt. A business retry creates a new run from the business session's accepted Checkpoint; it does not create a new co-creation thread.

## Finding 6 — Model-facing content and app-facing evidence metadata must be separated

- Tool output content enters the model context; application metadata must not be inferred back from that text.
- M0 keeps the built-in filesystem tool surface and routes it through a read-only `EvidenceBackend`. Stable metadata (file ID, locator basis, content hash) comes from the deterministic manifest/adapter side-channel rather than a new custom read tool that would bypass FilesystemPermission.
- Final structured output carries EvidenceRefs that the application validates against the canonical extracted view. It never trusts a path/line range simply because the model emitted it.

## Finding 7 — Replacing FilesystemMiddleware can silently drop permissions

- Live docs state that a caller middleware with the same `.name` replaces the built-in instance in place.
- A replacement `FilesystemMiddleware` does not inherit `backend=` or `permissions=` passed at the `create_deep_agent()` top level.
- The earlier design passed backend to the replacement but permissions only at the top level, leaving the exact read boundary it intended to enforce unproven.
- Correction: construct the replacement with `FilesystemMiddleware(backend=..., permissions=..., tools=[...])` and test cross-scope reads and writes. Production routes `/evidence/` to an application-owned read-only backend rather than the host filesystem.

## Finding 8 — Stable cross-turn checkpoints add a second state source unless authority is explicit

- PostgreSQL business tables already store the authoritative draft, decisions, gaps, answers, revisions and operation state. Checkpoint must not replace those tables.
- But using no Checkpointer for the multi-turn co-creator would lose exact conversational/tool context, repeat evidence reads and model calls, and force the application to recreate an interrupt protocol.
- Correction: use both. Business tables own accepted facts and store the one accepted checkpoint pointer; PostgreSQL Checkpointer owns only Graph execution state. Every resume uses the accepted checkpoint ID, never the raw latest thread checkpoint.
- Stable thread state retains private messages and is coupled to AI/Graph versions, so session records pin `ai_profile_version + graph_schema_version`; incompatible migration creates a new thread from the business projection and records continuity reset.

## Finding 9 — HarnessProfile is global mutable registration, not a session profile

- Harness profiles resolve by provider/model key; re-registering merges into the existing global entry.
- Using that registry to represent `ai_profile_version` would let concurrent old/new sessions affect one another.
- Correction: register only immutable security defaults at process startup under each exact model key. Build/cache Agent graphs by application AI Profile version and never re-register from a request.

## Finding 10 — Custom middleware is the wrong owner for business state

- Official hook semantics: node hooks run at lifecycle points; wrap hooks control each model/tool call; multiple middleware compose with onion ordering.
- M0 needs call caps and limited transport retries, which built-in middleware already supplies. Permissions belong to FilesystemMiddleware/EvidenceBackend; input/output business validation belongs to the Adapter/Service.
- No custom middleware is required for the first implementation. If payload-free per-call telemetry cannot be obtained from callbacks, add one stateless class-based observer using wrap hooks for timing and before/after-agent for run boundaries, with payload tracing omitted.
- Hooks must never advance OperationJob, confirm a question, freeze a version, change the model/tools/prompt, or persist structured output.

## Finding 11 — Only backgrounding upload leaves the most fragile HTTP calls synchronous

- A co-creation turn may reread long evidence and a freeze may build/hash a package; both can outlive ordinary request timeouts just like batch analysis.
- Correction: use one DB-backed OperationJob contract for batch analysis, co-creation turns, coverage review and freeze. Commands return `202`; the frontend polls a durable business projection and survives refresh/re-entry.

## Finding 12 — A valid old run can still become unsafe before commit

- An OperationJob can start against revision N, then finish after the target was discarded or advanced to N+1.
- Idempotency at enqueue time does not stop this late result from overwriting newer state.
- Correction: store target revision on the job and perform a second compare-and-swap check at commit. Mark stale work `superseded`; do not present it as an AI failure or allow retry against the old revision.

## Finding 13 — Global tool exclusion cannot express per-agent file access

- The three Agent instances share a model key, so a HarnessProfile exclusion of filesystem tools would affect all of them.
- `coverage_reviewer` needs no file tools while the other two do.
- Correction: give coverage review its own StateBackend and replace its FilesystemMiddleware with `tools=[]`. Keep only truly global safety invariants in HarnessProfile.

## Finding 14 — “All context is in Checkpoint” is technically false and unsafe as a design rule

- Checkpointer persists Graph State. Deep Agents runtime context is supplied per invocation and is not automatically added to state or the model prompt.
- Identity, credentials, business revision, evidence scope, deadline and compatibility versions must be revalidated and re-supplied on every start/resume. Credentials and database handles must never be forced into checkpointed state merely to make it “self-contained.”
- Evidence files remain in application storage behind EvidenceBackend; the Checkpoint stores only Agent messages, state and virtual scratch references.

## Finding 15 — ask-user HITL matches the product, but only under a narrow contract

- Deep Agents HumanInTheLoopMiddleware supports `respond`, specifically intended for ask-user tools that synthesize the human reply as a tool result.
- `standard_cocreator` can expose a pure `ask_teacher` tool and interrupt before its execution. The interrupting AIMessage must contain only that one tool call, produce exactly one action request and allow only `respond`; multiple/concurrent questions or unrelated pending tools fail closed.
- `interrupt_on + response_format` and the selected model's tool-calling strategy must be tested together. If unstable, use completed turns on the same Checkpointer thread; do not switch to free-form JSON or no persistence.

## Finding 16 — Interrupt resume re-runs code before the interrupt

- LangGraph resumes an interrupted node from its beginning. Any non-idempotent operation before `interrupt()` can execute twice.
- M0 keeps the Agent read-only and forbids business DB writes, external sends and irreversible actions inside the Graph. The answer is saved to CoCreationTurn before resume; all accepted delta/confirmation/version writes happen after the Agent boundary in a business transaction.

## Finding 17 — Checkpoint advance and business commit are not one atomic fact

- The Graph can persist a new interrupt/result checkpoint and then fail before the Service commits its business projection.
- Retrying the model from the old business state wastes cost and may create a different branch; blindly resuming thread latest accepts uncommitted state.
- Correction: AgentRunAttempt stores base and produced checkpoint IDs plus result hash. The session's accepted checkpoint advances only in the successful business CAS. A failed projection becomes `projection_pending` and is rebuilt from the produced checkpoint without another model call; stale branches become `superseded`.

## Finding 18 — Checkpoint content needs its own data lifecycle

- Deep Agents checkpoints can include messages, tool results, automatic summaries and StateBackend scratch/offloaded conversation containing business text.
- Use encrypted serialization, restricted DB access, no payload logging, explicit retention, active-session protection and thread deletion. Deleting an ended thread must not remove any confirmed business asset.

## Finding 19 — Store/Memory is still unnecessary

- Checkpointer provides short-term state within one co-creation thread. Store/Memory provides long-term information across threads.
- M0's cross-session facts already belong to scenario contracts, questions and provenance tables. Enabling writable shared Memory adds namespace and prompt-injection risk without a product requirement.
- Correction: use Checkpointer for `standard_cocreator`; keep StoreBackend Memory and MemoryMiddleware disabled.

## Revised implementation boundary

- Direct integration: Deep Agents only.
- Instances: three named, role-specific agents under one versioned AI Profile; no subagent delegation. Batch analysis reads only the current batch, co-creation only the current task package, and coverage review receives structured snapshots with no filesystem tools.
- Business interface: `EvidenceAnalyzer` and `CoverageReviewer` return validated DTOs from fresh attempts. `StandardCoCreator` exposes start/resume/reproject over a stable PostgreSQL-checkpointed thread.
- UI progress: database job phases and polling. Do not couple product state to LangChain token/tool event streams.
- Streaming: disabled for M0 model calls unless a later product requirement explicitly needs it.
- Persistence: PostgreSQL business tables are authoritative; OperationJob owns scheduling; PostgreSQL Checkpointer owns only `standard_cocreator` execution continuity; Store/Memory remains disabled.
- HITL: prefer one pure `ask_teacher` tool with `respond`; fallback is completed turns on the same Checkpointer thread if the capability Spike fails.
- Middleware: built-in run limits and finite model retry only; no custom business middleware by default.
