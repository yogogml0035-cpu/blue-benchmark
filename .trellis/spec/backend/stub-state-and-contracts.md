# 持久化状态、数据与合同

## 先确认当前实现边界

当前后端已经使用 SQLAlchemy 业务数据库和 Alembic 迁移；Case Builder 的 AI 仍是 Stub，真实 Deep Agent、Checkpointer 和评测集仍由后续子任务实现。规范以源码、测试和迁移为准；任务研究文档中尚未落地的能力不能当作当前事实。

| 已实现事实 | 尚未实现、需另立任务的计划 |
|---|---|
| `auth`、`workspaces`、`case_builder` Repository 使用业务数据库表 | 生产认证体系和多租户权限 |
| Session Cookie 只把 SHA-256 token hash 存入数据库 | 更完整的 Session 过期、撤销和轮换策略 |
| 旧 `/cases` 入口保留 TXT/Markdown Stub 闭环 | 旧入口向完整任务包迁移 |
| `/upload-batches` 接受多文件和 ZIP，原文件以服务端存储键保存 | 生产对象存储、OCR 和更多媒体解析 |
| `_run_stub_generation` 和内容标记驱动固定分支 | 真实模型、LangChain、LangGraph Checkpoint |
| 确认后生成数据库中的 `candidate_case` JSON 快照 | 正式评测集、评测执行、版本历史 |
| `OperationJob` 负责持久化排队、租约、重试和幂等，Fake Worker 可执行基础操作 | 真实 Deep Agent Worker、跨进程 Checkpointer |

数据库重启或 Python 进程重启不会清空业务记录；只有测试中的 `reset()` 会显式清空测试数据库。不要把业务数据库记录与后续 Checkpointer 执行状态混为同一事实源。

## 业务数据所有权

每个 Repository 只拥有自己的 Record 到数据库行的映射和读写函数：

- `auth/repository.py`：`UserRecord`、`users`、`sessions` 表；
- `workspaces/repository.py`：`WorkspaceRecord`、`workspaces` 表；
- `case_builder/repository.py`：`CaseRecord`、`cases` 表；
- `case_builder/ingestion_repository.py`：`UploadBatchRecord`、`EvidenceFileRecord`、文件用途确认表。

Record 是内部可变状态，Pydantic Schema 是外部合同。Service 必须显式投影，例如 `workspaces/service.py::to_workspace` 和 `case_builder/service.py::_detail`；不要直接序列化 Record 的全部字段。

测试通过各 Repository 的 `reset()` 清空业务测试数据库；`backend/tests/conftest.py` 为每个 pytest 进程提供独立 SQLite 文件，避免并行测试互相清空数据。新增 Repository 时必须纳入 `clear_business_data()` 的依赖逆序清理。

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

旧 `case_builder/service.py::create_case` 继续只接受 TXT/Markdown 并保存 Stub 案例；M0 完整资料入口是 `case_builder/ingestion_service.py::create_upload_batch`，由 `/api/workspaces/{workspace_id}/upload-batches` 提供。入口支持 `.md/.txt/.json/.jsonl/.zip`、多文件、ZIP 展开、服务端生成存储键、SHA-256、media type、解析状态和 canonical view 元数据。

安全解包必须先校验每个 ZIP 条目的 POSIX/Windows 路径，再跳过安全目录；拒绝绝对路径、`..`、空路径段、重复名称、符号链接、特殊文件、损坏压缩包、嵌套层级、文件数、单文件大小、展开总量和异常压缩比。原文件先写入 `staging/<batch>/<file>`，发布到 `evidence/<batch>/<file>` 时同时写 ready marker；数据库写入失败必须清理已发布和 staged 对象。

上传成功只创建 `UploadBatch`、`EvidenceFile`、默认未确认的 `FileDisposition` 和 `batch_analysis` `OperationJob`，返回 `202` 及 `UploadBatchResponse`。`GET /upload-batches/{batch_id}` 和 `GET /upload-batches/studio` 只读取业务投影，不创建任务、不续租、不推进状态。重复 `command_id` 在同一 workspace 返回原批次，不读取或覆盖第二份资料。

HTTP 只返回服务端生成的业务 ID、哈希和文件摘要，不返回宿主绝对路径、存储键、解析正文、凭证、token、thread 或 Checkpoint 字段。不要把前端的扩展名检查当作安全边界。

## Scenario: M0 业务持久化与安全上传

### 1. Scope / Trigger

- Trigger: auth、workspace、case 状态改为数据库权威，并新增多文件/ZIP 资料批次和后台操作合同。

### 2. Signatures

- `POST /api/workspaces/{workspace_id}/upload-batches`：multipart `title`、可选 `task_description`、`files[]`、可选 `command_id`；返回 `202 UploadBatchResponse`。
- `GET /api/workspaces/{workspace_id}/upload-batches/{batch_id}`：返回当前 `UploadBatchResponse`。
- `GET /api/workspaces/{workspace_id}/upload-batches/studio?batch_id=...`：返回 `StudioProjection`。
- `POST /api/workspaces/{workspace_id}/upload-batches/{batch_id}/retry`：JSON `command_id`、`batch_revision`；返回 `202 UploadBatchResponse`。
- 业务数据库表至少包括 `users`、`sessions`、`workspaces`、`cases`、`upload_batches`、`evidence_files`、`file_dispositions`、`operation_jobs`、`agent_run_attempts`。

### 3. Contracts

- 环境键：`DATABASE_URL`、`CHECKPOINT_DATABASE_URL`、`STORAGE_ROOT`、`UPLOAD_MAX_BYTES`、`UPLOAD_MAX_FILES`、`UPLOAD_MAX_TOTAL_BYTES`、`ARCHIVE_MAX_MEMBERS`、`ARCHIVE_MAX_UNCOMPRESSED_BYTES`、`ARCHIVE_MAX_DEPTH`、`ARCHIVE_MAX_RATIO`。
- `StudioProjection.next_action` 是带 `kind` 的联合模型；前端只消费业务阶段，不推导 Worker/Agent 状态。
- `OperationJob` 由 `target_type + target_id + business_revision + command_id` 唯一幂等；claim 创建对应 `AgentRunAttempt`，结果投影需通过 revision/accepted pointer CAS。

### 4. Validation & Error Matrix

- 未登录/越权 -> `401/403`；授权范围内不存在 -> `404`。
- 未支持扩展名 -> `415 UNSUPPORTED_FILE_TYPE`。
- 文件、总上传、ZIP 展开或条目数量超限 -> `413` 对应限制错误。
- 路径穿越、特殊文件、损坏或过深 ZIP -> `422` 安全错误。
- 陈旧批次 revision、无可重试操作或错误状态 -> `409`。
- 业务 schema 未迁移到 Alembic head -> startup/schema check fail closed，不自动建生产表。

### 5. Good/Base/Bad Cases

- Good: 多份可读取资料返回 `202`，文件摘要带 hash/解析状态，Worker 完成后投影变为 `confirm_file_roles`。
- Base: ZIP 内含可读 Markdown 和不支持扩展名；两者都保存，后者标为 `unsupported` 并进入阻塞提示。
- Bad: `../x.md`、绝对路径、symlink、损坏 ZIP、重复命令覆盖旧批次或把参考资料放进 runtime 响应。

### 6. Tests Required

- API：上传 `202`、跨用户 `403`、纯读轮询、重复 `command_id`、重试命令和文件用途 revision 冲突。
- 安全：路径穿越、目录项、符号链接/特殊文件、损坏 ZIP、嵌套、zip bomb/压缩比、文件数/大小/展开量和部分不支持文件。
- Operation：六种 kind 的幂等、lease reclaim、并发 claim 单胜者、自动 Attempt、retryable/failed、projection_pending、CAS superseded。
- 持久化：新 Python 进程读取 user/workspace/upload batch；PostgreSQL 17 migration、schema check 和 API smoke。

### 7. Wrong vs Correct

#### Wrong

```python
path = storage_root / upload.filename
path.write_bytes(await upload.read())
```

#### Correct

```python
staged = storage.stage_bytes(batch_id, file_id, content)
storage.publish(staged.key, f"evidence/{batch_id}/{file_id}")
```

用户文件名只保留为展示元数据，存储路径始终由服务端生成并经过 namespace 校验。
