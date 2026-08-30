# 后端开发规范

适用于 `backend/` 的 FastAPI 业务数据库服务。写代码前先确认任务触及哪一类边界，再读取对应规范。

## 规范索引

| 规范 | 何时读取 |
|---|---|
| [后端结构与依赖边界](./structure-and-boundaries.md) | 新增或移动 Feature、Router、Service、Repository、Schema、脚本 |
| [持久化状态、数据与合同](./stub-state-and-contracts.md) | 修改业务数据、认证归属、上传、Case 状态机或确认流程 |
| [错误与 API 响应](./errors-and-api-responses.md) | 新增错误分支、状态码、异常处理或前后端错误合同 |
| [后端质量与测试](./quality-and-tests.md) | 编写或审查后端代码、补充 API 测试、执行质量门 |

## 开发前检查

- [ ] 已从源码、迁移、测试和 `README.md` 判断当前实现，没有把 Checkpointer、真实 AI 等未来文档当成现状。
- [ ] 已确定修改所属 Feature，跨 Feature 依赖通过对方 Service。
- [ ] 涉及 API 字段、状态或错误时，已列出 OpenAPI、前端生成类型和测试的同步点。
- [ ] 涉及资源读取或写入时，已检查登录、Workspace 归属和 Case 归属顺序。

## 质量检查

- [ ] Router、Service、Repository、Schema 职责没有混写。
- [ ] 业务数据库持久化与测试数据库清理边界仍然真实。
- [ ] 状态转换、失败和重试有合同级测试，且保持幂等。
- [ ] 对外响应不包含内部 Record、密码哈希、Session Token、原始文本或 `thread_id`。
- [ ] 运行 `cd backend && uv run pytest -q`；跨层变更同时运行 `make test`。
