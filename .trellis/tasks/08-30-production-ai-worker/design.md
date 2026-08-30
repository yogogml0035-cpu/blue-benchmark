# 生产 AI Worker 接线设计

## Change Boundary

当前缺口是运行时组装，而不是业务共创逻辑：真实 adapters、模型构造和 PostgreSQL Checkpointer 都已有部分能力，但常驻入口没有把它们放进同一生命周期。本任务只修改后端运行时配置、模型/Checkpointer 工厂、Worker 入口、依赖、启动文档和对应测试；不改 Feature Service、Repository、HTTP DTO、前端或数据库迁移。

## Runtime Topology

```text
.env
  ├─ AI_RUNTIME_MODE=production
  ├─ AI_PROVIDER=openai | anthropic
  ├─ AI_MODEL / AI_API_KEY / AI_BASE_URL
  └─ CHECKPOINT_DATABASE_URL / LANGGRAPH_AES_KEY
            │
            ▼
worker module entry
  ├─ validate production settings (fail before claim)
  ├─ build one chat model
  ├─ open sync PostgresSaver context
  ├─ set_adapters(production_adapters(model, saver))
  └─ OperationWorker.run_once / run_forever
            │
            ├─ batch_analysis      → DeepAgentsEvidenceAnalyzer
            ├─ cocreation_*        → DeepAgentsStandardCoCreator + saver
            └─ coverage_review     → DeepAgentsCoverageReviewer
```

`OperationJob`、业务状态、accepted checkpoint pointer 和 projection CAS 继续由现有 Feature/Repository 拥有；Checkpointer 只保存 LangGraph thread execution state。

## Configuration Contract

`Settings` 提供以下字段并做无副作用的归一化；生产模型工厂的
`runtime_model_identity` 再执行 Provider、模型、凭证和 Base URL 的
fail-closed 校验。这样非法 URL 不会在 Pydantic 导入 traceback 中回显
可能误粘贴的凭证：

| Variable | Contract |
|---|---|
| `AI_RUNTIME_MODE` | `production` 或显式 `fake`；正常示例为 `production` |
| `AI_PROVIDER` | `openai` 或 `anthropic`，不自动推断 |
| `AI_MODEL` | Provider 接受的模型/部署名，非空 |
| `AI_API_KEY` | 统一密钥，作为 secret 读取并显式传给模型客户端 |
| `AI_BASE_URL` | 可选；空值使用官方端点，非空必须是 HTTP(S) URL |
| `CHECKPOINT_DATABASE_URL` | psycopg 可连接的独立 PostgreSQL 数据库 URL |
| `LANGGRAPH_AES_KEY` | 16/24/32 字节，加密 Checkpoint payload |

模型工厂返回 chat model 和不含密钥的 runtime identity。OpenAI 兼容厂商统一走 `ChatOpenAI`；Anthropic 协议统一走 `ChatAnthropic`。两者都保持 `streaming=False`，不设置 `temperature`。

AI Profile version 由现有 harness/schema 基线加 `provider + model + normalized base_url` 的短哈希组成。哈希不包含 API Key；模型接线变化会让旧 CoCreationSession 触发现有 `CheckpointIncompatible` 路径。

## Model Ownership

新增 `backend/app/lib/ai_runtime/model.py` 作为唯一模型配置验证和构造入口，避免 Settings、adapter 和 Worker 分别推断 Provider。

`_DeepAgentBase` 改为接收已构造模型和明确的 model registration key；三个 production adapters 共用同一不可变模型客户端。Fake adapters 不经过该工厂。

## Checkpointer Lifecycle

在 `backend/app/lib/ai_runtime/checkpoint.py` 增加同步 context manager：

1. 复用现有数据库分离和 AES key 校验；
2. 使用 psycopg `Connection.connect(..., autocommit=True, prepare_threshold=0, row_factory=dict_row)`；
3. 构造带 `EncryptedSerializer` 的同步 `PostgresSaver`；
4. 查询 Checkpointer 必需表完成 readiness 检查，但不调用 `setup()`；
5. yield saver，并由 context manager 关闭连接。

现有 `make checkpoint-setup` 继续是显式 schema 初始化入口，可调整为复用同一套 URL/key 校验，但不得在 Worker 启动时自动建表。

## Worker Assembly

- 保留 `default_worker()` 作为现有确定性测试/显式 Fake 业务处理器，避免普通测试访问网络。
- 增加 production runtime context/worker factory：先完成模型与 Checkpointer 初始化，再调用 `set_adapters(production_adapters(...))`，最后构造 handler registry。
- module entry 根据 `AI_RUNTIME_MODE` 选择：默认 production；只有明确 `fake` 才进入 Fake。
- 所有初始化发生在 `run_once()` 之前，因此缺配置、连接失败或 schema 未就绪都不会 claim OperationJob。
- 不在捕获异常时打印 Settings 或模型对象，避免 Secret 值进入日志。

## Provider Smoke

`backend/scripts/smoke_ai_provider.py` 复用生产模型工厂，以合成 Schema/提示执行一次本项目同类的 ToolStrategy 结构化输出。命令只打印：

```text
AI_PROVIDER_SMOKE=PASS provider=<provider> model=<model>
```

失败时输出稳定错误类型并以非零状态退出；不输出模型回复、密钥、Base URL query、Checkpoint 或 private reasoning。该命令是部署验收门，不进入默认 `make test`。

## Compatibility and Rollback

- 旧 `.env` 没有真实模型字段时，Worker 会显式失败；这是有意的 fail-closed 行为，不提供隐式 Anthropic/Fake 兼容分支。
- 现有测试直接调用 `default_worker()` 的行为保持不变。
- 若 OpenAI 兼容 Provider 不支持工具调用或 ToolStrategy，smoke/真实任务失败；不降级自由文本 JSON。
- 回滚时可撤销模型依赖、工厂和 Worker 入口改动；业务表、迁移和已存在 Checkpoint 数据不变。
