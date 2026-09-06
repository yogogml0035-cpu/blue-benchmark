# 持久化、消息管理与中间件核查

状态：本轮增量研究，仅规划。用户明确要求保留完整生成过程和上下文，为 M1 的中断恢复、询问与聊天提前设计运行基础。没有安装依赖、初始化检查点、修改数据库或调用模型。

## 1. 运行环境是实查结果，不是历史记忆

| 项目 | 本轮只读核查结果 |
| --- | --- |
| Docker | `desktop-linux` 下容器 `skill-eval-platform-postgres` 正在运行，镜像 `postgres:17`，映射本机 5432。 |
| 业务库 | 主工作区和本任务 `.env` 的脱敏目标均为 `127.0.0.1:5432/skill_eval`，使用 `postgresql+psycopg`。 |
| 检查点库 | 两处 `.env` 均已配置 `CHECKPOINT_DATABASE_URL`，目标为同一实例的 `skill_eval_checkpoint`。 |
| 实际连接 | 两库均可只读连接，服务器报告 PostgreSQL 17.11；核查事务的 `transaction_read_only=on`。 |
| 已有检查点 | 专用库中存在 `checkpoint_migrations`、`checkpoint_blobs`、`checkpoint_writes`、`checkpoints`；迁移号最大为 9，核查时 checkpoints 有 4,415 行。只读表结构/计数，没有读取检查点内容。 |
| 密钥 | `.env` 中存在 `LANGGRAPH_AES_KEY`；未输出其内容，也未据此声称当前运行已启用加密或格式已验证。 |
| 当前代码 | `backend/app` 没有接入 `PostgresSaver`、`PostgresStore`、thread/checkpointer/interrupt；当前设置和 `.env.example` 没有对应接入合同。环境变量存在不等于已接入。 |
| 当前依赖 | `.venv` 未安装 deepagents、langgraph、langchain、langgraph-checkpoint-postgres、psycopg-pool；psycopg 为 3.3.4。 |
| 部署差异 | 当前 `deploy/compose.yaml` 仍指向 postgres:16-alpine，不等于正在运行的本机 postgres:17。本轮使用既有 Docker 实例，不自动重建、替换或降级容器。 |

既有检查点库不是空库，上表是核查当时的只读事实。后续 D21 已授权在本次重构切换时一次性清理当前项目测试数据，执行边界见 design.md 第 7.1 节；本轮没有清表、迁移、密钥轮换或重放旧线程。新运行使用新代码分配的线程，不能以“接回数据库”为由恢复旧共创流程。

## 2. 最新发布与技能例子的交叉验证

- 本轮实时读取官方 PyPI，下载 wheel 到内存并验证 SHA256、AST 检查，没有安装或执行发布包。最新正式 Deep Agents 仍为 `0.7.13`；最新 `langgraph-checkpoint-postgres` 为 `3.1.2`。实施和交付前继续重新核查，而非把本轮版本固定为未来目标。
- 0.7.13 的 `create_deep_agent` 接受 `checkpointer`、`store`、`backend`、`middleware`、`context_schema`、`state_schema` 等，但没有 `harness_profile` 参数。
- 该版本 `StateBackend.__init__` 不接 runtime 参数；`StoreBackend.__init__` 提供 `namespace` 与 `store`。因此不能直接抄旧 Skill 中 `StateBackend(runtime)` 或 `create_deep_agent(harness_profile=...)` 的示例。
- PostgresSaver 发布包包含 `setup`、`get_tuple`、`put`、`put_writes`、`delete_thread` 等能力，也包含 Postgres Store 实现。包具备能力，不代表当前 9 号数据库迁移、serializer 或模型流式适配已完成验证。

## 3. 按用户要求读取的技能与实际采用的经验

已读取 ecosystem-primer、deep-agents-core、deep-agents-memory、langgraph-persistence、langgraph-human-in-the-loop，以及指定的 langchain-dev-guide；后者重点读取 `reference/{deepagents,middleware,streaming,structured-output,model-integration}.md` 的相关部分。

| 经验 | 本次采用方式 |
| --- | --- |
| Backend、checkpointer、Store 是不同职责 | StateBackend 的文件在图状态中，可由 checkpointer 跨重启恢复同一线程；Store 才负责跨线程共享，不把“默认 backend”误读为一定落宿主机磁盘。 |
| 内置上下文管理也使用文件路径 | 官方说明工具结果和历史会使用内部目录；新权限不能误禁这些工作路径，也不能让它们落到宿主机真实项目目录。 |
| middleware 顺序 | before 按顺序、after 逆序、wrap 为嵌套。还要检查 Deep Agents 自带 middleware 与用户 middleware 合成后的真实顺序，不只看自己传的数组。 |
| wrap 内直接改对象不等于持久更新 | 请求临时调整用 request override；持久状态更新用 node hook 返回值，或当前官方支持的 ExtendedModelResponse/Command。避免多个 middleware 争写同名字段。 |
| interrupt 与恢复有特定协议 | 自定义 interrupt 的回复和 HITL 工具审批的 decisions 合同不能混用；恢复使用同一线程的 Command(resume)，不是重新提交全部 messages。 |
| interrupt 会重跑当前节点前半段 | 不在 interrupt 前执行无幂等保护的外部副作用；观察/重试 middleware 不把中断吞成普通异常。 |
| 流式 API 与纯工具可测试性 | 原生 v3 事件与注入的消息 sink 配合；不为取 custom 进度强制让所有纯业务工具依赖全局 get_stream_writer。 |
| namespace 与运行环境 | 当前是本地 Worker，不假定存在 LangGraph Server 的 rt.server_info.user.identity；身份和范围由应用实际登录/场景凭证合同提供。 |
| reasoning/tool-call 兼容 | 保留所选 provider 协议要求的消息关联字段；不把非流式成功视为多轮工具调用、流式和恢复均可用，也不把内部推理字段公开给 UI。 |

技能是踩坑线索，不是固定 API 真理。本文所有具体参数以当前发布包与官方正文为准，不自动引入技能中提到的第三方框架、ContextSeek 或新的外部记忆服务。

## 4. 需要在设计中落实的原理

- Checkpointer 保存图执行状态和可恢复步骤，不是逐 token 的完整界面日志。完整公开消息另存；模型输入可压缩，公开历史不能因此被删成摘要。
- 同一 PostgreSQL 实例可继续使用当前两个数据库：业务/消息事实留在 skill_eval，框架检查点留在 skill_eval_checkpoint；不需要另建一套 Docker 服务。
- PostgreSQL 接入并不让业务表与检查点自动成为一个事务。必须覆盖“模型完成且 checkpoint 已写，但业务保存还没完成”的恢复路径，不能每次重试都重新生成。
- Job lease/CAS 保护业务提交，不自动保护同一线程的 checkpoint 写入。需线程单写者和失租停止机制，不能让两个 attempt 并发污染同一图状态。
- 当前管理 API 只校验登录，并没有已实现的“每位老师拥有私有题库”合同；外部收题凭证才绑定 scene。新 thread_id 和 Store namespace 不能凭空充当权限系统。
- M0 的运行恢复基础现在设计并纳入验收；M1 的聊天业务、提问工具和用户回复入口另按阶段启用，不因为未来需要而现在恢复旧共创页面或增加空的 M1 状态入口。

## 5. 尚未取得的证据

未进行依赖解析安装、PostgresSaver setup、serializer/密钥格式试验、进程崩溃恢复、双 Worker 竞争、真实 provider 多轮消息恢复、SSE 完整内容回放、M1 中断问答试跑。本轮元数据和静态源码检查不能替代这些验收。

## 官方来源

- `https://docs.langchain.com/oss/python/langchain/middleware/custom`
- `https://docs.langchain.com/oss/python/langgraph/checkpointers`
- `https://docs.langchain.com/oss/python/langgraph/stores`
- `https://docs.langchain.com/oss/python/langgraph/interrupts`
- `https://docs.langchain.com/oss/python/deepagents/backends`
- `https://docs.langchain.com/oss/python/langchain/event-streaming`
- `https://www.postgresql.org/docs/17/explicit-locking.html`
- `https://pypi.org/pypi/deepagents/json`
- `https://pypi.org/pypi/langgraph-checkpoint-postgres/json`
