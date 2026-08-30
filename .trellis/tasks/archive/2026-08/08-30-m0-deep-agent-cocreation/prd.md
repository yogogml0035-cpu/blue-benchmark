# M0 Deep Agent 与共创

## Goal

在持久化与 OperationJob 基础上实现三种受限 Deep Agents 能力，使老师能从完整任务包确认分组、逐轮形成场景标准和单题判定依据，并在刷新、失败和进程重启后继续同一共创。

## Confirmed Facts

- 前置 Spike 已验证锁定版本、当前 Claude/Bedrock relay、ToolStrategy、单 `ask_teacher/respond`、加密 AsyncPostgresSaver、显式 accepted Checkpoint 恢复和完成式同-thread 降级。
- Provider 原生 `json_schema` 和 `temperature` 不兼容；无 Checkpointer 时传 `durability="sync"` 会触发框架缺陷。
- Deep Agent 只提出候选；业务表和老师确认始终是权威。

## Requirements

### R1 — 三个命名 Agent 与最小工具面

- `batch_analyzer`、`standard_cocreator`、`coverage_reviewer` 使用独立小 Schema 和静态提示词，不互相委派。
- 关闭 general-purpose subagent；不得暴露 task、write_todos、execute、write/edit/delete。
- 文件读取只经 ReadOnlyEvidenceBackend；每个 Agent 同时具备路径 permission、模型工具 allowlist 和隐藏调用 fail-closed。

### R2 — 稳定 AI Profile

- 固定已验证依赖、模型 adapter/ID、ToolStrategy、middleware 顺序、工具面、Schema、调用限制和问答模式为 `ai_profile_version`。
- Profile 只在 Worker 启动按精确模型键注册一次；请求中不得重注册或污染其他版本。
- parsing error、invalid_tool_calls、越权 locator、零/多问题或非 respond decision 直接失败，不做自由文本 JSON 或模型 fallback。

### R3 — 证据理解与任务分组

- Agent 必须先读 manifest/行数，再显式 offset/limit 至 EOF；模型 locator 必须回查 canonical view。
- 一批可提议 0..N TaskPackage；老师能确认、合并、拆分，多次 Skill 运行保留为 attempts。
- 文件角色、任务分组和可见性未经老师确认不是业务事实。

### R4 — 场景与单题共创

- 代表性任务包先形成场景合同，确认后默认复用为第一道候选题，可标记仅初始化。
- 每轮只有一个最高价值问题、原因、EvidenceRef 和结构化 delta；老师答案先落业务表，再由 OperationJob resume。
- 场景合同、继承规则、单题补充、主观判定依据、阻塞缺口和老师确认分层保存。

### R5 — Checkpoint 与业务恢复

- 一个 CoCreationSession 一个 stable thread；业务表只接受明确 checkpoint_id，不采用 raw latest。
- co-creator 使用加密 AsyncPostgresSaver 和 `durability="sync"`；batch/coverage 不使用稳定 Checkpointer且省略 durability。
- produced Checkpoint 已存在但业务提交失败时只用 get_state 重投影，不再次调用模型/工具。
- 不兼容或缺失 Checkpoint 只能显式 continuity reset；Store/Memory 保持禁用。

## Out of Scope

- 评测集下一版本、冻结、版本包和下载。
- 前端场景工作台。
- 跨 thread 记忆、Agent subagent、Skills、流式 token/tool UI。

## Acceptance Criteria

- [ ] Worker 启动工具面断言和权限越界测试通过。
- [ ] 当前 provider ToolStrategy/HITL 回归测试通过，负例保持 fail-closed。
- [ ] 超过 100 行且尾部有关键反馈的 fixture 被完整读取和引用。
- [ ] 一批多任务、一任务多 attempts、分组合并/拆分通过。
- [ ] 同 stable thread 多轮回答、重复 command、并发 resume、重启恢复和 stale branch 测试通过。
- [ ] projection_pending 重投影不增加模型或工具调用。
- [ ] Checkpoint 删除后，已确认场景合同、题稿、回答和形成记录仍完整。
- [ ] `cd backend && uv run pytest -q` 与 `make openapi` 通过。

## Dependencies and Ownership

- 依赖 `m0-persistence-ingestion` 完成并通过其 handoff gate。
- 独占：`backend/app/lib/ai_runtime/**`、Deep Agent adapters/profile、cocreation/task-grouping 专属模块及测试。
- 顺序扩展共享：case_builder Schema/Service/Repository/Router、Worker handler、OpenAPI；不得重写上一任务的数据库/租约合同。
- 不修改：evaluation_sets 冻结实现和前端产品文件。
