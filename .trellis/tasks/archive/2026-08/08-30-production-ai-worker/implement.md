# 生产 AI Worker 接线实施计划

## Ordered Checklist

1. 在 `backend/app/lib/settings.py` 建立显式 runtime/provider/model/secret/base URL 配置合同，并让 AI Profile identity 对 Provider、模型和端点变化敏感。
2. 新增 `backend/app/lib/ai_runtime/model.py`，集中校验 production 配置并构造 `ChatOpenAI` 或 `ChatAnthropic`；将 `langchain-openai` 加入 `backend/pyproject.toml` 并同步 `backend/uv.lock`。
3. 调整 `backend/app/lib/ai_runtime/adapters.py`，让 production adapters 接收同一已构造模型和注册键，删除仅凭 Base URL 选择 Anthropic 的分支；Fake adapters 保持确定性。
4. 在 `backend/app/lib/ai_runtime/checkpoint.py` 增加加密同步 `PostgresSaver` context 和 schema readiness 检查，保持 setup 为显式部署步骤；让 `backend/scripts/setup_checkpointer.py` 以不泄露连接细节的方式报告失败。
5. 调整 `backend/app/lib/operations/worker.py` 的 module entry：production 初始化全部成功后才运行 Worker；显式 fake 模式复用现有 Fake runtime；`--once` 与常驻模式共用接线。
6. 新增 `backend/scripts/smoke_ai_provider.py` 与 `make ai-smoke`，只用合成数据验证真实 Provider 的结构化 tool calling，并控制输出边界。
7. 更新 `.env.example`、`README.md` 和必要的启动说明，给出 OpenAI 兼容与 Anthropic 两套可复制配置、成功标记和失败检查。
8. 补充 runtime configuration、model factory、worker wiring 和 Checkpointer 单元测试；确认普通测试不会调用网络或真实 PostgreSQL，并更新后端 code-spec 的生产运行时合同。

## Validation

```bash
git diff --check
cd backend && uv run pytest -q
make test
make build
```

有用户提供的真实非生产密钥时，再分别对实际选择的 Provider 执行：

```bash
make checkpoint-setup
make ai-smoke
make worker
```

验收需区分：代码/配置门禁通过、PostgreSQL schema 就绪、Provider smoke 通过、真实 OperationJob 完成、共创 interrupt/resume 经进程重启恢复。没有凭证时后四项不得标记为已验证。

## Risky Files and Rollback Points

- `backend/app/lib/settings.py`：环境变量改名会让旧 `.env` fail-closed；先用配置单元测试锁定错误信息。
- `backend/app/lib/ai_runtime/profile.py`：版本指纹影响旧 Checkpoint 兼容；必须验证同配置稳定、Provider/模型/端点变化不同。
- `backend/app/lib/ai_runtime/adapters.py`：模型对象注入不能改变 ToolStrategy、安全 middleware、permissions 或业务投影边界。
- `backend/app/lib/ai_runtime/checkpoint.py`：同步 saver 必须保持 AES serializer 和显式 setup，不得混用业务数据库。
- `backend/app/lib/operations/worker.py`：所有生产初始化必须发生在 claim 前；Fake 测试路径不能被全局 adapters 污染。

任一步失败，优先回滚该职责的独立提交，不修改业务数据、强删 Checkpoint 或降级到自由文本/Fake 继续生产运行。

## Pre-Start Gate

- PRD、design 和本计划已经过用户确认。
- 适用 backend specs 与 Deep Agents/LangGraph Provider/Checkpointer 资料已读取。
- 任务分支为 `codex/production-ai-worker`，base branch 为 `main`，独立 worktree 不包含原规划工作区的未提交改动。
- 实施批准后才运行 `task.py start`；规划批准不提前领取 OperationJob、不调用真实 Provider。
