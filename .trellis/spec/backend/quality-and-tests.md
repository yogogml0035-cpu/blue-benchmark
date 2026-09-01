# 后端质量与测试

## 当前质量门

后端依赖由 `backend/pyproject.toml` 和 `backend/uv.lock` 管理，使用 uv；不要再增加 `requirements.txt`、Poetry 或第二份依赖入口。当前仓库没有 Ruff、Black、mypy 或覆盖率门禁，不能把这些工具写成“已经强制”。

可靠的现行验证命令：

```bash
cd backend && uv run pytest -q
make test
```

`make test` 还会运行前端 TypeScript 检查。只改后端合同后仍应执行跨层 OpenAPI 检查，见 `../guides/cross-layer-contracts.md`。

## 测试模式

`backend/tests/test_api.py` 和 `backend/tests/test_persistence_ingestion.py` 使用 FastAPI `TestClient` 做 HTTP 合同级测试，而不是绕过 Router 直接调用 Service：

- `reset_repositories` / `reset_database` 是 `autouse` fixture，每个测试前清空业务测试数据库；
- `client` fixture 创建同一 FastAPI 应用的客户端；
- `register`、`create_workspace`、`upload_case` 是闭环准备助手；
- 第二个 `TestClient` 表示另一个独立 Cookie 会话，用于越权验证。

当前覆盖基线：

1. 健康检查报告 `business database`，OpenAPI 含关键 Case 与 UploadBatch 合同；
2. 默认上传 -> 提问 -> 草稿 -> 确认闭环，以及确认幂等；
3. `parse_failed`、一次性 `ai_failed` 与重试；
4. Workspace 和 Case 的跨账号 `403`；
5. 数据库新进程读取、Alembic migration/schema readiness、服务端存储键和 ready marker；
6. 多文件/ZIP 安全边界、批次 `202`、纯读投影、command 幂等、用途 revision 冲突和 OperationJob lease/CAS/Attempt。
7. M0 TaskPackage 分组、受限 AI runtime、EvidenceRef canonical 回查、共创 stable thread、accepted Checkpoint CAS、projection_pending 重投影和跨层真实/合成验收。

修改这些合同必须扩展相同层级的 API 测试。新增错误分支至少断言 HTTP 状态、机器码或业务状态，并确认失败没有推进不允许的状态。

## 代码约定

- 使用现代类型标注（`str | None`、`dict[str, T]`、`list[T]`），保持 Pydantic Schema 和 Record 字段明确。
- 时间统一使用 `datetime.now(timezone.utc)`，不要生成无时区时间。
- 入口字符串按现有 Schema / Service 显式 `strip()`；不要在多个层重复各自定义不同的归一规则。
- ID 由服务端 `uuid4()` 生成；客户端输入不得成为内部 ID 或路径。
- 业务转换函数返回 Pydantic 响应模型，不返回随意拼接的字典。
- 密码比较使用恒定时间比较；不得弱化现有哈希或在测试输出密码哈希。

## Review 清单

- [ ] 代码仍遵守 Router -> Service -> Repository 和跨 Feature Service 边界。
- [ ] 业务数据库与未来 Checkpointer 执行状态没有混写。
- [ ] 新字段/状态/错误已同步 Schema、OpenAPI、前端生成类型和相关测试。
- [ ] 授权顺序和跨账号隔离没有回退。
- [ ] 重试路径保持幂等，失败不会产生半完成快照。
- [ ] 文件先 staging，再发布 ready marker；数据库失败清理已发布和 staged 对象。
- [ ] 响应没有暴露内部状态或敏感信息。
- [ ] 新增 Agent 只通过 `ReadOnlyEvidenceBackend` 读取虚拟 scope；工具 allowlist、权限 deny、HITL 单问题和 `invalid_tool_calls` 负例均有测试。
- [ ] 共创答案先保存业务 Turn，再由 OperationJob resume；重复命令不重复模型调用，Checkpoint latest 不得替代 accepted pointer。
- [ ] `make openapi` 只生成后端 OpenAPI 与前端类型，CI/显式 Fake 与常驻生产 Worker 都不打印业务正文、Checkpoint、凭证或 private reasoning。
- [ ] `make contract-check` 能在不改写生成文件的情况下发现后端 OpenAPI 或前端生成类型漂移；显式真实样本 runner 使用临时数据库/存储并只输出阶段标记。
- [ ] 版本 API/download 读取前校验 Manifest 身份、三分区 hash、ready marker 和 ZIP 条目内容；历史派生不能绕过同一完整性检查。
- [ ] 并发同命令/同草稿写入有 row lock 或唯一约束兜底，错误 payload 返回 409，不以 500 暴露竞态。
- [ ] OperationJob 的相同 target/revision/command 若跨 `kind` 必须显式冲突，不能返回另一种 operation；批次分析提交同时校验 operation attempt CAS 和批次仍处于分析态。
- [ ] batch analyzer 的 `evidence_refs` 既要属于整批 scope，也要属于各自 group 的 `evidence_file_ids`；迟到或跨组结果不能替换已发布提案。
- [ ] `cd backend && uv run pytest -q` 通过；跨层变更还通过 `make test`。

## 真实 AI / Checkpointer 回归门

- [ ] `make ai-smoke` 只证明当前 Provider 的一次结构化调用；不能外推文件工具、HITL 或业务 E2E。
- [ ] 真实 Worker 必须在同一隔离 PostgreSQL 业务库/Checkpointer 库上运行；先迁移业务 schema，再显式 `make checkpoint-setup`，失败不 claim。
- [ ] 真实模型请求有有限 timeout，长处理期间能续租，重启/lease reclaim 不产生第二个业务结果。
- [ ] `standard_cocreator` 的 `question_id/question -> id/text`、`respond.message`、`context=context` 和 accepted Checkpoint 指针有生产 adapter 回归；completion fallback 按当前 kind 使用单一 wire schema，再进入严格业务 Schema。
- [ ] Checkpoint serializer 显式 allowlist 应用类型，并在 `LANGGRAPH_STRICT_MSGPACK=true` 下执行 read/delete；删除 completed thread 后业务资产仍可读。
- [ ] 新增题级 Agent 的 Pydantic 类型、嵌套资料角色枚举和证据 locator 必须加入 Checkpoint serializer allowlist；仅默认宽松模式无警告不算通过，必须用 `LANGGRAPH_STRICT_MSGPACK=true` 启动并回读。
- [ ] authoring projection 写入失败时只允许重试已保存的内部 projection payload；`authoring_reproject` 不得重新调用 analyzer/question Agent，缺少 payload 时必须显式失败。
- [ ] rubric 生成的结构化输出和中文/泄漏校验最多做一次受限修复；`rubric_reproject` 只读取同一题目修订、同一业务 revision 的已保存 projection，不能因旧 job 的 terminal 状态遮蔽当前快照。
- [ ] 新 authored question revision 加入 Working Set 时必须校验发布内容 hash、资料元数据/ready marker 和当前合同；含 authored member 的 mixed package 使用 v2，v1 builder/reader 不得改变。
- [ ] 真实 runner 必须显式传 `--samples-dir`，每轮命令使用全局唯一 nonce，只输出阶段/计数/错误类型；禁止把 `EvalData`、凭证、正文或 raw model output 写入 Git。
- [ ] 真实 runner 在共享隔离业务库中核验本轮 operation 的私有 Worker 运行标记为 `production`；API health 或 `AI_RUNTIME_MODE` 不能替代实际 Worker 证明，标记不得进入业务 API。
- [ ] pnpm v11 的 `allowBuilds` 必须在 `frontend/pnpm-workspace.yaml` 明确列出需要执行的依赖脚本；`make test` 与 `make build` 都要在该配置下通过。
- [ ] 前端上传 command 在同一表单重试时稳定；静默轮询遇到失权/资源消失要清空旧快照，旧路由的迟到响应不能覆盖新资源；`projection_pending` 必须有重投影入口。

### Migration gotcha: PostgreSQL dependencies

- PostgreSQL migrations that change a table with inbound foreign keys must use
  direct `ADD COLUMN`/`ALTER COLUMN` or explicitly drop dependent foreign keys
  first. `batch_alter_table(recreate="always")` can try to drop a primary or
  unique index while another FK still depends on it; SQLite passing does not
  prove the PostgreSQL path. Always run `make db-migrate` and `make db-check`
  against the configured PostgreSQL before claiming the schema is ready.
