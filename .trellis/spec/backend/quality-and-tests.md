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
- [ ] `make openapi` 只生成后端 OpenAPI 与前端类型，生产默认 Fake 不打印业务正文、Checkpoint、凭证或 private reasoning。
- [ ] `make contract-check` 能在不改写生成文件的情况下发现后端 OpenAPI 或前端生成类型漂移；显式真实样本 runner 使用临时数据库/存储并只输出阶段标记。
- [ ] 版本 API/download 读取前校验 Manifest 身份、三分区 hash、ready marker 和 ZIP 条目内容；历史派生不能绕过同一完整性检查。
- [ ] 并发同命令/同草稿写入有 row lock 或唯一约束兜底，错误 payload 返回 409，不以 500 暴露竞态。
- [ ] `cd backend && uv run pytest -q` 通过；跨层变更还通过 `make test`。
