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

合同定义见 `app/lib/schemas.py::ErrorResponse`，转换入口见 `app/lib/errors.py::error_response`。`code` 用于前端分流，`message` 用于用户提示，`details` 只放必要、可公开的结构化信息，例如上传大小限制。

## 在哪里产生错误

- Pydantic / FastAPI 负责字段类型、长度、路径和表单边界；`validation_error_handler` 将其统一成 `422 VALIDATION_ERROR`，并在 `details.fields` 返回字段位置和消息。
- Service 负责业务冲突、授权、状态转换和组合校验，抛出明确状态码与机器码。参考 `workspaces/service.py::assert_owner`、`case_builder/service.py::generate_draft`、`_validate_confirmation`。
- Repository 当前只做内存读写，不负责把“未找到”映射成 HTTP。
- Router 在装饰器 `responses` 中声明实际可能返回的 `ErrorResponse`，使 OpenAPI 能生成合同；不要在 Router 捕获后重新包装同一种错误。

## 业务失败与系统失败

解析失败和 Stub AI 失败是 Case 资源的可恢复业务状态，通过 `CaseDetail.case.state` 与 `builder.last_error` 返回，不伪装成 500：

- 解析失败：`stage=parse`、`retryable=false`；
- AI 失败：`stage=ai`、`retryable=true`。

只有无法归类的异常才进入 `app/main.py::unexpected_error_handler`，对外固定返回经过清洗的 `500 INTERNAL_ERROR`。不得在响应中包含堆栈、内部 Record、Cookie、密码哈希、绝对路径或未来模型原始错误。

## 状态码语义

- `401`：没有有效 Session；
- `403`：已登录但资源不属于当前用户，或非安全请求的 Origin 不允许；
- `404`：当前授权范围内资源不存在；
- `409`：当前业务状态不允许动作、问题/草稿陈旧或重复提交冲突；
- `413` / `415`：上传大小或类型被入口拒绝；
- `422`：字段或组合内容无效；
- `500`：未预期错误，且响应必须清洗。

M0 共创新增的业务码包括 `FILE_ROLES_NOT_CONFIRMED`、`INVALID_TASK_GROUPING`、`TASK_NOT_CONFIRMED`、`CONTRACT_NOT_CONFIRMED`、`STALE_COCREATION`、`COMMAND_ID_REUSED`、`RETRY_NOT_AVAILABLE`；它们仍遵守 `409`（状态/revision/幂等冲突）或 `422`（输入/证据结构无效）的语义。

后台 Agent 错误不把 provider 原始消息返回给浏览器：结构化输出无效、工具越权、证据 locator 越界或 Checkpoint 不兼容只进入 OperationJob 的清洗错误和业务 `failed`/`projection_pending`/`continuity_reset` 状态。`CoCreationSessionView` 不包含 `thread_id`、`checkpoint_id`、interrupt、raw message 或凭证。

新增错误码时同步检查后端 Router `responses`、`backend/openapi.json`、前端 `ApiError` / `toPageFault` 以及对应状态测试。

## 当前没有日志规范

仓库未配置日志库，也没有结构化日志实现。不要把模板中的 log level、字段或追踪 ID 当作现行规则。未来引入日志时必须另立任务，先确定敏感数据边界和测试，再新增对应规范。
