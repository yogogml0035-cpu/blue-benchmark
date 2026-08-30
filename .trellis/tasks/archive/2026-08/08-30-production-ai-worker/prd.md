# 生产 AI Worker 接线

## Goal

让常驻 Operation Worker 在正常启动时只使用真实 AI：由后台环境变量显式选择 OpenAI 兼容协议或 Anthropic 协议，使用对应模型客户端，并在同一进程生命周期内持有 PostgreSQL Checkpointer。配置不完整时必须在领取业务任务前失败，不能静默回退到 Fake adapter。

## User Value

- 用户只需配置一组明确的 Provider、模型、端点和密钥，即可让 `make worker` 执行真实 AI 分组、共创和覆盖审查。
- 切换 OpenAI 兼容服务与 Anthropic 服务不需要改业务代码。
- Worker 重启后，共创可以继续使用业务表明确接受的 PostgreSQL Checkpoint。

## Confirmed Facts

- `backend/app/lib/operations/worker.py:92` 的 `default_worker()` 只初始化 AI Profile，没有安装 `production_adapters(...)`；模块入口在 `backend/app/lib/operations/worker.py:130` 直接构造该 Worker。
- `backend/app/lib/ai_runtime/adapters.py:481` 已有三个真实 Deep Agents adapter 的组合工厂，但它没有进入常驻 Worker 生命周期。
- `_DeepAgentBase._model()` 当前只在设置了 `AI_BASE_URL` 时构造 `ChatAnthropic`，否则返回 Anthropic 模型字符串；不能选择 OpenAI 兼容协议，也没有统一校验 Provider 配置。
- `backend/app/lib/ai_runtime/checkpoint.py:69` 只有异步 PostgreSQL Checkpointer context manager，而现有 Worker、handler 和 Deep Agent 调用链使用同步 `graph.invoke()` / `graph.get_state()`。
- `.env.example` 已列出业务数据库、Checkpoint 数据库和加密密钥，但缺少真实模型配置；其中 Checkpointer URL 使用了 SQLAlchemy driver scheme，生产 Checkpointer 需要 psycopg 可连接的 PostgreSQL URL。
- 现有自动化测试依赖确定性的模块级 Fake adapters；它们仍需要保留，但不能成为正常常驻 Worker 的隐式默认运行路径。

## Requirements

### R1 — 显式 Provider 配置

- 使用 `AI_PROVIDER=openai|anthropic` 显式选择协议，不根据已有 Key 或 Base URL 猜测 Provider。
- 使用统一的 `AI_MODEL`、`AI_API_KEY` 和可选 `AI_BASE_URL` 配置模型：
  - `openai` 使用 `ChatOpenAI`，既支持 OpenAI 官方端点，也支持遵循 OpenAI Chat Completions/tool-calling 合同的第三方端点；
  - `anthropic` 使用 `ChatAnthropic`，既支持 Anthropic 官方端点，也支持兼容 Anthropic Messages API 的端点。
- `AI_PROVIDER`、`AI_MODEL` 或 `AI_API_KEY` 缺失、Provider 值不受支持、Base URL 非 HTTP(S) 时，生产 Worker 必须在领取 OperationJob 前以不含密钥的明确错误退出。
- 不发送 `temperature`，保持现有非流式、ToolStrategy、调用次数和重试边界。
- Provider、模型或端点改变时，AI Profile 兼容指纹也必须改变；旧 Checkpoint 不得被新运行时误判为兼容。

### R2 — 生产 Worker 生命周期

- 正常 `make worker` 默认进入 production 模式，启动顺序为：校验模型配置 → 构造真实模型与 adapters → 连接并验证独立 PostgreSQL Checkpointer → 安装 adapters → 开始领取任务。
- 同步 Worker 必须使用同步 `PostgresSaver`；连接和 saver 在 Worker 整个运行周期内保持有效，并在进程退出时关闭。
- Checkpointer schema 仍由 `make checkpoint-setup` 显式创建；Worker 只做 readiness 检查，缺表时提示先运行该命令，不在进程启动时偷偷迁移。
- `CHECKPOINT_DATABASE_URL` 必须与 `DATABASE_URL` 指向不同数据库；URL 和加密密钥错误不得降级为无 Checkpointer 运行。
- `--once` 与常驻循环使用同一生产接线。
- Fake 只允许自动化测试或显式 `AI_RUNTIME_MODE=fake` 的本地运行；`.env.example` 和 README 的正常启动路径使用 production。

### R3 — 兼容性与可验证性

- 增加 `langchain-openai` 作为锁定依赖；不引入第三方通用 Provider adapter 或新的配置框架。
- 单元测试覆盖两个 Provider 的模型构造、配置失败、密钥不泄露、AI Profile 指纹变化、生产 adapters 安装、同步 Checkpointer 生命周期和 Fake 显式模式。
- 增加显式真实 Provider smoke 命令，使用合成输入验证当前端点至少能完成本项目依赖的 tool calling 与结构化输出；只输出 Provider、模型、PASS/FAIL 和错误类型，不输出密钥、模型正文或 private reasoning。
- 普通 CI 不调用真实 Provider；没有用户密钥时只验证接线和 fail-fast，不能宣称真实端点已验收。

## Acceptance Criteria

- [ ] `.env.example` 完整列出 production 模式、两种 Provider 的切换方式、模型、API Key、Base URL、正确的 Checkpointer URL 与加密密钥占位符。
- [ ] `make worker` 在 production 配置缺失时于领取任务前失败，且错误和日志不包含 API Key。
- [ ] `AI_PROVIDER=openai` 构造 `ChatOpenAI`；自定义 `AI_BASE_URL` 可接 OpenAI 兼容厂商。
- [ ] `AI_PROVIDER=anthropic` 构造 `ChatAnthropic`；空 Base URL 使用官方端点，自定义 Base URL 使用兼容端点。
- [ ] production Worker 安装三个真实 adapters，并在有效的同步 PostgreSQL Checkpointer context 内执行；退出后连接被关闭。
- [ ] Checkpointer 数据库未 setup、与业务数据库相同或加密密钥非法时启动失败，不领取任务、不回退 Fake。
- [ ] Provider/模型/端点变化会改变 AI Profile 兼容指纹，旧 accepted Checkpoint 继续保持 fail-closed。
- [ ] `AI_RUNTIME_MODE=fake` 仍可显式运行确定性本地 Worker，现有自动化测试不访问外部模型。
- [ ] `make ai-smoke` 可在用户提供真实配置后验证 tool calling/结构化输出，并输出不含业务正文和凭证的结果标记。
- [ ] `git diff --check`、`make test` 与 `make build` 通过；真实 Provider smoke 结果单独标记为已执行或待用户凭证验证。

## Out of Scope

- 为每个模型厂商编写专用 SDK adapter，或保证第三方端点的非标准 `reasoning_content` 字段可往返。
- 支持 Bedrock、Vertex AI、Azure 旧版专用协议或运行时热切换 Provider。
- 把 Checkpointer 当成业务数据库、任务队列或跨 thread Store/Memory。
- 自动创建数据库、自动执行 Checkpointer schema setup、部署 Docker/服务器或管理真实密钥。
- 修改前端、HTTP API 或业务状态机。

## Risks and Deferred Items

- “OpenAI 兼容”只代表协议入口兼容；本项目还依赖稳定 tool calling、ToolStrategy 和 Deep Agents 工具循环，必须用目标模型执行 smoke 后才能认定可用。
- `ChatOpenAI` 不保留第三方非标准 reasoning 字段；当前产品不展示或依赖 private reasoning，因此本任务不增加专用 reasoning adapter。
- 本地无法在没有用户真实 Key 的情况下证明某个端点可用；实现完成时必须把代码门禁与真实 Provider 验收状态分开报告。
