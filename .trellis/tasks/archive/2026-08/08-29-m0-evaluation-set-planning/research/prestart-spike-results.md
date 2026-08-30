# M0 Pre-start Spike Results

Date: 2026-08-30

## Outcome

The planning-stage Spike passed the framework, provider, permission, persistence,
resume, projection, and concurrency checks required before implementation. The
production response strategy is now fixed to LangChain `ToolStrategy`; provider
native `json_schema` is not compatible with the active Claude/Bedrock relay.

No product source was changed. The executable Spike files live under
`research/spikes/`, use synthetic text only, and accept credentials through
environment variables without printing them.

## Pinned capability baseline

| Package | Verified version |
|---|---:|
| Python | 3.13.15 |
| `deepagents` | 0.7.11 |
| `langchain` | 1.3.18 |
| `langchain-core` | 1.6.1 |
| `langgraph` | 1.2.11 |
| `langgraph-checkpoint` | 4.2.0 |
| `langgraph-checkpoint-postgres` | 3.1.2 |
| `langchain-anthropic` | 1.7.0 |
| `psycopg` | 3.3.4 |
| `psycopg-pool` | 3.3.1 |
| `pycryptodome` | 3.23.0 |

The actual endpoint test used the currently configured Claude Sonnet alias. The
relay URL and authorization token were read only for the process lifetime and
were never printed or copied into the repository.

## Provider capability matrix

Command: `provider_capability_spike.py --negative-checks`

| Capability | Result | Contract consequence |
|---|---|---|
| Non-streaming message call | PASS | M0 keeps streaming disabled. |
| Empty tools | PASS | Tool-less coverage calls are supported. |
| Normal tool call | PASS | Standard tool loop is usable. |
| Forced named tool call | PASS | A required single tool can be enforced. |
| ToolMessage round trip | PASS | Multi-turn tool/message pairing is accepted. |
| Nested Chinese Pydantic schema via function calling | PASS | Nested M0 DTOs are viable. |
| Deep Agent `ToolStrategy(Review)` | PASS | Fixed production structured-output strategy. |
| `ask_teacher` single interrupt | PASS | Exactly one projected business question is viable. |
| `allowed_decisions=[respond]` | PASS | Teacher answers can return as the synthetic tool result. |
| Explicit interrupted Checkpoint ID | PASS | The application can persist the accepted branch pointer. |
| Resume on the same thread to `structured_response` | PASS | HITL and structured output work together on this endpoint. |
| `invalid_tool_calls` on successful calls | PASS, zero | Any non-empty value remains fail-closed. |
| Provider-native `json_schema` | FAIL: `AnthropicInvalidRequestError` | Do not use `ProviderStrategy` or auto-select it. |
| `temperature=0` | FAIL: `AnthropicInvalidRequestError` | Do not send `temperature` for this model route. |

## Filesystem and middleware matrix

Command: `checkpointer_spike.py static`

| Capability | Result |
|---|---|
| `read_file` defaults to 100 lines | PASS |
| Default read reports remaining lines | PASS |
| Explicit `offset`/`limit` reaches line 130 and EOF | PASS |
| `/evidence/**` read allowed | PASS |
| Read outside the evidence scope denied | PASS |
| Write/edit/delete/execute tools absent | PASS |
| General-purpose `task` tool absent | PASS |
| Per-Agent model tool allowlist preserves ToolStrategy/HITL | PASS |
| Hidden disallowed tool hallucination rejected before execution | PASS |
| Tool-surface middleware sync and async hooks | PASS |
| Synthetic malformed tool call is rejected | PASS |
| One transport retry occurs inside one logical model step | PASS |

For `deepagents==0.7.11`, a replacement `FilesystemMiddleware` accepts
`backend=` and `tools=` publicly, but its permission constructor argument is
currently named private `_permissions=`. Implementation must isolate this in the
AI adapter factory, pin the exact package version, and fail startup if the
signature changes. Passing `permissions=` only to `create_deep_agent()` is not
accepted as proof that a replacement instance retained the rules.

Observed async middleware onion order:

```text
A.before -> B.before -> A.wrap_enter -> B.wrap_enter
-> B.wrap_exit -> A.wrap_exit -> B.after -> A.after
```

At an interrupt boundary, the `after` hooks run when that interrupted step is
resumed, before the next model step. Telemetry and limits must be designed for
this actual ordering.

## PostgreSQL Checkpointer matrix

Commands: `checkpointer_spike.py start`, a new Python process running
`checkpointer_spike.py resume --checkpoint-id <accepted-id>`, then
`checkpointer_spike.py delete`.

| Capability | Result |
|---|---|
| `AsyncPostgresSaver.setup()` against PostgreSQL 17 | PASS |
| AES encrypted serializer read/write | PASS |
| Stable server-owned thread | PASS |
| Single `ask_teacher` interrupt and `respond` only | PASS |
| `durability="sync"` with a Checkpointer | PASS |
| Raw latest branch deliberately differs from accepted branch | PASS |
| New process resumes the explicit accepted Checkpoint, not raw latest | PASS |
| Resume produces a new Checkpoint and final business projection | PASS |
| `get_state` reprojects without a model/tool replay | PASS |
| Database payload scan finds none of the synthetic question/answer markers | PASS |
| First active-resume CAS claim wins; concurrent second claim fails | PASS |
| Stale revision commit is rejected | PASS |
| Completed-turn fallback stays on one Checkpointer thread | PASS |
| Thread deletion succeeds and leaves no history | PASS |

The Spike separately reproduced a LangGraph 1.2.11 defect: invoking a graph with
`durability="sync"` but no Checkpointer warns that durability has no effect and
then raises an internal `AttributeError`. Therefore only
`standard_cocreator` passes `durability="sync"`; stateless batch and coverage
agents omit the argument entirely.

## Locked implementation decisions

- Register the exact model-level `HarnessProfile` once during Worker startup;
  never re-register it per request because profile registration merges.
- Disable the general-purpose subagent and assert that `task` is absent.
  Deep Agents 0.7 no longer adds Todo middleware by default, but startup still
  asserts that `write_todos` is absent.
- Use one replacement `FilesystemMiddleware` per file-reading Agent with an explicit
  read-tool allowlist, `ReadOnlyEvidenceBackend`, and first-match-wins rules:
  allow the current `/evidence/**` scope, deny all other reads, deny all writes.
- Add one stateless sync/async model-tool-surface middleware per Agent. It
  exposes only the named Agent's read tools, `ask_teacher`, and/or its one
  ToolStrategy schema tool, then rejects any hidden or hallucinated tool call
  before the tool node. This is required because Deep Agents 0.7.11 requires
  `read_file` on every `FilesystemMiddleware` allowlist, while the coverage
  reviewer must expose no filesystem tool.
- Fix structured output to `ToolStrategy` and treat any parsing error,
  `invalid_tool_calls`, zero/multiple `ask_teacher` calls, or unsupported
  decision type as a terminal attempt failure.
- Use `AsyncPostgresSaver` only for `standard_cocreator`; keep Store/Memory
  disabled. Business tables remain authoritative and persist only the accepted
  Checkpoint pointer plus business projections.
- Run Checkpointer `setup()` as a deployment migration, not in request or
  normal application startup.
- Use `durability="sync"` only for the checkpointed co-creator. Omit it for
  stateless Agents.
- If an accepted Checkpoint is missing or the pinned profile/graph version is
  incompatible, fail closed and create an explicit continuity reset; never
  adopt raw thread latest.

## Reproduction contract

Install the exact versions above into a disposable Python environment. Then:

```bash
SPIKE_ANTHROPIC_API_KEY='<configured token>' \
SPIKE_ANTHROPIC_BASE_URL='<configured relay URL>' \
SPIKE_MODEL_ID='<configured model id>' \
python research/spikes/provider_capability_spike.py --negative-checks

SPIKE_DATABASE_URL='<temporary PostgreSQL URL>' \
python research/spikes/checkpointer_spike.py static

SPIKE_DATABASE_URL='<temporary PostgreSQL URL>' \
python research/spikes/checkpointer_spike.py start

SPIKE_DATABASE_URL='<temporary PostgreSQL URL>' \
python research/spikes/checkpointer_spike.py resume --checkpoint-id '<accepted id>'

SPIKE_DATABASE_URL='<temporary PostgreSQL URL>' \
python research/spikes/checkpointer_spike.py delete
```

All commands must print only result booleans, package versions, model aliases,
and error types. They must not print credentials, relay URLs, prompts containing
business evidence, raw Checkpoint payloads, or private reasoning.
