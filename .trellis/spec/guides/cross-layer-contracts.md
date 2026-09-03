# 跨层合同检查

## 当前数据流

```text
调用方（管理员会话 / 场景凭证 / 未来的上传 Skill 与前端）
  -> FastAPI Router
  -> Feature Service
  -> SQLAlchemy Repository / 业务数据库
  -> Pydantic Response / AppError
```

仓库是纯后端工程。管理员路由走 Session Cookie；外部批量收题走场景凭证 Bearer；评分维度生成由单消费者 Worker 异步执行。没有前端、浏览器路径或 TypeScript 生成类型。OpenAPI 是唯一对外机器合同。

## 合同事实源

- 后端运行时字段、枚举和校验：`backend/app/features/*/schemas.py`；
- 状态转换、授权和幂等：对应 Feature `service.py`；
- 机器可读 HTTP 合同：FastAPI 导出的 `backend/openapi.json`；
- 当前可运行边界：`README.md`、`Makefile`、Alembic migrations 和 `backend/app/lib/database/session.py`。

## API 合同变更清单

修改字段、枚举、错误或接口时按顺序检查：

1. 后端 Schema、Router `response_model` / `responses` 和 Service 是否一致；
2. 后端 API 测试是否覆盖成功、失败、授权和重试；
3. 运行 `make openapi`，只接受生成器产生的 `openapi.json` 变更；
4. 运行 `make contract-check` 确认已提交合同与当前 FastAPI 一致；
5. `make test` 通过；涉及迁移或启动门控时补充 `make db-migrate` / `make db-check`；
6. 如运行方式改变，同步 README 的使用说明；
7. 有意删除旧语义（破坏性收紧、入口收缩）时，全仓库 grep 旧词：`main.py` 的 FastAPI `description`、`pyproject.toml` description、包/模块 docstring、`openapi.json`、README 与 `skills/` 下的 SKILL.md / reference；只保留必要的禁止性描述，不留兼容性旧词。历史迁移文件不改写。

## Skill 文档编辑规则

`skills/` 下的 SKILL.md 与 reference 是双重文本：人类可读的指引可以改写或翻译，但机器标识符必须与脚本行为、后端合同逐字一致：

- 保留原样：字段名、错误码、脚本输出前缀（`config-error`、`invalid`、`upload-failed` 等）、HTTP 路径、JSON/命令示例、长度限制数值、环境变量名；
- 脚本输出文案由 `skills/ai-eval-push/tests/` 的隔离测试固定；要改输出文案（含中文化）必须同步改脚本与测试，并单独开任务，不在文档任务里顺手改；
- 翻译或改写后用 token 对比核对（如 `grep -oE '`[^`]+`'` 新旧版本取集合差异），确认机器标识符零漂移。

## 授权与数据泄露检查

跨主体功能必须同时验证：

- 管理员路由先有有效 Session；外部收题只接受场景凭证，且场景归属只来自凭证；
- 场景凭证不能读取、修改、删除或发布题目，只能查询连接状态与批量上传；
- 响应不包含密码哈希、Session Token、明文凭证、`token_hash`、宿主机路径或材料原文之外的内部字段；
- 题目材料、标准答案、Bad case、老师反馈与评分维度不进入任何对外泄漏面；
- 客户端扩展名/禁用等只是体验层，不替代后端校验；材料隐私兜底只在后端完成。

## 状态机检查

题目状态变化必须由后端 Service/Worker 完成。新增状态或动作时检查：

- 允许来源状态、目标状态和不允许组合的 409 机器码；
- 重复请求、陈旧 `content_revision` 和命令幂等/冲突规则；
- `last_error` 与 `next_action` 是否和当前状态一致；
- 已发布题目被编辑后回到待处理，不保留历史版本；
- 发布只标记当前题目与当前维度，不创建快照或派生草稿。

## 证据等级

- `pytest` / OpenAPI 漂移检查通过：自动化门通过；
- `accept_real_ai_rubric` 真实 Provider 端到端通过：真实 AI 验收；
- 文档或 Mock 写明能力：只代表设计或说明，不能升级为运行证据。

## 真实运行与命令身份检查

- 命令 ID 的数据库唯一范围必须按实现核对；`command_id + payload_hash` 决定幂等重放与冲突，跨场景的命令互不影响。
- `/healthz` 的 `ai` 只报告 `AI_RUNTIME_MODE`，不代表 Provider 或 Worker readiness；README 必须把这几项分开描述。
- 评分维度生成的结构化输出必须经过两字段合同与可执行性/隐私校验后才能提交；模型原文不进入响应或日志。
- 真实 E2E 只输出阶段/计数/错误码；禁止把 `EvalData`、凭证、正文或 raw model output 写入 Git。
