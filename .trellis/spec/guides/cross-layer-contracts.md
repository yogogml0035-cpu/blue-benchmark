# 跨层合同检查

## 当前数据流

```text
用户输入
  -> Next.js Feature Component
  -> frontend/features/*/services
  -> frontend/lib/api/client
  -> same-origin /api/* Rewrite
  -> FastAPI Router
  -> Feature Service
  -> SQLAlchemy Repository / 业务数据库
  -> Pydantic Response / AppError
  -> 页面以服务端快照或 PageFault 渲染
```

当前链路已到业务数据库、服务端文件存储、统一 OperationJob、受限 Deep Agent adapter、共创业务投影和 evaluation-set 版本包；默认 CI 使用 Fake adapter，真实 provider 调用和生产 Checkpointer 仍需独立部署/Spike 证据。M2 被测 Agent、评测执行和报告仍是后续计划，不能把版本包冻结误写成执行验收。

## 合同事实源

- 后端运行时字段、枚举和校验：`backend/app/features/*/schemas.py`；
- 状态转换、授权和幂等：对应 Feature `service.py`；
- `evaluation_sets` 的历史内容事实源：版本记录指向的 ready Manifest/三分区/ZIP，不是可变业务表；
- 机器可读 HTTP 合同：FastAPI 导出的 `backend/openapi.json`；
- 前端 DTO：生成的 `frontend/src/lib/api/generated.ts`；
- 前端传输和错误：`api/client.ts`、`api/pageFault.ts`；
- 前端 Case 展示语义：`case-builder/lib/caseState.ts`；
- 当前可运行边界和人工验收：`README.md`、`Makefile`、Alembic migrations 和 `backend/app/lib/database/session.py`。

`docs/` 下的设计合同可以约束未来方向，但其中尚未出现在依赖清单、源码和测试里的能力必须标注为计划，不能覆盖当前源码事实。

## API 合同变更清单

修改字段、枚举、错误或接口时按顺序检查：

1. 后端 Schema、Router `response_model` / `responses` 和 Service 是否一致；
2. 后端 API 测试是否覆盖成功、失败、授权和重试；
3. 运行 `make openapi`，只接受生成器产生的 `openapi.json` / `generated.ts` 变更；
4. Feature Service 是否仍只消费生成 DTO；
5. 页面加载联合、`PageFault`、`STATE_META`、进度和预演 fixture 是否穷举新合同；
6. `make test` 通过；涉及路由或生产门控时 `make build` 通过；
7. 如用户路径改变，同步 README 的人工验收说明。

## 授权与数据泄露检查

跨层功能必须同时验证：

- 请求先有有效 Session，再检查 Workspace 所有者，再检查 Case 与 Workspace 关系；
- 403 页面不继续渲染旧缓存中的资源；
- 后台投影只读取已授权的业务记录；
- 响应不包含密码哈希、Session Token、内部 `thread_id`、`parsed_text` 或其他账号标识；
- `runtime` 只能包含老师确认可见的任务/Brief/输入，`judge` 与 `provenance` 不得进入被测 Agent 输入；下载前校验 Manifest、分区和 ZIP 内容 hash；
- 前端扩展名、禁用按钮和路由 ID 都只是体验层，不替代后端校验；文件存储键和 ZIP 安全校验只在后端完成。

## 状态机检查

Case 状态变化必须由后端 Service 完成，前端只显示返回快照。新增状态或动作时检查：

- 允许来源状态、目标状态和不允许组合的 409 机器码；
- 重复请求、陈旧问题和陈旧草稿的幂等/冲突规则；
- `last_error.stage` 与 `retryable` 是否和页面下一步一致；
- `confirmed` 是否仍只创建候选案例，不越级进入评测集；
- `EvaluationSetVersion` 只能从 active draft 原子创建，版本号连续、历史只读，freeze 失败不创建可见版本；
- 刷新后是否能仅凭 GET 返回恢复页面，不依赖本地记忆。

## 证据等级

- `pytest` / typecheck / build 通过：对应自动化门通过；
- 预演状态可渲染：开发 fixture 与类型可用；
- 浏览器闭环实际完成：真实前后端交互已验收；
- 文档或 Mock 写明能力：只代表设计或说明，不能升级为运行证据。

## 真实运行与命令身份检查

- Provider smoke、真实文件读取、HITL resume、业务 projection 和版本下载是不同证据等级；任何一个绿灯不能替代其他层。
- 运行时上下文必须通过 `graph.invoke(..., context=context)` 传入，才能让 middleware 的权限/预算 predicate 看到当前身份、scope 和 business revision；声明 `context_schema` 不等于已经传递。
- 工具 envelope 与业务 DTO 不能靠字段同名假设：`ask_teacher` 的 `question_id/question` 要映射为 `id/text`，`respond` 决策按当前 LangChain 版本使用 `message`；生成的 `CoCreationQuestion` 必须再做 canonical evidence 校验。
- 命令 ID 的数据库唯一范围必须按实现核对。若 answer command 为全局唯一，runner 和多 session 测试必须使用 nonce；跨 session 重用应返回 `COMMAND_ID_REUSED`，不能伪装成问题状态冲突。
- 公共 DTO 可能只暴露 `has_contract` / `has_judgment_package` 等业务布尔值，不能在 E2E 中读取不存在的内部 `contract_revision_id`；内部数据库核对和浏览器 DTO 核对要分别完成。
- `/healthz` 的 `ai` 只报告 `AI_RUNTIME_MODE`，不代表 Provider、Checkpointer 或 Worker readiness；README 必须把这几项分开描述。
- 真实 E2E 结束前要清理精确命名的临时容器/存储；删除 completed Checkpoint thread 后再次回查业务 TaskPackage、合同和版本，证明执行连续性与业务资产确实分离。
- 前端上传必须传入组件生命周期内稳定的 `command_id`，以覆盖成功响应丢失后的同表单重试；disposition Service 的返回类型必须与实际 `UploadBatchResponse` 合同一致。
- 轮询响应提交前要通过 workspace/batch/session generation guard；401/403/404 不能保留旧私有快照，`projection_pending` 要走明确的服务端 reproject/retry 动作。
