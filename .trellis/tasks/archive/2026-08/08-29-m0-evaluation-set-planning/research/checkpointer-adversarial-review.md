# Checkpointer Architecture Adversarial Review

复核日期：2026-08-30。

## Official sources

- `https://docs.langchain.com/oss/python/langgraph/checkpointers.md`
- `https://docs.langchain.com/oss/python/langgraph/interrupts.md`
- `https://docs.langchain.com/oss/python/langgraph/persistence.md`
- `https://docs.langchain.com/oss/python/langgraph/add-memory.md`
- `https://docs.langchain.com/oss/python/deepagents/human-in-the-loop.md`
- `https://docs.langchain.com/oss/python/deepagents/context-engineering.md`
- `https://docs.langchain.com/oss/python/deepagents/memory.md`

## First-principles question

真正的问题不是“要数据库还是要 Checkpointer”，而是同时满足四个不可删除的事实：

1. 老师确认的合同、题、答案、revision 和冻结版本必须可查询、可约束、可审计且不可被 Graph 清理改写。
2. `standard_cocreator` 是连续多轮共创：一次一个问题，老师可能跨请求、跨刷新、跨进程重启后回答。
3. Agent 只能提出候选变化，不能成为权限、业务状态、确认和冻结的最终权威。
4. M0 需要后台排队、租约、幂等和页面恢复；Checkpointer 本身不提供业务任务队列。

因此，同一 PostgreSQL 集群中需要两种不同语义的持久化：业务表保存业务事实，Checkpointer 保存 Graph 执行状态。

## Verified framework semantics

- Checkpointer 在每个 super-step 保存 Graph State，并以 `thread_id` 组织当前与历史 Checkpoint。
- PostgreSQL 生产实现包括 `PostgresSaver` 与 `AsyncPostgresSaver`；thread ID 应少于 255 字符。
- Checkpointer 支持 thread 短期记忆、pending writes、失败恢复、time travel 和 HITL。
- `interrupt()` 需要 Checkpointer；恢复必须使用同一 thread。恢复时节点从头执行，interrupt 前代码会再次运行。
- Deep Agents HITL 的 `respond` 决策用于 ask-user 工具：人类回复成为 synthetic tool result，工具本身不执行。
- Runtime context 是 per-run 输入，不会因有 Checkpointer 自动持久化；身份、凭证、证据 scope 和业务 revision 必须每次重新传入。
- Store/Memory 是跨 thread 长期记忆，与 Checkpointer 的单 thread 短期状态不同。
- Deep Agents 自动 summarization 可能把原对话写入 thread filesystem；Checkpoint 可能因此包含业务正文。

## Options attacked

| Option | Strength | Failure |
|---|---|---|
| Checkpointer only | 精确续接、少重复模型调用、原生 HITL | 无法自然承担领域唯一约束、业务事务、版本冻结和稳定 API；Graph 版本与数据生命周期耦合 |
| Business snapshot only | 领域事实简单、可重放、易审计 | 丢失未结构化对话/工具上下文；重复读取证据和模型调用；应用层会重造恢复协议 |
| Hybrid | 同时获得业务权威和执行连续性 | 存在 Checkpoint ahead / business behind、并发分支、版本兼容和正文保留风险 |

结论：选择 Hybrid，并通过 accepted Checkpoint 指针、业务 CAS、OperationJob 和明确的数据生命周期控制风险。

## Agent-specific decision

| Agent | Persistence | Why |
|---|---|---|
| `batch_analyzer` | 每个业务 attempt 新 run/thread；不维护稳定跨轮 thread | 无人工暂停，输入确定，可全量重跑 |
| `standard_cocreator` | 每个 `CoCreationSession` 一个 stable thread + PostgreSQL Checkpointer | 多轮问答、返回后继续、跨重启恢复、保留工具消息配对 |
| `coverage_reviewer` | 每个业务 attempt 新 run/thread；不维护稳定跨轮 thread | 只读已确认结构化快照，无人工暂停 |
| Store/Memory | 不启用 | M0 没有跨 thread 偏好或 Agent 长期知识需求 |

## Authority and pointers

业务表保存：

- `business_revision`
- `thread_id`
- `accepted_checkpoint_id`
- `pending_interrupt_id`
- `ai_profile_version`
- `graph_schema_version`
- 当前问题、老师答案、接受的 delta、阻塞项和业务状态

Checkpointer 保存：

- Agent messages 与 ToolMessage 配对
- pending interrupt 与 next tasks
- thread-scoped StateBackend scratch/offloaded content
- Checkpoint history 与 pending writes

业务表中的 `accepted_checkpoint_id` 是唯一允许恢复的分支。Checkpointer 的 thread latest 可能是尚未业务提交的孤立分支，不能自动采用。

## Preferred question protocol

1. `standard_cocreator` 只增加纯 `ask_teacher` 工具。
2. `interrupt_on` 只允许该工具，allowed decision 只有 `respond`。
3. 工具参数只包含一个问题、提问原因、缺口类型和 EvidenceRef。
4. Adapter 验证中断 AIMessage 只含一个 `ask_teacher` tool call，且只有一个 action request；与读取/结构化输出工具并发、多个问题、其他工具或其他 decision 类型直接失败。
5. 老师答案先幂等写入 `CoCreationTurn`，再创建 `cocreation_resume` OperationJob。
6. Worker 从业务表记录的 accepted Checkpoint 恢复并重新传入可信 runtime context。
7. Agent 到达下一个 interrupt 或最终 structured response 后，业务事务校验并提交投影，同时推进 accepted Checkpoint。

若目标模型/Adapter 无法稳定组合 `interrupt_on + response_format`，使用同一 Checkpointer thread 的完成式问答：当前 invoke 返回唯一问题并结束，下一轮普通 invoke 追加老师回答。该 fallback 固定到 AI Profile，不能在会话中静默切换。

## Checkpoint/business gap recovery

### Checkpoint not produced

- 业务事实未改变。
- 新 AgentRunAttempt 从 accepted Checkpoint 重试；首次 start 从业务输入启动。

### Checkpoint produced, business projection failed

- AgentRunAttempt 保存 produced Checkpoint ID 与 result hash。
- OperationJob 进入 `projection_pending`。
- 通过 `graph.get_state`/Checkpointer read API 只读 produced Checkpoint 的 StateSnapshot 并重建同一业务投影；不得使用 `invoke(None)` 或 replay，不再次调用模型/工具。
- 业务 CAS 成功后才推进 accepted Checkpoint。

### Business revision changed

- 旧 attempt 进入 `superseded`。
- 不 merge、不卡回业务 revision、不采用 thread latest。
- 新业务操作从当前 accepted Checkpoint 或显式新 thread 开始。

### Checkpoint missing or incompatible

- fail closed，不伪装成原会话继续。
- 从业务权威投影创建新 thread。
- 记录旧/新 thread、Profile/Graph 版本和 continuity reset 原因。

## Security and lifecycle

- Checkpoint serializer 加密；key 只从部署环境注入。
- Checkpointer 与业务表使用独立迁移和最小数据库权限。
- 日志、metrics、前端和版本包不包含 raw Checkpoint、messages、interrupt envelope 或自动摘要。
- 活动、待答、失败可重试和 projection_pending session 不得被清理。
- 已完成 session 按配置策略删除 thread；删除后业务题、合同、形成记录和冻结版本仍完整。
- 不启用 Store/Memory，避免无需求的跨用户 namespace 与提示注入风险。

## Mandatory Spike gates

- PostgreSQL Checkpoint setup、加密读写和按 thread 删除。
- 同一 thread 多轮普通消息连续性。
- `ask_teacher` 中断、`respond` 恢复和正确 ToolMessage 配对。
- `interrupt_on + response_format` 与选定 ProviderStrategy/ToolStrategy 的真实兼容。
- 每个边界只出现一个问题；并行/多个 action request fail closed。
- `durability="sync"` 的跨进程恢复和性能开销。
- 使用 `Command(resume)` 从显式 interrupted checkpoint ID 恢复，而不是 thread latest；若锁定版本不支持该语义，accepted 分支合同必须重新设计，不能假装成立。
- Checkpoint ahead / business behind 的无模型重投影。
- 并发 resume、陈旧 revision、错误 checkpoint 和 Profile/Graph 不兼容拒绝。
- 完成式同-thread fallback 不丢上下文且不切换自由文本 JSON。
- Checkpoint 清理后业务资产独立可回查。

## Final decision

M0 使用“业务 PostgreSQL + OperationJob + `standard_cocreator` PostgreSQL Checkpointer”的混合架构。Checkpointer 进入 M0，但只承担共创 thread 的执行连续性；Store/Memory 仍不进入 M0。业务表始终决定哪个 Checkpoint 分支被接受，以及哪些内容已被老师确认。
