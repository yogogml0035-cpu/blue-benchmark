# Framework Evidence

Checked again against the live LangChain/Deep Agents documentation on 2026-08-30.

## Sources

- `https://docs.langchain.com/oss/python/deepagents/overview.md`
- `https://docs.langchain.com/oss/python/deepagents/backends.md`
- `https://docs.langchain.com/oss/python/deepagents/customization.md`
- `https://docs.langchain.com/oss/python/deepagents/context-engineering.md`
- `https://docs.langchain.com/oss/python/deepagents/permissions.md`
- `https://docs.langchain.com/oss/python/deepagents/profiles.md`
- `https://docs.langchain.com/oss/python/deepagents/fault-tolerance.md`
- `https://docs.langchain.com/oss/python/deepagents/human-in-the-loop.md`
- `https://docs.langchain.com/oss/python/deepagents/sandboxes.md`
- `https://docs.langchain.com/oss/python/langgraph/overview.md`
- `https://docs.langchain.com/oss/python/langgraph/interrupts.md`
- `https://docs.langchain.com/oss/python/langgraph/persistence.md`
- `https://docs.langchain.com/oss/python/langgraph/checkpointers.md`
- `https://docs.langchain.com/oss/python/langgraph/add-memory.md`
- `https://docs.langchain.com/oss/python/langchain/middleware/custom.md`

## Findings

- Deep Agents is a harness built on LangChain components and LangGraph runtime. “Only integrate Deep Agents” means the application does not separately create a LangChain agent or hand-write a LangGraph; it does not remove those internal dependencies.
- Deep Agents fits heterogeneous evidence analysis because it provides a virtual filesystem, growing-context management and durable thread support.
- Current docs support a read-only filesystem tool allowlist (`read_file`, `ls`, `glob`, `grep`) and allow task planning/subagents to be disabled. M0 must verify these behaviors against the pinned package version in a Spike.
- Sandboxes are only necessary when executing arbitrary code. M0 explicitly treats uploaded Skill/code as data and does not execute it.
- Custom LangGraph is deferred because M0's deterministic business state is enforced in FastAPI/DB and each user turn can invoke the same Deep Agents thread. Reconsider only if runtime evidence proves that precise node-level orchestration is missing.
- Deep Agents checkpoints are execution state, not business tables; confirmed standards and frozen versions remain PostgreSQL facts.
- Checkpointers persist Graph State at super-step boundaries and are the native mechanism for thread-scoped conversation continuity, pending writes, fault recovery, time travel and HITL interrupt/resume. Production supports `PostgresSaver`/`AsyncPostgresSaver`; `thread_id` is the persistent cursor and must stay under 255 characters.
- `interrupt()` requires a Checkpointer and resumes with the same thread. The interrupted node restarts from its beginning, so any code before the interrupt must be idempotent; M0 therefore keeps all business writes outside the Graph.
- Deep Agents HITL supports `respond`, which returns the teacher's message as a synthetic tool result for an ask-user style tool. This directly fits the “one highest-value question, then wait” requirement, provided the model/response strategy passes a real compatibility Spike.
- Runtime `context_schema` values are per-run inputs and are not automatically checkpointed. Identity, credentials, evidence scope, business revision and compatibility versions must be re-supplied and revalidated on every start/resume.
- Custom Deep Agent state and default StateBackend scratch can survive checkpointing. Automatic summarization may preserve rendered conversation history in that thread filesystem, so Checkpoint storage can contain business content and needs encryption, access isolation and retention/deletion policy.
- `create_deep_agent` already assembles Filesystem, Summarization, PatchToolCalls, provider caching and optional subagent/HITL middleware. A caller-supplied middleware with the same `.name` replaces the built-in instance in place; a FilesystemMiddleware replacement does not inherit top-level backend/permissions and must be fully configured itself.
- Permissions are first-match-wins and unmatched operations are allowed. Production therefore needs both a read-tool allowlist and explicit catch-all deny rules. A custom `EvidenceBackend` can map virtual evidence paths to application storage without exposing host paths.
- HarnessProfile registration is global per provider/model key and re-registration merges. It is suitable for immutable model safety defaults, not for request-scoped AI Profile versions.
- M0 does have a thread-scoped continuity need for `standard_cocreator`: multi-round AI/teacher co-creation, one question at a time, return-later behavior and cross-restart recovery. It should use PostgreSQL Checkpointer while PostgreSQL business tables remain authoritative. `batch_analyzer` and `coverage_reviewer` still use fresh attempts because they have no human pause or cross-turn memory requirement.
- Checkpointer and Store remain distinct. Checkpointer is in scope only for the co-creation thread; Store/Memory is out of scope because M0 has no cross-thread user preference or Agent long-term knowledge requirement.
- A Checkpointer is not a queue or business transaction coordinator. OperationJob remains responsible for leases, concurrency, idempotent commands, `202` page status and retries. The business session stores which checkpoint branch is accepted; raw “latest checkpoint for thread” is never an authority.
- Official custom middleware guidance separates node hooks (logging, validation, state updates) from wrap hooks (retry, caching, transformation) and uses onion ordering. M0 can use built-in call-limit/model-retry middleware; business transitions and structured-output validation remain ordinary Service/Adapter code.
