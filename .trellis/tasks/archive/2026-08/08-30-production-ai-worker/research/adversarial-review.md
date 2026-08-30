# 对抗式审查记录

审查对象：`codex/production-ai-worker` 当前实现，日期 2026-08-30。

## Round 1 — 入口与配置偷换

- 反例：`make worker` 仍直接构造模块级 Fake；或只设置 API Key 就静默选错 Provider。
- 证据：module entry 现在只在 `AI_RUNTIME_MODE=fake`/`--fake` 进入 `default_worker()`；默认/production 进入 `production_worker()`，先构造模型与 Checkpointer 再 yield Worker。
- 修正：新增显式 `AI_PROVIDER`、`AI_MODEL`、`AI_API_KEY`、`AI_BASE_URL`；`production_adapters` 不接受空 Checkpointer，也不把未验证模型字符串交给 Deep Agents。
- 测试：Provider client 类型、OpenAI Chat Completions 强制关闭 Responses API、直接 adapter 走统一 factory、生产 adapters 必须有 Checkpointer。

## Round 2 — Secret/ambient env 与错误边界

- 反例：`OPENAI_BASE_URL`/`ANTHROPIC_BASE_URL` ambient env 覆盖后台配置；Base URL query/userinfo 带入密钥；CLI traceback 打印 key/DSN；示例 key 被当作真实凭证。
- 证据：模型工厂对官方端点显式传固定 URL；自定义 URL 只允许 HTTP(S) 且拒绝 userinfo/query/fragment；`SecretStr` 保护 AI key 和 AES key；`replace-with-*` 占位符被拒绝；Worker/setup/smoke 只输出稳定错误类型。
- 修正：Settings 只做归一化，运行时错误统一由可捕获的 `ModelConfigurationError`/`CheckpointError` 报告；setup 脚本移除异常链输出。
- 测试：空/非法/占位 key、无效 Provider/模型/URL、ambient URL 隔离、smoke 失败不包含异常详情或 key。

## Round 3 — Checkpointer claim 前置与重启

- 反例：数据库能连但 Checkpointer 未 setup，Worker 先 claim 后在 handler 中失败；异步 saver 被同步 `graph.invoke()` 使用；连接或加密 serializer 没有跨进程持久化。
- 证据：同步 `open_postgres_checkpointer` 使用 psycopg `autocommit=True`、`prepare_threshold=0`、`dict_row` 和 AES `EncryptedSerializer`；readiness 检查四张表及最新 migration version；所有初始化在 `run_once()` 前完成。
- 实测：本机 PostgreSQL 17 临时容器中执行 `checkpoint-setup`，进程 A 写入 LangGraph state，进程 B 重新打开连接读到 `{'value': 2}`；另一个未 setup 的数据库使 Worker 输出 `Checkpointer schema is not ready; run make checkpoint-setup`、退出码 2。临时容器已删除。
- 测试：schema 缺表/旧 migration、same database（含 `postgresql+psycopg` 与 `postgresql` 混用）、连接关闭、model/Checkpointer 失败时 `claim_next` 未调用。

## Round 4 — Profile compatibility 与全量质量门

- 反例：Provider/模型/端点切换后旧 accepted Checkpoint 被误认为兼容；OpenAI 模型悄悄切到 Responses API；只做后端单测却遗漏前端/合同漂移。
- 证据：`AIProfile.version` 包含不含密钥的 runtime fingerprint；模型工厂对 OpenAI 显式 `use_responses_api=False`；真实 provider smoke 使用与当前 Deep Agents `ToolStrategy` 相同的 CoverageReview 路径。
- 质量门：`uv run pytest -q` 通过（77 tests）；`make test` 通过（后端 77、前端 typecheck、OpenAPI contract-check）；`make build` 通过；`uv lock --check`、`git diff --check` 通过。
- 未验证项：当前环境没有用户真实 AI 凭证，因此 `make ai-smoke` 只验证无凭证时安全 FAIL；目标 Provider 的真实 tool-calling/结构化输出和真实 OperationJob 仍需用户在配置凭证后执行。
