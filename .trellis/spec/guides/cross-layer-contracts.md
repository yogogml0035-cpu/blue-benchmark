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

任务分组的空集合必须结合批次状态解释：后端允许分析结果 `groups=[]`，但只要批次已就绪且存在未忽略文件，前端仍必须保留老师手动新增、分配和确认的路径；分析中、失败或没有可用文件时则分别等待、重试或上传新批次。不要把 `task_packages=[]` 统一渲染成无法继续的空页。

## 证据等级

- `pytest` / typecheck / build 通过：对应自动化门通过；
- 预演状态可渲染：开发 fixture 与类型可用；
- 浏览器闭环实际完成：真实前后端交互已验收；
- 文档或 Mock 写明能力：只代表设计或说明，不能升级为运行证据。

## Authoring conversation release contract

### 1. Scope / Trigger

- Trigger: the first-stage authoring flow adds a database-backed conversation,
  safe-event stream, candidate question projections, and matching App Router
  screens.
- Scope: candidate discovery, teacher-controlled boundaries, input/answer
  review, recovery, and the cross-layer OpenAPI chain. Rubric publication and
  human scoring remain separate child tasks.

### 2. Signatures

- `POST /api/workspaces/{workspace_id}/authoring-conversations` creates a
  `202` conversation using `command_id`, optional `upload_batch_id`, manual
  instruction/message, and optional teacher reference answer.
- `POST .../{conversation_id}/messages` accepts a teacher message plus an
  optional `question_draft_id` and attachment IDs, guarded by
  `conversation_revision`.
- Boundary mutations use `action=confirm|split|merge|discard`; input/answer
  edits use `draft_revision`; all writes carry a stable `command_id`.
- `authoring_conversations`, `authoring_messages`, `safe_stream_events`, and
  `benchmark_question_drafts` are forward-only business projections. Safe
  events retain the latest 500 sequence values per conversation; the GET
  snapshot remains the recovery authority when older events are compacted.

### 3. Contracts

- Only parsed, non-ignored evidence IDs enter the authoring analyzer. A legacy
  upload role maps `brief -> brief` and `runtime -> fact`; `judge`,
  `provenance`, and unknown roles reopen as `unconfirmed`.
- After boundary confirmation, each active draft uses a distinct internal
  question-agent thread and accepted checkpoint. The agent may ask one safe
  Chinese question; only a teacher-marked standard-answer message can become
  the reference answer.
- A normal teacher message that answers a pending question is targeted to that
  draft by the service; the draft stores the prompt sequence so an older
  targeted answer cannot be replayed as a new response.
- A projection failure stores the already-validated internal projection in the
  OperationJob. Retry chooses `authoring_reproject` and commits that payload
  without another model call; a missing payload is not treated as safely
  reprojectable.
- A teacher may edit a local draft while an AI operation is active, but the
  save/confirm commands stay disabled in the UI and are rejected by the
  service/repository with `409`.
- A boundary mutation may target only `candidate` drafts. Once a draft has
  entered input/answer review or confirmation, its evidence boundary is
  immutable in this first-stage flow.
- If a file-backed analyzer returns zero usable groups, the service persists a
  zero-candidate recoverable state; it must not manufacture an evidence-free
  question.

### 4. Validation & Error Matrix

- non-owner workspace or conversation -> `403 FORBIDDEN`;
- unknown conversation/draft -> `404 RESOURCE_NOT_FOUND`;
- active authoring operation -> `409 AUTHORING_ACTIVE`;
- stale conversation/draft revision -> `409 STALE_AUTHORING` or
  `409 STALE_QUESTION_DRAFT`;
- boundary action on a non-candidate draft -> `409 QUESTION_BOUNDARY_LOCKED`;
- unconfirmed material role or missing teacher answer -> `409` confirmation
  error;
- event kind, payload key, payload size, internal term, or host path outside
  its allowlist -> reject before persistence;
- every command replay with the same payload returns the original projection;
  a different payload returns `409 COMMAND_ID_REUSED`.

### 5. Good/Base/Bad Cases

- Good: a real parsed file yields candidate groups, the teacher confirms or
  splits them, assigns roles, supplies a teacher answer, and refreshes to the
  same server snapshot.
- Base: an analyzer finds no group or all files are ignored; the UI explains
  the missing evidence and offers recovery instead of showing a confirmable
  no-evidence draft.
- Bad: a delayed browser command tries to merge a confirmed draft, or a model
  emits an ignored/legacy file ID; the request fails closed without changing
  the existing projection.

### 6. Tests Required

- API tests assert owner isolation, one active operation, command replay and
  conflict, boundary lock, split/merge/discard evidence coverage, ignored and
  legacy role handling, safe-event rejection/retention, and recovery states.
- `make openapi`, `make test`, `make build`, and `git diff --check` must pass.
- The explicit browser gate must run against a production API, one production
  Worker, the real Provider, and `/Users/hsikey/BenchMark/EvalData`; assert
  multi-question creation, a second teacher turn, confirmation, refresh, and
  no browser console errors.

### 7. Wrong vs Correct

#### Wrong

```python
# The UI hid the action, so the API accepts any selected draft.
mutate_boundaries(draft_ids=payload.draft_ids, action=payload.action)
```

#### Correct

```python
if any(draft.status != "candidate" for draft in drafts):
    raise RepositoryConflict("only candidate question draft boundaries can be changed")
```

The server owns the invariant; UI disabling is only an interaction aid.

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
- rubric 未开始是可读取的 `200 + not_started` 页面状态；生成轮询只持续到 `queued|processing` 离开，投影待恢复单独走无模型 `rubric_reproject`，避免把预期资源空态变成浏览器 404 噪声。
- `BenchmarkQuestionRevision` 进入 Working Set 时必须沿 `question_revision_id + question_revision_number + question_revision_hash` 传过 OpenAPI、Feature Service、Repository 和版本 builder；与旧 `TaskPackage` 混合时整包升级到 v2，v1 历史字节不可重拼。

## Scenario: External authoring connection and draft ingestion

### 1. Scope / Trigger

- Trigger: a logged-in teacher explicitly binds one local Agent to one
  Workspace and the Agent uploads one complete text evaluation-case draft.
- Scope: connection-code exchange, least-privilege bearer auth, exact text
  preservation, idempotent draft creation, website handoff and empty-workspace
  recovery. The external API never starts AI, rubric or publication work.

### 2. Signatures

- `POST /api/workspaces/{workspace_id}/authoring-connections` creates a short
  lived one-time code; `DELETE .../{connection_id}` revokes the binding.
- `POST /api/external/authoring-connections/exchange` consumes the code once
  and returns a bearer token; `GET /api/external/authoring-connection` only
  returns the bound display name and scopes.
- `POST /api/external/evaluation-case-drafts` accepts `schema_version=1.0`,
  `command_id`, `title`, raw `task_requirement`, text `input_files`,
  `bad_samples` and raw `reference_answer_text`; it has no Workspace/account
  path parameter.
- `authoring_connections` stores only code/token hashes and a request lease;
  `authoring_external_commands` stores only connection-scoped payload hash and
  draft/conversation IDs; external text is stored as ready evidence objects.

### 3. Contracts

- Full input files require matching UTF-8 byte size and SHA-256; excerpts
  require a source display name and explicit excerpt marker. Only `.txt` and
  `.md` are accepted, with a 1 MiB per-file and 2 MiB canonical payload limit.
- The API creates a normal `input_answer_review` draft and no `OperationJob`.
  The response contains `draft_ready`, current Workspace display name and an
  exact same-origin URL with `?draft=<draft_id>`; the URL never contains a
  token.
- Web Session GET/PATCH may display and edit external text evidence. External
  bearer auth has only `connection:read` and `draft:create`; it cannot read,
  patch, score, publish, download or delete a draft.
- Empty `GET /upload-batches/studio` returns `200` with `batch_id=null` and
  `batch_status=none`, so a new Workspace is a recoverable upload state rather
  than a browser-console 404.
- If question confirmation already submitted rubric start, the route carries
  `started=1`; the rubric page polls `not_started` snapshots briefly before
  showing a manual start button, avoiding a second start command during the
  commit/GET race.

### 4. Validation & Error Matrix

- reused connection code -> `409 CONNECTION_CODE_REUSED`; expired/invalid code
  -> `409 CONNECTION_CODE_EXPIRED` or `401 CONNECTION_CODE_INVALID`;
  revoked token -> `401 EXTERNAL_TOKEN_INVALID`;
- same `connection_id + command_id + payload_hash` -> original draft response;
  same command with a different hash -> `409 COMMAND_ID_REUSED`;
- non-text, path-like source name, missing excerpt provenance, mismatched full
  hash/size, vague feedback or private/tool trace -> `422` with a stable code;
- payload/file/count over limit -> `413`; per-token concurrency or frequency
  over limit -> `429` without正文; stale request/command leases are reclaimable;
- an external bearer presented to a Web Session endpoint never authenticates;
  a non-owner Session cannot create, inspect or revoke another Workspace.

### 5. Good/Base/Bad Cases

- Good: create code, exchange once, push a complete EvalData Markdown file,
  replay the same command, then open the exact URL in the teacher browser and
  edit the text there.
- Base: no input files is allowed for a manual text-only draft; a Workspace
  with no upload batch still shows connection and upload controls.
- Bad: client supplies `workspace_id`, silently truncates a full file, puts a
  token in the URL, retries after revoke, or sends system/tool/private trace;
  fail closed without creating an AI job or leaking the body.

### 6. Tests Required

- API tests assert token/code hashes, one-time exchange, rebind/revoke,
  owner isolation, exact task/answer/file bytes, excerpt markers, bad-sample
  allowlist, command replay/conflict, no OperationJob, Web-only editing,
  storage cleanup and stale request/command lease recovery.
- Live HTTP E2E runs `scripts/accept_external_authoring.py` with
  `/Users/hsikey/BenchMark/EvalData`; browser E2E asserts the empty Workspace
  connection card, one-time-code Sheet, exact draft URL, 390px layout and no
  console errors.
- The real Provider/Worker E2E remains a separate gate and must still pass the
  three-file EvalData upload, rubric/package/lifecycle and real browser flow.

### 7. Wrong vs Correct

#### Wrong

```python
# The external client chooses the tenant and the router starts AI implicitly.
workspace_id = payload.workspace_id
create_conversation(workspace_id, payload)
operation_repository.create_or_get(kind="rubric_process", ...)
```

#### Correct

```python
# Tenant and scope come only from the bearer principal; upload is synchronous.
principal = require_external_principal(token)
draft = create_external_draft(principal.workspace_id, raw_payload)
assert no_operation_job_was_created(draft.id)
```
