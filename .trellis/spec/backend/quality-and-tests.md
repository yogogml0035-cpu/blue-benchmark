# 后端质量与测试

## 当前质量门

后端依赖由 `backend/pyproject.toml` 和 `backend/uv.lock` 管理，使用 uv；不要再增加 `requirements.txt`、Poetry 或第二份依赖入口。当前仓库没有 Ruff、Black、mypy 或覆盖率门禁，不能把这些工具写成“已经强制”。

可靠的现行验证命令：

```bash
cd backend && uv run pytest -q
make test      # pytest + OpenAPI 漂移检查
make build     # 后端编译/导入验证
```

`make test` 与 `make contract-check` 只运行后端检查（仓库已无前端）。OpenAPI 合同变更见 `../guides/cross-layer-contracts.md`。

## 测试模式

`backend/tests/` 使用 FastAPI `TestClient` 做 HTTP 合同级测试，而不是绕过 Router 直接调用 Service：

- `conftest.py` 为每个 pytest 进程提供独立临时 SQLite；
- `tests/helpers.py` 提供 `register_admin`、`create_scene`、`issue_credential`、`upload_batch`、`make_case`、`run_worker_until_idle` 等闭环准备助手；
- 需要独立会话/凭证隔离验证时，使用第二个 `TestClient`。

当前覆盖基线：

1. 批量收题的原子性（全成全败）、命令幂等（同 payload 重放）、变更 payload 冲突、跨场景隔离；
2. 六类材料边界与隐私兜底（凭证/主机路径/Unicode 绕过）；
3. 评分维度生成（成功、失败、重试、模糊输出拒绝、同命令复活不污染队列）；
4. 状态机与发布门禁、`save-and-regenerate` 作废旧维度、`title` 改名不触发重新生成；
5. 两字段维度合同与逐项及格语义；
6. 迁移（旧 head 升级、fresh DB、downgrade）与 OpenAPI 合同；
7. 并发/安全加固回归（条件 UPDATE 单写者、单管理员原子性、已发布维度守卫、登出鉴权等）。

修改这些合同必须扩展相同层级的 API 测试。新增错误分支至少断言 HTTP 状态、机器码或业务状态，并确认失败没有推进不允许的状态。

## 代码约定

- 使用现代类型标注（`str | None`、`dict[str, T]`、`list[T]`），保持 Pydantic Schema 和 Record 字段明确。
- 时间统一使用 `datetime.now(timezone.utc)`，不要生成无时区时间。
- 入口字符串按现有 Schema / Service 显式 `strip()`；不要在多个层重复各自定义不同的归一规则。
- 内部 ID 由服务端 `uuid4()` 生成；客户端输入（`client_case_id`、`command_id`）只作为业务键，不得成为内部主键或路径。
- 业务转换函数返回 Pydantic 响应模型，不返回随意拼接的字典。
- 密码与凭证比较使用恒定时间/哈希比较；不得在测试或响应输出密码哈希或明文凭证。

## Review 清单

- [ ] 代码仍遵守 Router -> Service -> Repository 和跨 Feature Service 边界。
- [ ] 新字段/状态/错误已同步 Schema、OpenAPI 和相关测试。
- [ ] 管理员会话与场景凭证的授权顺序和隔离没有回退。
- [ ] 重试路径保持幂等，失败不会产生半批数据或孤立生成任务。
- [ ] 并发同命令/同题目写入有条件 UPDATE 或唯一约束兜底，错误返回 409/422，不以 500 暴露竞态。
- [ ] 评分维度提交原子（业务写入 + 任务终态同事务），旧任务被 fencing 判为 `superseded`，不覆盖新材料。
- [ ] 响应没有暴露明文凭证、`token_hash`、宿主机路径或材料原文之外的内部字段。
- [ ] 评分生成失败投影为 `generation_failed`，不留下永久 `generating`。
- [ ] `cd backend && uv run pytest -q` 通过；跨层变更还通过 `make test`。

## 真实 AI 回归门

- [ ] `make ai-smoke` 只证明当前 Provider 的一次结构化调用；不能外推业务 E2E。
- [ ] 真实 Worker 必须在隔离业务库上运行；先 `make db-migrate`，配置/连接失败在 claim 前退出。
- [ ] 真实模型请求有有限 timeout，长处理期间能续租，重启/lease reclaim 不产生第二个业务结果。
- [ ] 真实端到端用 `scripts/accept_real_ai_rubric.py`，只输出阶段/计数/错误码；禁止把 `EvalData`、凭证、正文或 raw model output 写入 Git。
- [ ] 真实验收必须核验生成由 `production` Worker 完成；API health 或 `AI_RUNTIME_MODE` 不能替代实际 Worker 证明。

### Migration gotcha: PostgreSQL dependencies

- PostgreSQL migrations that change a table with inbound foreign keys must use
  direct `ADD COLUMN`/`ALTER COLUMN` or explicitly drop dependent foreign keys
  first. `batch_alter_table(recreate="always")` can try to drop a primary or
  unique index while another FK still depends on it; SQLite passing does not
  prove the PostgreSQL path. Always run `make db-migrate` and `make db-check`
  against the configured PostgreSQL before claiming the schema is ready.
