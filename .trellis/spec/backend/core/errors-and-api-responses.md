# 错误与 API 响应

## 统一错误形状

可预期的业务失败抛出 `app.lib.errors.AppError`，由应用级处理器转换成统一 JSON：

```json
{
  "error": {
    "code": "MACHINE_READABLE_CODE",
    "message": "可直接展示的中文说明",
    "details": null
  }
}
```

合同定义见 `app/lib/schemas.py::ErrorResponse`，转换入口见 `app/lib/errors.py::error_response`。`code` 用于调用方分流，`message` 用于提示，`details` 只放必要、可公开的结构化信息，例如批量收题的逐题问题清单。

## 在哪里产生错误

- Pydantic / FastAPI 负责字段类型、长度、路径和请求体边界；`validation_error_handler` 将其统一成 `422 VALIDATION_ERROR`，并在 `details.fields` 返回字段位置和消息。
- Service 负责业务冲突、授权、状态转换和组合校验，抛出明确状态码与机器码。参考 `question_library/service.py::publish`、`scenes/service.py::revoke_credential`。
- Repository 负责业务数据库 Row/Record 读写，不负责把“未找到”映射成 HTTP；测试通过独立 SQLite 文件隔离数据。
- Router 在装饰器 `responses` 中声明实际可能返回的 `ErrorResponse`，使 OpenAPI 能生成合同；不要在 Router 捕获后重新包装同一种错误。

## 业务失败与系统失败

评分维度生成失败是题目的可恢复业务状态，通过 `QuestionDetailResponse.status` 与 `last_error` 返回，不伪装成 500：

- 生成失败：`status=generation_failed`、`last_error.code` 为 `AI_CALL_FAILED`/`AI_OUTPUT_INVALID` 等，可重试。

只有无法归类的异常才进入 `app/main.py::unexpected_error_handler`，对外固定返回经过清洗的 `500 INTERNAL_ERROR`。不得在响应中包含堆栈、内部 Record、Cookie、密码哈希、明文凭证、绝对路径或模型原始错误。

## 状态码语义

- `401`：没有有效管理员会话，或场景凭证缺失/无效/已撤销；
- `403`：已登录但越权；
- `404`：当前授权范围内资源不存在；
- `409`：当前业务状态不允许动作、内容版本陈旧或命令/凭证冲突；
- `422`：字段或组合内容无效（含隐私兜底拒绝、空泛评分标准）；
- `500`：未预期错误，且响应必须清洗。

M0 业务码包括 `COMMAND_ID_REUSED`、`COMMAND_IN_PROGRESS`、`CASE_ALREADY_EXISTS`、`BATCH_CASE_INVALID`、`PRIVATE_CONTENT_REJECTED`、`CRITERION_TOO_VAGUE`、`STALE_REVISION`、`QUESTION_DELETING`、`RUBRIC_GENERATING`、`GENERATION_FAILED`、`CRITERIA_MISSING`、`CRITERIA_NOT_CONFIRMED`、`ALREADY_PUBLISHED`、`REVIEW_REOPEN_NOT_AVAILABLE`、`PUBLISHED_REOPEN_REQUIRED`、`DELETE_CONFIRMATION_MISMATCH`、`SCENE_NOT_EMPTY`、`RETRY_NOT_AVAILABLE`、`SCENE_NAME_EXISTS`、`CREDENTIAL_ALREADY_REVOKED`；它们遵守 `409`（状态/版本/幂等冲突）或 `422`（输入/材料/标准/确认无效）的语义。

评分维度生成的后台错误不把 provider 原始消息返回给调用方：模型调用失败、结构化输出无效或提交被 fencing 拒绝，只进入 `OperationJob` 的清洗错误和题目 `generation_failed`/`superseded` 状态。

新增错误码时同步检查后端 Router `responses`、`backend/openapi.json` 以及对应状态测试。

## AI 运行诊断（唯一的结构化日志面）

`ai_runtime/diagnostics.py` 是仓库唯一的结构化日志实现，只服务 AI 运行失败排查，不是通用日志框架：

- 单一白名单序列化（`RECORD_FIELDS`）：时间、event/stage、异常分类、HTTP status、服务端 param、request_id、retryable、合同身份（fingerprint/provider/model/endpoint_fingerprint/协议/思考强度/输出策略/策略版本）、operation/question/attempt/thread 关联 ID。
- 出口是标准 `logging`（`ai_runtime.diagnostics` logger）：stderr + `storage/runtime/ai-diagnostics.jsonl`（5 MiB×1 轮转，gitignored；路径按模块位置推导，容器为 `/app/storage/...`，不用 PROJECT_ROOT）。
- 分类取异常链最深 cause（业务包装不得掩盖 provider 分类）；`retryable` 采用 LangChain `ModelError` 标准语义。未知异常按类名（代码标识符）记录，否则 `unknown`；合同不可解析记 `unavailable`，不伪装默认身份。
- 永不记录：provider 原始消息、材料、headers、完整 URL、原始工具负载、私有推理、凭证、任意异常的 `str(exc)`。哨兵测试（T12）覆盖 last_error、公开事件与诊断文件三个出口。
- 诊断失败（文件不可写、logger 被迁移工具禁用）不得改变原始失败语义；logger 每次访问强制 re-enable。
- 其余仓库范围仍无日志规范；新增其它日志面必须另立任务并先定敏感数据边界。
