# M0 主观评测集实施计划

## 1. Execution Strategy

该任务包含五个可以独立验证但顺序依赖明显的交付面，批准实施后建议由当前任务作为父任务，再创建以下 Trellis 子任务：

1. `m0-persistence-ingestion`：PostgreSQL 业务表、Checkpoint 基础设施、文件存储、上传批次和后台任务。
2. `m0-deep-agent-cocreation`：受限只读 Deep Agent、稳定共创 thread、HITL 问答、任务分组、场景合同与单题共创。
3. `m0-evaluation-versioning`：合同影响审查、下一版本草稿、冻结与三视图版本包。
4. `m0-frontend-workflow`：场景首页、上传/分组、共创、版本与历史页面。
5. `m0-integration-acceptance`：真实样本闭环、文档、视觉与跨层验收。

父任务拥有 PRD、跨子任务合同和最终集成验收；子任务按 1 → 2 → 3 → 4 → 5 执行。不要并行修改同一 OpenAPI 字段或生成类型。

## 2. Phase 0 — Replace obsolete planning contracts

- [x] 已按 `research/ui-adversarial-review.md` 更新 `.interface-design/system.md`：保留来源分组、一屏一节和浅色可访问性；加入“当前 / 题 / 版本”、一问一变一确认、按需“标准与依据”、中性主动作、较少表面和上下文文字预算，并明确这些是尚未实现的目标合同。
- [x] 已删除设计系统中的过时规则：评测集（未来）、禁止任何场景内导航、所有说明强制 30 字、生产 JSON 编辑器、默认机器码、通用卡片墙、高饱和蓝主按钮和四路由假设。
- [ ] 实施开始后，在当前文档重组结果上建立新的 `docs/architecture.md` M0 事实边界；本轮发现原文件已被其他改动删除，因此未恢复或覆盖。
- [ ] 实施开始后建立新的 case-builder/evaluation-set Feature 文档；当前旧文件已被其他改动删除，本轮未恢复或覆盖。
- [x] 已在任务 `research/adr-0002-m0-runtime-and-persistence.md` 固化“业务状态与 Checkpoint 分离、同时持久化”、Deep Agents + OperationJob + accepted Checkpoint + ask_teacher/respond + CAS，明确 Store/Memory 禁用。实施后再迁入项目 ADR 事实层。
- [x] 当前新增文档均标注规划/Preview/Spike 状态，没有把未来能力写成已运行产品事实。

Validation:

```bash
rg -n "评测集（未来）|Asset Rail|Formation Receipt" .interface-design/system.md .trellis/tasks/08-29-m0-evaluation-set-planning
```

预期：只剩明确的历史/迁移说明，没有两个并存的当前方案。`docs/` 若继续被当前外部改动删除，则实施时按最终目录结构新建事实文档，不在本轮恢复。

## 3. Phase 1 — Persistence and domain foundation

- [ ] 引入 PostgreSQL Repository、数据库会话和迁移；先保持现有 `auth`、`workspaces` 行为与错误码。
- [ ] 为 `case_builder` 增加 UploadBatch、EvidenceFile、FileDisposition、TaskPackage、SkillRunEvidence、CoCreationSession/Turn、QuestionRevision、TeacherFeedback、StandardPromotionProposal 表；CoCreationSession 保存 stable thread、accepted Checkpoint、pending interrupt、业务 revision、AI Profile 和 Graph Schema 版本。
- [ ] 在 `app/lib/operations` 增加 OperationJob、AgentRunAttempt、租约/幂等与单消费者；它统一覆盖批次分析、共创、覆盖审查和冻结，只调度目标 Feature Service，不直接读写其 Repository。
- [ ] 引入 `langgraph-checkpoint-postgres` 与生产异步 Checkpointer；业务迁移和 Checkpointer `setup()` 分开执行。应用启动只验证两套 schema ready，不自动建表。
- [ ] 为 Checkpointer 配置加密 serializer、独立连接权限、thread 删除能力和保留清理作业；加密 key 只从部署环境读取。
- [ ] 新建真实 `evaluation_sets` Feature，拥有 ScenarioContractRevision、WorkingSetDraft/Member、ContractImpactReview、CoverageSnapshot、EvaluationSetVersion。
- [ ] 为本地存储创建服务端生成键的 adapter；HTTP 永不返回绝对路径。
- [ ] 增加事务、唯一约束和版本/幂等字段：每场景一个 working draft、连续版本号、同 target/revision/command 单运行、同共创 session 单活动 resume、同 turn 单回答、同修订单确认。
- [ ] 将测试从 Repository `reset()` 迁移到事务/测试数据库隔离。

Validation:

```bash
cd backend && uv run pytest -q
```

必须覆盖：重启后账号/场景/上传批次仍存在，跨用户 403，stable thread 仅服务端可见，同 session 并发 resume 被拒绝，唯一操作/回答约束与陈旧修订 409，清理 Checkpoint 不删除业务资产。

## 4. Phase 2 — Safe ingestion and background jobs

- [ ] 实现多文件与 ZIP 上传；初始白名单 `.md/.txt/.json/.jsonl/.zip`，限制文件数、单文件大小、展开总大小和嵌套层级。
- [ ] 使用库 API 安全解包，拒绝绝对路径、`..`、符号链接、特殊文件和 zip bomb；禁止通过 shell 解包用户内容。
- [ ] 为每个文件计算 SHA-256、识别 media type、生成 parse state 与 locator 视图。
- [ ] 上传成功返回 `202` 与完整 UploadBatch 快照，不等待分析。
- [ ] 实现通用 OperationJob 单消费者：支持 `batch_analysis`、`cocreation_start`、`cocreation_resume`、`cocreation_reproject`、`coverage_review`、`freeze_package`，具备 claim lease、过期回收、target/revision/command/accepted-checkpoint 幂等、启动恢复、有限重试和 commit-time CAS；迟到分支进入 `superseded`；当前不引入 Celery/Redis。
- [ ] 实现轮询 GET；GET 不推进状态，不创建运行。
- [ ] 实现 `StudioProjection` 与 discriminated `next_action`；active_operation 只暴露业务阶段，不序列化 Worker/Agent 内部状态。
- [ ] 增加文件角色、required/ignored、visibility 决策接口和冻结前门禁函数。

Validation:

```bash
cd backend && uv run pytest -q
```

必须覆盖：路径穿越、符号链接、超限、损坏 ZIP、部分不支持文件、所有 OperationJob kind 的重复命令、进程重启后的租约回收、失败重试不产生第二运行、错误 accepted Checkpoint/迟到分支不覆盖新 revision、GET 轮询无副作用。

## 5. Phase 3 — Restricted Deep Agents and AI Profile

- [ ] 锁定 Deep Agents/LangChain/LangGraph/`langgraph-checkpoint-postgres`/模型 adapter 版本，先做隔离 Spike；不要在 Spike 通过前实现业务 Feature。
- [ ] 验证按精确模型键、仅在进程启动时注册的 HarnessProfile 能关闭默认 general-purpose subagent/`task`；不添加 Todo、Skills、Memory 或任何同步/异步 subagent，并证明请求处理中不会重注册或合并污染另一 AI Profile。
- [ ] 增加 Worker 启动工具面断言：batch Agent只允许 read/list/search，co-creator 额外只允许纯 `ask_teacher`，coverage Agent无文件工具，三者均无 task/execute/write/edit/delete；断言失败时 Worker fail closed。
- [ ] 实现无共享可变状态的只读 `EvidenceBackend`：从 typed `AgentRunContext` 解析当前 scope，只读 canonical view，写/改/删固定拒绝；开发 FilesystemBackend 只作为隔离临时目录对照，不进入生产默认。
- [ ] 验证 `batch_analyzer` 只能读当前批次、`standard_cocreator` 只能读当前任务包、`coverage_reviewer` 无文件工具；替换内置 FilesystemMiddleware 时把 backend、permissions 和 read-tool allowlist 一起传给替换实例，permission 按 allow `/evidence/**` → deny read `/**` → deny write `/**` 排序，并用越权路径测试证明默认 allow 被兜住。
- [x] 已执行真实 endpoint capability matrix：普通工具调用、specific/forced `tool_choice`、ProviderStrategy、ToolStrategy、invalid_tool_calls、空 tools、中文嵌套 Schema、多轮 tool/message roundtrip、非流式 invoke，以及 `interrupt_on + response_format + respond + 同一 thread resume`；结果见 `research/prestart-spike-results.md`。
- [x] 当前 AI Profile 固定 ToolStrategy；ProviderStrategy 实测失败，禁止 AutoStrategy 或自由文本 JSON 降级。模型/adapter/Schema 变化时必须重跑矩阵并升级 Profile。
- [ ] 实现 `EvidenceAnalyzer`、`StandardCoCreator`、`CoverageReviewer` 三个 Protocol；`StandardCoCreator` 明确提供 start/resume/reproject，生产 adapter 使用三个命名 Deep Agent，测试 adapter 使用 Fake。它们共享 AI Profile，但不是 subagents。
- [ ] 分别定义小型 `BatchAnalysis`、`AskTeacherInput`、`CoCreationResult`、完成式降级 `CoCreationTurn`、`CoverageReview` Pydantic Schema；从 `structured_response` 或唯一 `ask_teacher` action request 读取后，再执行 locator、文件归属、阻塞缺口和业务状态复验。
- [ ] 定义 EvidenceRef locator union（line range / JSON pointer / event id）并回查 canonical extracted view；模型输出路径和 quote 不能直接成为业务证据。
- [ ] 模型只通过内置只读工具获得正文；应用的 file_id、canonical locator basis 和 hash 来自确定性 manifest/adapter side-channel，不从模型文本反推，也不为 artifact 新增绕过 FilesystemPermission 的自定义读取工具。
- [ ] 系统提示词要求先读 manifest/行数，再显式 `limit`/`offset` 分页到 EOF；用超过 100 行且尾部含关键反馈的 fixture 做硬验收。
- [ ] 实现纯 `ask_teacher` 工具并配置 `interrupt_on={ask_teacher: allowed_decisions=[respond]}`；工具不得访问业务库或写文件。中断边界的 AIMessage 必须只有一个 ask_teacher tool call；与读取/结构化输出工具并发、零个/多个问题、其他 interrupt 或额外 decision 类型时 fail closed。
- [ ] 使用加密 `AsyncPostgresSaver` 编译 `standard_cocreator`；FastAPI/Worker lifespan 持有 Checkpointer 连接生命周期，部署迁移单独调用 setup。`batch_analyzer` 与 `coverage_reviewer` 不维护稳定 thread。
- [ ] 固定并测试 Deep Agents 非流式 invoke 输出协议版本，确保能稳定读取 interrupts、action_requests、review_configs、最终 value/structured_response 和 produced checkpoint config；不得混用不同文档版本的返回形状。
- [x] Spike 已证明共创 session 可用服务端 stable thread、显式 accepted checkpoint_id 和 `durability="sync"` 跨新进程恢复，而不是隐式使用 thread latest；实现仍需保持浏览器、模型和上传文件不能提供内部 ID。
- [ ] 若锁定版本不支持显式 checkpoint resume，采用 fail-closed fallback：未接受 produced 分支只能先重投影，业务/兼容性冲突必须 continuity reset 到新 thread；禁止在旧 thread 上回退恢复或默默采用 latest。
- [ ] 验证 `interrupt()` 恢复时节点前置代码重跑：Graph 内不写业务表、不发送外部消息、不产生不可幂等副作用；业务答案先写 `CoCreationTurn`，Worker 再执行 `Command(resume=respond)`。
- [ ] 实现完成式问答降级并固定到 `ai_profile_version`：如果目标模型无法稳定组合 HITL 与 response_format，仍在相同 Checkpointer thread 中用普通多轮消息继续；不得静默切换模式或退回无 Checkpointer。
- [ ] 固定并测试 built-in middleware：ModelCallLimit(run_limit)、ToolCallLimit(run_limit)、有限 ModelRetry；文件读取不配置 ToolRetry，不配置 fallback、动态模型/工具/Prompt。分别记录逻辑调用上限、传输 retry、OperationJob deadline、token/cost ceiling，不能假定它们天然共享一个计数器。
- [ ] 先用模型 callback/usage 和 OperationJob 收集无正文指标；只有证据证明不足时才实现 stateless class-based `RunTelemetryMiddleware`，使用 wrap_model_call/wrap_tool_call 计时、before_agent/after_agent 收束，trace policy 省略 payload，禁止改业务 state/prompt/model/tools。
- [ ] batch/coverage 的每次业务 retry 使用新 AgentRunAttempt/run/thread；co-creator 的业务 retry 使用新 run，但从 accepted Checkpoint 恢复。ModelRetry 的传输 retry 留在同一 run 并单独计数。
- [ ] 每次 co-creator start/resume 都重新传 typed runtime context：业务 revision、AI Profile/Graph Schema 版本、身份、evidence scope 和 deadline。Runtime context/凭证不得进入 Checkpoint state。
- [ ] 实现 AgentRunAttempt 的 base/produced checkpoint 指针和结果 hash；Graph 已推进但业务提交失败时进入 `projection_pending`，通过 `get_state`/Checkpointer read API 只读 StateSnapshot 并 reproject。禁止 `invoke(None)`、checkpoint replay、模型或工具调用。
- [ ] 老师逐轮回答使用 FastAPI 幂等命令创建 `OperationJob(kind=cocreation_resume)` 并返回 `202`；同一 session 同时只允许一个活动 resume，错误 checkpoint 或陈旧 revision 直接拒绝。
- [ ] 对模型/工具调用、总时长、上下文和输出加限制；默认禁用 streaming，不展示或持久化 private reasoning。
- [ ] Agent 图实例按 `ai_profile_version + graph_schema_version` 缓存或构建；活动旧 session 必须可路由到兼容旧图。HarnessProfile 只承载进程级安全不变量，不能用全局注册表承载会话版本。
- [ ] 实现显式 continuity reset：旧图不可恢复时从业务投影创建新 thread，记录旧/新 thread、Profile/Graph 版本和原因；不能让新图直接恢复旧 Checkpoint。
- [ ] 设计 Checkpoint 加密 key/codec 轮换：活动旧 thread 在完成、重加密或 continuity reset 前保持可读；禁止直接替换 key 造成静默不可恢复。
- [ ] 明确不配置 LangGraph Store、StoreBackend Memory 或 MemoryMiddleware；测试证明跨 session 事实只从业务表读取，不发生 thread 间隐式记忆泄漏。

Validation:

```bash
cd backend && uv run pytest -q
```

使用 Fake Adapter 机械覆盖全部状态；真实模型 Spike/Smoke Test 独立、默认不运行、不输出业务正文、private reasoning 或凭证。Spike 必须输出能力矩阵、实际 middleware 顺序、替换实例权限、Checkpoint 写入/恢复证据、interrupt envelope、respond 后消息配对、进程重启恢复、业务重投影、加密/清理和完成式降级结果，不只报告“调用成功”。

## 6. Phase 4 — Task grouping and AI-native co-creation

- [ ] 实现一个上传批次 0..N 任务分组提案；老师可确认、合并和拆分，确认后创建 TaskPackage。
- [ ] 同一真实任务的多次 Skill 运行保留为 attempts，不生成重复题。
- [ ] 初始化场景时从代表性任务包建立 ScenarioContractRevision 共创；合同确认后默认复用任务包生成第一道候选题，支持“仅初始化”。
- [ ] 实现每轮一个问题、提问原因、回答、turn delta 和当前完整投影；首次共创产生并投影 accepted Checkpoint，answer 命令保存回答后返回 `202`，后台恢复同一 thread 后再发布本轮更新与下一问。
- [ ] 将 interrupt action request 投影为业务 `CoCreationTurn`，只保存问题、原因和 EvidenceRef；不把原始 interrupt envelope、ToolMessage、thread 或 Checkpoint 暴露给前端。
- [ ] 实现 scoped retry：已有 produced Checkpoint 时只 reproject；没有 produced Checkpoint 时从 accepted Checkpoint 新建 resume attempt；老师已保存的回答不因 AI 失败丢失。
- [ ] 实现主观 JudgmentPackage 完整性门：参考/多版结果、认可与否定理由、硬门禁、最低质量线、能力、规则来源和阻塞缺口。
- [ ] 批注默认 question_only；Deep Agent只能提升级建议。老师批准后创建合同新修订并触发受影响题审查。
- [ ] 所有确认与回答幂等；AI 失败不部分确认资产。

Validation:

```bash
cd backend && uv run pytest -q
make openapi
```

必须覆盖：一批多任务、一任务多 attempts、分组合并/拆分、代表包仅初始化、一次一问、同一 stable thread 多轮回答、回答后刷新与进程重启恢复、重复 command 不重复 resume、并发 resume 被拒绝、Checkpoint ahead/业务 behind 重投影、陈旧分支 superseded、阻塞缺口、标准提案拒绝/批准、合同变化后的 review_required。

## 7. Phase 5 — Evaluation set lineage and immutable package

- [ ] 实现每场景唯一 WorkingSetDraft，从最新冻结版本派生；加入、移除、修订题只影响下一版本。
- [ ] 实现合同影响规则检查、AI 建议投影和老师最终放行；AI 不能解除 review_required。
- [ ] 实现集合硬完整性门和覆盖摘要；覆盖不足需老师确认但不设置固定题数。
- [ ] freeze 命令校验 revision/command id、保存冻结意图并创建 `OperationJob(kind=freeze_package)` 后返回 `202`；Worker 再构建 canonical Manifest、runtime/judge/provenance 三分区、分区哈希与整体哈希。
- [ ] 成功后原子创建 EvaluationSetVersion 并发布不可变包；失败不创建可见版本，重试幂等。
- [ ] 实现版本历史、Manifest API 与下载；API 和下载读取同一已生成包。
- [ ] 加断言保证 runtime 中不存在参考结果、评分规则、历史评语和老师判断。

Validation:

```bash
cd backend && uv run pytest -q
make openapi
```

必须覆盖：无题/未复核/未确认可见性/必需文件失败时冻结阻塞，覆盖警告确认，冻结中刷新恢复，重复 command 不生成第二版本，连续版本，历史不可变，打包失败回滚，包哈希稳定，runtime 泄漏测试。

## 8. Phase 6 — Frontend workflow

- [ ] OpenAPI 生成类型先行；页面与 fixtures 不手写 DTO。
- [ ] 先用真实长度内容做场景工作台静态 Preview：“当前 / 题 / 版本”、共创主画布、本轮更新、关闭/打开“标准与依据”、后台处理中、下一版与历史；桌面和窄屏视觉审查通过后再接 API。
- [ ] 将主流程收敛为 `/workspaces`、场景工作台、聚焦题详情和只读版本详情四个 route family；上传、批次、分组、场景标准不再作为老师必须理解的独立页面。
- [ ] 场景工作台只使用文字型三项导航（当前、题、版本）+ 660–720px 主画布；不做 Dashboard 卡片墙，不常驻第三列，不把“下一版/历史”拆成两项。
- [ ] 用 `StudioProjection` 驱动唯一 next_action；在“当前”内实现多文件上传、全部 OperationJob kind 的可见性友好轮询、失败重试和离开/恢复，前端不推导 Agent/Worker/Checkpoint 状态。
- [ ] 在同一工作项内实现文件角色与任务分组确认；优先原生可访问控件，不先做拖拽分组。
- [ ] 实现聚焦问答：一次一个问题、回答命令到 `202` 的短 busy、持久化处理中、本轮更新，以及默认关闭的“标准与依据”；resume 失败后保留已提交答案并显示唯一“重试整理”，老师无需重填；窄屏为全屏 sheet，已完成问答过程可按需回查。
- [ ] 前端 DTO、URL、日志和 Preview fixture 不包含 thread_id、checkpoint_id、interrupt_id、decision、Graph node 或 raw messages；开发 Preview 也只预演业务投影，不伪造内部 Checkpoint。
- [ ] 扩展一屏一节 DraftEditor，加入继承规则、本题补充、判定依据、可见性和最终定稿门。
- [ ] 从生产 DraftEditor 移除 JSON 编辑器；仅在 Preview/开发工具保留。错误机器码、Manifest hash 与 Schema 默认放入折叠技术详情。
- [ ] UI 文案使用资料、任务、场景标准、题稿、题、下一版、历史版本；三视图显示为给 Skill 的材料、评分依据、形成记录。
- [ ] 更新视觉 token/规则：主按钮使用中性深色，蓝色只用于链接/焦点/当前态；普通区块依靠留白和发丝线，控件 6–8px、焦点面 10–12px；不增加 AI 渐变、发光球、机器人图标、聊天气泡、卡中卡或逐字输出。
- [ ] 实现标准升级提案三选项与合同影响审查。
- [ ] 实现下一版本草稿、硬门、覆盖风险确认、冻结和版本历史/下载。
- [ ] 为 desktop 和 narrow viewport 完成抽屉、焦点、键盘、aria-live 和 reduced-motion 验收。
- [ ] 将旧 cases 路由重定向到场景工作台或聚焦题详情，不保留第二套编辑页面。

Validation:

```bash
cd frontend && pnpm typecheck
cd frontend && pnpm build
```

再用开发 Preview fixture 覆盖长文件名、多任务分组、后台操作、等待回答、resume 中、resume 失败但答案已保存、重投影、本轮更新极值、标准与依据、待复核、冻结阻塞、冻结中、冻结成功和版本只读状态。视觉上验证只有“当前 / 题 / 版本”、一个主按钮、一个焦点面，没有卡片墙、AI 装饰、永久第三列、Checkpoint 技术词、默认机器码或 JSON。

## 9. Phase 7 — Integration and real-sample acceptance

- [ ] 使用合成/脱敏 fixture 完成默认 CI，不把真实业务样本提交 Git。
- [ ] 用户确认稳定的本地、Git-ignored 样本目录后，使用财报 JSONL、MEGA ZIP 和媒体沟通 Markdown 做真实导入验收。
- [ ] 验证 JSONL 被识别为单一真实任务的事件流，老师反馈与多次生成保留为 attempts/feedback。
- [ ] 验证 JSONL 100 行之后和 Markdown 尾部的关键老师反馈被读取并生成有效 locator，不能只命中开头内容。
- [ ] 验证 MEGA ZIP 的讲稿、拍摄指引和对话导出被归为同一任务包并可确认角色。
- [ ] 验证媒体沟通 Markdown 被建议为 runtime 输入，不误建独立题或 judge 答案。
- [ ] 两个任务分别完成单题共创和定稿，加入同一场景下一版本草稿，冻结版本并下载三视图包。
- [ ] 在一次批次分析、一次共创回答和一次冻结过程中分别刷新/关闭重开页面；在 co-creator 已中断等待回答、答案已保存但尚未 resume、以及 produced Checkpoint 尚未投影三个点分别重启 Worker，证明恢复不丢答案、不重复模型调用、不接受错误分支。
- [ ] 完成一场共创后删除其 Checkpoint thread，验证已确认题、场景标准、形成记录、下一版本草稿和冻结包仍可完整读取；再验证活动待答 session 不会被清理任务删除。
- [ ] 验证 Checkpoint/自动摘要/interrupt envelope/内部消息没有进入三视图版本包、HTTP DTO、业务日志或浏览器页面。
- [ ] 解包版本，机械验证哈希与 runtime 信息隔离。
- [ ] 更新 README：启动 API、启动单消费者、前端地址、成功标记、失败检查和完整人工验收路径。
- [ ] 更新 Trellis specs，使规范只描述最终源码事实，不保留 Walking Skeleton 过时边界。

Validation:

```bash
make test
make build
```

浏览器验收必须真实走通，不以 Preview、HTTP 200、监听端口或文档截图替代。

## 10. Risky Changes and Rollback Points

| Risk | Guardrail / rollback |
|---|---|
| 内存 Stub → PostgreSQL | 先保持现有 auth/workspaces API 测试；迁移失败不继续 AI 层 |
| 单文件 → ZIP/多文件 | 安全解包测试先于 Deep Agent；Agent 永不直接解压或执行 |
| 同步 → 统一后台操作 | 所有 OperationJob kind 共用租约与幂等合同；GET 只读；命令到 `202` 后刷新可恢复 |
| Deep Agents API 漂移 | Adapter port + Fake；Spike 失败时停在设计修订，不把框架细节泄漏到业务 Service |
| 宿主文件泄漏 / 权限规则默认 allow | 生产 EvidenceBackend + typed scope + 工具 allowlist；替换 FilesystemMiddleware 时直接携带 permissions；allow/deny/catch-all 与跨 scope 测试 |
| Provider 不支持 forced tool_choice/JSON Schema | capability matrix 先行；固定通过的 response strategy；禁止自由文本静默降级 |
| read_file 默认 100 行 | manifest + 显式 limit/offset + EOF 证明；尾部反馈验收 |
| 一个大 Schema/万能 Agent | 三个命名 Agent + 三个小 response_format；无 subagent 委派 |
| middleware/业务层叠加重试 | 分开逻辑调用、传输 retry、deadline、token/cost 与业务 attempt；文件工具不重试；记录并测试真实 onion 顺序 |
| HarnessProfile 全局注册污染 | 只在启动时注册精确模型键的安全不变量；Agent 图按 ai_profile_version 隔离；请求中禁止重注册 |
| Checkpoint 与业务 revision 竞争 | 业务表保存 accepted Checkpoint；resume/commit 双重 CAS；不采用 thread latest；迟到分支 superseded |
| Checkpoint 已推进但业务投影失败 | AgentRunAttempt 保存 produced Checkpoint/result hash；进入 projection_pending 并重投影，禁止重复模型调用 |
| ask-user 中断协议异常 | 只允许一个 `ask_teacher` action request 和 `respond`；零个/多个/其他工具 fail closed；保留完成式同-thread 降级 |
| interrupt 恢复重跑副作用 | Graph 内不写业务表、不发送外部消息；答案和业务写入都在 Graph 外幂等执行 |
| Graph/Profile 升级破坏旧 thread | session 固定 ai_profile_version + graph_schema_version；兼容旧图路由；不兼容时显式 continuity reset |
| Checkpoint 存业务正文 | 加密 serializer、独立权限、无 payload 日志、按 thread 保留/删除；清理后业务资产仍完整 |
| Checkpointer 被误当任务队列 | OperationJob 继续拥有排队、租约、并发、重试与 `202` 页面状态 |
| 合同修订影响已定稿题 | review_required + 老师放行；禁止批量静默继承 |
| 冻结包跨存储/数据库提交 | staging + hash + ready marker；失败不创建可见版本 |
| runtime 泄漏答案 | 独立分区、Schema allowlist 与机械泄漏测试 |
| UI 规模扩张 | 保持“当前 / 题 / 版本”、一个焦点/一屏一节/一个主按钮；不建 Dashboard、模型设置或空未来页面 |
| 后端实体泄漏到 UI | StudioProjection + 唯一 next_action；业务词表；技术详情默认折叠；生产禁 JSON 编辑器 |

## 11. Pre-start Gates

在运行 `task.py start` 前必须满足：

- [x] 用户已通过本次 `/goal` 明确批准进入实施，并在完成子任务后要求多轮对抗式审查与父任务复核。
- [x] 已创建并链接 5 个子任务，每个都有顺序依赖、文件所有权、PRD、design 和 implement。
- [x] 父任务与 5 个子任务的 `implement.jsonl` / `check.jsonl` 都含真实规范/研究上下文并通过 validate。
- [x] Deep Agents/Checkpointer 锁定版本、默认 subagent 关闭、EvidenceBackend、Filesystem replacement、ToolStrategy、invalid_tool_calls、100 行截断、模型工具面和 middleware onion 顺序均有可重复 Spike 与结果矩阵。
- [x] `standard_cocreator` Spike 已验证 stable thread、加密 AsyncPostgresSaver、`ask_teacher/respond`、单中断、显式 checkpoint_id、sync durability、跨新进程 resume、无模型重投影、CAS、stale branch 拒绝和完成式同-thread 降级。
- [x] Checkpoint 迁移、AES key 注入、访问隔离、活动 session 保护、保留/删除和业务独立回查策略已确定，不含真实凭证。
- [x] 任务内 ADR 已明确业务表、OperationJob、Checkpointer 和 Store/Memory 四者职责。现有 `docs/` 正被其他改动删除，本轮未恢复或覆盖。
- [x] 场景工作台规划态 Preview 已通过桌面/窄屏审查：只有“当前 / 题 / 版本”、一个焦点面和一个主动作；`.interface-design/system.md` 已标注目标合同尚未实现。
- [x] PostgreSQL、单消费者和本地存储开发配置已确定，不包含真实凭证。
- [x] 三份样本仍可读取，并已复制到稳定、Git-ignored `.local-samples/m0/`；源/目标 SHA-256 一致。
- [x] 规划阶段未修改 `backend/`、`frontend/` 产品代码且未运行 `task.py start`；实施阶段在独立子任务分支完成并合并回 `main`，规划批准与实施批准保持分开。

## Final execution status

- 五个子任务均已归档，集成验收报告位于 `.trellis/tasks/archive/2026-08/08-30-m0-integration-acceptance/acceptance.md`。
- 父任务最终对抗式审查与修正见 `research/final-adversarial-review.md`；本地 M0 闭环已通过，生产 Checkpointer 常驻接入、自动清理消费者、完整提案 UI 和 M2 执行仍按报告标为未验证或后续边界。
