# Stub 状态、数据与合同

## 先确认当前实现边界

当前代码是可运行的内存 Stub，不是持久化或真实 AI 版本。规范以源码和 `README.md` 的现状说明为准；`docs/初始化项目开发规格.md`、`docs/architecture.md`、`docs/features/case-builder.md` 和 ADR 中的 PostgreSQL、LangGraph 等内容仍是未来设计，不能当作已经实现的开发模式。

| 已实现事实 | 尚未实现、需另立任务的计划 |
|---|---|
| `auth`、`workspaces`、`case_builder` Repository 使用进程内 `dict` | PostgreSQL、SQLAlchemy、Alembic、数据库事务 |
| Session Cookie 对应内存 Session 表 | 持久化 Session、生产认证体系 |
| TXT/Markdown 同步读取并只保留解析文本与附件元数据 | 原文件存储、更多格式解析、OCR |
| `_run_stub_generation` 和内容标记驱动固定分支 | 真实模型、LangChain、LangGraph Checkpoint |
| 确认后生成一个内存 `candidate_case` 快照 | 正式评测集、评测执行、版本历史 |
| 单请求同步执行 | Worker、任务队列、实时推送 |

后端重启会清空账号、Session、场景和案例。不要写出暗示“已持久化”“可跨重启恢复”的代码、测试说明或验收结论。

## 内存数据所有权

每个 Repository 只拥有自己的 Record 和集合：

- `auth/repository.py`：`UserRecord`、`users`、`sessions`；
- `workspaces/repository.py`：`WorkspaceRecord`、`workspaces`；
- `case_builder/repository.py`：`CaseRecord`、`cases`。

Record 是内部可变状态，Pydantic Schema 是外部合同。Service 必须显式投影，例如 `workspaces/service.py::to_workspace` 和 `case_builder/service.py::_detail`；不要直接序列化 Record 的全部字段。

测试通过各 Repository 的 `reset()` 隔离全局状态，参考 `backend/tests/test_api.py::reset_repositories`。新增 Repository 时必须提供同等的测试清理入口。

## Case Builder 状态机

对外状态唯一来源是 `case_builder/schemas.py::CaseState`。状态转换由 `case_builder/service.py` 集中执行：

```text
上传 -> ready_for_ai | parse_failed
ready_for_ai -> generating -> waiting_for_input | waiting_for_confirmation | ai_failed
waiting_for_input -> generating -> waiting_for_confirmation
ai_failed -> generating -> waiting_for_confirmation
waiting_for_confirmation -> confirmed
```

保持以下已实现合同：

- 空白或无法 UTF-8 解码的内容进入 `parse_failed`，不得进入 Stub 生成。
- `[stub:ai_failed]` 第一次生成进入可重试的 `ai_failed`；再次生成进入待确认。
- `[stub:waiting_for_confirmation]` 与 `[stub:success]` 直接进入待确认；普通输入先进入一次提问。
- `generating` 的重复生成只返回当前快照；不允许状态组合返回 `409 AppError`。
- 同一问题的相同答案重试返回当前快照，不同答案返回 `QUESTION_ALREADY_ANSWERED`。
- 确认必须校验当前 `draft_revision`、完整性和证据 `source_id`；相同确认重试返回同一候选快照。
- `confirmed` 只表示候选案例已确认，不表示已加入评测集或触发评测。

新增状态时要同时检查 Schema、Service 冲突映射、API 测试、OpenAPI、前端 `caseState.ts` 和预演 fixtures，不能只改枚举。

## 认证与归属顺序

业务 Router 用 `Depends(auth_service.require_current_user)` 先解析当前用户。访问 Case 时，Service 先调用 `workspace_service.assert_owner`，再检查 Case 是否属于 URL 中的 Workspace。保持 `401`（未登录）、`403`（已登录但越权）、`404`（授权范围内不存在）的语义，不要为了“防枚举”私自合并现有合同。

密码只以 PBKDF2 哈希存入内部 Record，响应模型永不包含密码或哈希。Session Cookie 由 `auth/service.py::_set_session` 统一设置为 `HttpOnly`、`SameSite=Lax`，`Secure` 取自 Settings。

## 上传边界

`case_builder/service.py::create_case` 是当前唯一上传入口：扩展名和声明类型都必须在白名单，读取上限为 `settings.upload_max_bytes + 1`，文本按 `utf-8-sig` 解码。文件名只作为附件展示元数据；当前实现没有写入磁盘。

不要把前端的扩展名检查当作安全边界，也不要在没有实现存储时编造磁盘路径或持久化证明。
