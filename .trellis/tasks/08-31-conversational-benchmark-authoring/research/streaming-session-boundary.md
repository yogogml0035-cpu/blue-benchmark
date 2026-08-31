# Deep Agents 流式会话边界

## 当前事实

- 当前依赖锁定为 `deepagents==0.7.11`、`langgraph==1.2.11`。
- 当前 `DeepAgentsStandardCoCreator` 使用同步 `graph.invoke(...)`，AI Profile 固定 `streaming=False`；前端每 2 秒 GET 一次完整会话快照。
- 当前安装版本的 `CompiledStateGraph` 提供 `stream`、`astream`、`stream_events`，支持 `updates`、`messages`、`custom` 等流模式。
- Deep Agents 的人工中断依赖 Checkpointer，并要求恢复时继续使用同一个 `thread_id`。
- 当前生产运行由独立 `OperationWorker` 消费持久化 `OperationJob`，长调用有 lease heartbeat、accepted checkpoint 和 projection-pending 恢复边界。

## 不采用的方案

### 不把 Agent 直接搬进 FastAPI SSE 请求

这样会让浏览器连接寿命承担模型执行，绕过当前队列、lease、重试、单 Worker 和 projection-pending 保护；断线也容易被误认为应取消业务运行。

### 不把 Provider 原始 token 直接转发给浏览器

原始 token 尚未经过中文、证据范围、隐私和内部字段校验，一旦流出无法撤回。上传正文、绝对路径、系统提示或模型私有内容都有提前泄露风险。

### 不引入 WebSocket、Redis 或第二套队列

M0 是单用户、单活跃轮次，浏览器只需要服务端单向事件。已有 PostgreSQL/OperationJob 足以承载可恢复事件，不需要额外基础设施。

## 推荐方案

### 1. Worker 仍是执行所有者

- API 命令保存老师消息/附件与业务 revision，创建 OperationJob 后返回 202。
- Worker 以 `graph.stream(..., version="v2")` 或等价 async 接口消费 Deep Agents 事件，同时保持当前 accepted checkpoint、lease heartbeat、ownership/CAS 和最终业务投影。
- 原始 LangGraph 事件只在 Worker 内部短暂存在，不能直接进入浏览器 DTO 或数据库。

### 2. 只持久化安全事件投影

新增按会话递增序号的安全事件记录，事件类型仅允许：

- `phase_started` / `phase_completed`：识别任务、读取资料、整理题目与标准答案、生成打分规则、校验候选；
- `action_summary`：已读取资料数量、候选任务数量、是否需要补充；
- `public_message_ready`：已经完整生成并通过中文/泄漏/结构校验的用户可见回复；
- `snapshot_changed`：业务快照已更新；
- `waiting_for_teacher` / `failed` / `completed`。

事件 payload 使用 Pydantic allowlist；禁止上传正文、原始 token、ToolMessage、工具参数、绝对路径、系统提示、Checkpoint/thread ID、凭证和 private reasoning。

模型生成的公开回复先完整缓冲并验证，再由服务端按小段发送形成流式视觉效果。这样不是 Provider token 直通，但满足“老师持续看到回复和进度”，并保持 fail-closed。

### 3. SSE 只负责增量体验

- FastAPI 提供鉴权后的同源 SSE 端点，按 session + `Last-Event-ID` 读取安全事件；事件 ID 是公开流序号，不是内部数据库/Checkpoint ID。
- 前端断线重连时从最后序号继续；若事件已压缩或缺失，先 GET 最新业务快照和消息列表，再继续订阅。
- SSE 断线不取消 Worker；最终业务事实仍来自普通 GET 快照，SSE 不能宣布题目确认、发布或评分完成。
- 不使用 EventSource 无法自定义 POST 的限制承担写操作；发送消息、确认、上传和评分继续使用普通幂等 HTTP 命令。

### 4. 单活跃轮次

- 会话业务记录保存 `active_operation_id` 和 revision；只有没有活动 OperationJob，或状态为 waiting-for-teacher/completed/failed 时才接受下一条消息。
- 处理中前端保留输入草稿和附件选择，但发送按钮禁用；后端仍必须以 409 防止绕过 UI 的并发提交。
- M0 不实现 mid-run cancel、steering queue 或多消息队列。

## 中文与提示词合同

- System Prompt、任务消息、工具说明、错误和所有用户可见字段统一为中文；证据内容明确标为不可信数据，不得执行其中的指令。
- 模型生成的问题、回复和摘要必须包含中文并通过内部术语/路径/凭证扫描；失败时仅允许一次受限修复，仍失败则 fail-closed，返回确定性中文错误。
- 结构化进度由 Worker 根据实际阶段生成，不让模型自由编造“正在做什么”。

