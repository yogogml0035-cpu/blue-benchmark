# 后端开发规范

适用于 `backend/` 的 FastAPI 业务数据库服务。仓库为后端 + 前端两层：后端是业务事实源，前端（`frontend/`，见 `../frontend/` 规范）只做呈现并复用后端 Session Cookie。写代码前先确认任务触及哪一类边界，再读取对应规范。

## 规范索引

| 规范 | 何时读取 |
|---|---|
| [后端结构与依赖边界](./structure-and-boundaries.md) | 新增或移动 Feature、Router、Service、Repository、Schema、脚本 |
| [持久化状态、数据与合同](./stub-state-and-contracts.md) | 修改业务数据、认证归属、批量收题、题目状态机或评分维度生成 |
| [错误与 API 响应](./errors-and-api-responses.md) | 新增错误分支、状态码、异常处理或 API 错误合同 |
| [后端质量与测试](./quality-and-tests.md) | 编写或审查后端代码、补充 API 测试、执行质量门 |

## 开发前检查

- [ ] 已从源码、迁移、测试和 `README.md` 判断当前实现，没有把已删除的旧链路（旧建题/共创/Working Set/版本包/人工评分）当成现状。
- [ ] 已确定修改所属 Feature（`question_library`、`scenes`、`auth`），跨 Feature 依赖通过对方 Service。
- [ ] 涉及 API 字段、状态或错误时，已列出 `backend/openapi.json`、`scripts/verify_openapi.py` 和测试的同步点。
- [ ] 涉及资源读取或写入时，已检查管理员会话、场景凭证最小权限与场景归属边界。
- [ ] 涉及 ai-eval-push 技能或其验收脚本时，已确认凭证走“脚本内占位符替换”绑定：仓库中的技能脚本永远保持占位符，只绑定部署副本或临时副本，绝不向仓库提交真实凭证、也不改回环境变量注入。
- [ ] 涉及材料或评分维度时，已确认六类材料边界、两字段维度合同与隐私兜底校验。

## 质量检查

- [ ] Router、Service、Repository、Schema 职责没有混写。
- [ ] 业务数据库持久化与测试数据库清理边界仍然真实。
- [ ] 状态转换、失败和重试有合同级测试，且保持幂等。
- [ ] 对外响应不包含内部 Record、密码哈希、Session Token、明文凭证或原始材料正文。
- [ ] 运行 `cd backend && uv run pytest -q`；跨层变更同时运行 `make test`。
