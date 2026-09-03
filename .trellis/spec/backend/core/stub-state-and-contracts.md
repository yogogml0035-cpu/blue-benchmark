# 持久化状态、数据与合同

## 先确认当前实现边界

当前后端是统一的评测题库：业务数据库（SQLAlchemy + Alembic）保存题目六类材料、两字段评分维度、场景与凭证、批量收题回执和评分生成任务；恰好一个生产 Worker 负责评分维度生成。前端（`frontend/`）只做呈现，不持有业务事实；后端没有文件上传解析、没有 Checkpointer。规范以源码、测试和迁移为准；规划文档中尚未落地的能力不能当作当前事实。

| 已实现事实 | 尚未实现、需另立任务的计划 |
|---|---|
| `auth`、`scenes`、`question_library` 使用业务数据库表 | 评测执行与自动评分 |
| 单管理员（`admin_slot` 唯一约束原子生效），业务老师不建账号 | 多管理员、细粒度角色 |
| 场景凭证只存 SHA-256 hash，签发/轮换只回显一次明文 | 凭证过期时间、作用域细分 |
| 批量收题整批全成全败 + `command_id + payload_hash` 幂等 | 跨场景移动/复制题目 |
| 评分维度只有 `criterion + pass_score`，固定 10 分逐项及格 | 实际评分执行与提交 |
| `OperationJob` 负责生成任务排队、租约、重试与幂等 | 其他异步任务类型 |

数据库重启不会清空业务记录；只有测试中的清理逻辑会清空测试数据库。不要把业务数据库记录与 Worker 的瞬态租约/租期当作同一事实源。

## 业务数据所有权

每个 Repository 只拥有自己的 Record 到数据库行的映射和读写函数：

- `auth/repository.py`：`UserRecord`、`users`、`sessions` 表；
- `scenes/repository.py`：`SceneRecord`、`SceneCredentialRecord`、`scenes`、`scene_credentials` 表；
- `question_library/repository.py`：`QuestionRecord`、`CommandReceipt`、`eval_questions`、`batch_upload_commands` 表。

Record 是内部状态（`@dataclass(frozen=True)`），Pydantic Schema 是外部合同。Service 必须显式投影，例如 `question_library/service.py::_detail_response`；不要直接序列化 Record 的全部字段。

测试通过 `clear_business_data()` 清空业务测试数据库；`backend/tests/conftest.py` 为每个 pytest 进程提供独立 SQLite 文件。新增表时必须纳入 `clear_business_data()` 的依赖逆序清理与 `check_schema_ready()` 的合同。

## 评测集生命周期合同

- `PATCH /api/scenes/{id}` 提交完整目标元数据：名称沿用创建时的非空/长度/同名规则（同名 `409 SCENE_NAME_EXISTS`），`description=null` 明确清空描述。无变化时直接返回当前值，不另设“无变化冲突”合同。
- `DELETE /api/scenes/{id}` 只允许当前无题目的评测集：空判与删除是同一条件 DELETE（`WHERE NOT EXISTS(question)`），并发上传已建题时原子返回 `409 SCENE_NOT_EMPTY`，不留孤儿题目或半删状态。
- 删除空评测集由数据库级联清理其凭证与零题批次回执；场景与凭证、回执之间的外键必须保持 `ondelete=CASCADE`。
- CLI `scenes update`/`scenes delete` 复用同一 Service，不拥有第二套规则。

## 题目状态机

对外状态唯一来源是 `question_library/schemas.py::QuestionStatus`。状态转换由 `question_library/service.py` 与 `rubric_generation.py` 集中执行：

```text
批量收题 -> generating（criteria_confirmed=false）
generating -> pending_review | generation_failed
generation_failed -> generating（retry）
pending_review -> published（publish，要求 criteria_confirmed=true；成功置 ever_published=true）
published -> pending_review（review-reopen，保留材料/维度/确认事实，清空 published_at）
任意状态 -> generating（save-and-regenerate，published 回到待处理，criteria_confirmed 归 false）
```

`next_action` 由状态 + `criteria_confirmed` 共同决定：`pending_review` 未确认是 `review_criteria`，已确认是 `publish`。

保持以下已实现合同：

- 批量收题成功后每题立即排队生成；生成失败保留题目并支持重试，不回滚同批其他题。
- “保存并重新生成”是唯一材料编辑动作：覆盖材料、`content_revision` 递增、旧维度立即失效（`criteria_confirmed=false`）并重新排队；已发布题目被编辑后回到待处理，不保留历史版本；`ever_published` 不清除。
- 仅改 `title` 不触碰六类材料，也不触发重新生成。
- `generating` 中的题目禁止改维度、发布、删除。
- 发布要求存在非空评分维度，且 `criteria_confirmed=true`（AI 初稿不能直接发布）。
- `review-reopen` 只接受 `published` 来源；重复、错误状态或陈旧 revision 返回 409。
- 删除门禁按顺序：陈旧 revision（409 STALE_REVISION）、生成中（409 RUBRIC_GENERATING）、已发布（409 PUBLISHED_REOPEN_REQUIRED）、曾发布题标题确认（422 DELETE_CONFIRMATION_MISMATCH）；“曾发布”是服务端持久化事实（`ever_published`），详情以派生的 `delete_confirmation_required` 暴露。

新增状态时要同时检查 Schema、Service、`next_action` 映射、API 测试和 OpenAPI，不能只改枚举。

## 评分维度合同

每个维度只有 `criterion` 与 `pass_score`（0..10 整数），固定满分 10 分，逐项必须及格，任意一项不及格整题不通过（`rubric_rules.evaluate_question_pass`）。`criterion` 必须写明判断对象、合格表现和主要问题；孤立标签（“准确性”“创新性”等，含标点/括号包裹与列表组合）与过短文本被拒绝。管理员增删改维度与 AI 生成共用同一可执行性/隐私校验。

## 批量收题与幂等

`POST /api/external/question-batches` 由场景凭证（Bearer）鉴权，场景归属只来自凭证，payload 不接受 `scene_id`。整批在一个事务内创建题目、生成任务与回执：

- 相同 `command_id + 相同 payload`：返回原结果（幂等重放）。
- 相同 `command_id + 不同 payload`：`409 COMMAND_ID_REUSED`。
- 任一题校验或写入失败：整批回滚，无半批数据。
- 服务端对题目、材料、标题与 `client_case_id` 做隐私兜底（凭证、主机路径、系统控制内容），绕过手段（零宽字符、全角同形、Unicode 归一化）必须先归一化再扫描。

## 认证与归属顺序

- 管理员路由用 `Depends(auth_service.require_current_user)` 解析会话；单管理员由数据库唯一约束原子保证。
- `GET /api/auth/bootstrap` 匿名只返回 `registration_available`，不泄露管理员身份；首注与否的最终防线仍是数据库唯一约束。
- 本机密码重置只走 `scripts.admin_cli account reset-password`：`getpass` 两次隐藏输入、复用认证层长度校验与 PBKDF2 哈希，同事务更新唯一管理员并删除其全部 Session；密码不进入 argv、输出或日志。
- 外部收题用 `scenes.service.require_scene_principal` 解析凭证，返回 `ScenePrincipal(scene_id, credential_id)`；凭证只能“查询连接状态 + 批量上传”，不能读取/修改/删除/发布题目。
- 保持 `401`（未登录/凭证无效）、`403`（越权）、`404`（授权范围内不存在）、`409`（状态/版本/幂等冲突）的语义。

密码只以 PBKDF2 哈希存入内部 Record；Session Cookie 为 `HttpOnly`、`SameSite=Strict`、`Secure` 默认开启；场景凭证只存 hash，明文只在签发/轮换时返回一次，签发/轮换响应携带 `Cache-Control: no-store` 与 `Pragma: no-cache`。

## Worker 与评分维度生成

`app/lib/operations` 的 `OperationJob` 负责生成任务排队、租约、重试与幂等：

- 任务由 `target_type + target_id + business_revision + command_id` 唯一幂等；claim 创建对应 `AgentRunAttempt`。
- Worker 通过 `worker_process_lock` 保证同一业务库单消费者；心跳续租容忍瞬时失败，持续失败才放弃。
- 评分维度提交必须原子：`rubric_generation.commit_generation_result` 在同一事务内校验“任务仍归当前 Worker 且业务版本一致”与“题目仍指向该任务且 `content_revision` 一致”，同时写入维度与任务终态，防止旧任务/重复执行覆盖新材料或管理员编辑。
- 材料被编辑后旧任务在提交时被 fencing 判为 `superseded`，不得覆盖新版本。
- lease 过期导致的终态失败必须把题目投影为 `generation_failed`，不能留下永久 `generating`。

## 不要这样做

- 不要把题目材料、评分维度或状态写进 Worker 元数据、日志或错误消息正文。
- 不要把评分生成失败映射成 500；应返回可重试的业务失败状态。
- 不要让场景凭证或管理员会话互相顶替；两类主体的授权路径必须分离。
- 不要在响应中返回明文凭证、`token_hash`、宿主机路径或材料原文之外的内部字段。
