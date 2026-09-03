# M0 Next.js 对接：仓库合同审计

## 审计结论

当前 FastAPI 后端已经拥有题目收集、材料保存、异步维度生成、维度编辑和发布的主体能力，但不能直接支撑本轮确认的全部 Web 行为。前端开始前必须先补齐少量后端合同，否则界面只能靠隐藏按钮或本地状态伪造业务门禁。

## 当前可直接复用的事实

### 认证

- `POST /api/auth/register` 通过数据库唯一 `admin_slot` 原子保证只能创建一个管理员（`backend/app/features/auth/repository.py:52`、`backend/app/features/auth/service.py:63`）。
- `POST /api/auth/login` 支持用户名或邮箱，成功后写入 `HttpOnly`、`SameSite=Strict` Cookie（`backend/app/features/auth/service.py:50`、`backend/app/features/auth/service.py:79`）。
- `GET /api/auth/me` 与 `POST /api/auth/logout` 已存在（`backend/app/features/auth/router.py:35`）。

### 评测集与凭证

- 后端 `scene` 是题目的第一层归属，列表已返回名称、描述、题目数和有效凭证数（`backend/app/features/scenes/schemas.py:36`）。
- 已有创建、列表、详情、凭证签发、轮换、撤销接口（`backend/app/features/scenes/router.py:20`）。
- 凭证明文只在签发或轮换时返回，数据库只保存哈希；状态接口返回脱敏状态和最近使用时间（`backend/app/features/scenes/schemas.py:55`、`backend/app/features/scenes/repository.py:122`）。
- `GET /api/external/connection` 和批量上传会通过同一凭证确认评测集归属；上传 payload 不能伪造 `scene_id`。

### 题目与维度

- `GET /api/questions` 强制指定 `scene_id`，可以按状态筛选；列表返回标题、状态、维度数、更新时间和下一步动作（`backend/app/features/question_library/router.py:23`、`backend/app/features/question_library/schemas.py:248`）。
- 详情返回六类材料、当前维度、状态、错误和内部并发 revision（`backend/app/features/question_library/schemas.py:267`）。
- 材料只通过“保存并重新生成”修改；提交会覆盖当前材料、作废旧维度、递增 revision 并排队新任务（`backend/app/features/question_library/service.py:341`）。
- 生产 Worker 将题目、参考样例、Bad case/老师反馈、标准答案和记忆材料交给真实模型动态生成维度（`backend/app/features/question_library/rubric_generation.py:41`、`backend/app/lib/ai_runtime/adapters.py:129`）。
- 生产 Prompt 要求根据材料输出 2–6 个维度；每项只有 `criterion + pass_score`，`pass_score` 为 0–10 整数（`backend/app/lib/ai_runtime/adapters.py:62`、`backend/app/lib/ai_runtime/adapters.py:162`）。
- `FakeRubricGenerator` 中固定的两三条维度仅用于确定性测试（`backend/app/lib/ai_runtime/adapters.py:81`）；生产 Worker 通过 `production_worker()` 安装 `ModelRubricGenerator`（`backend/app/lib/operations/worker.py:193`）。
- `PATCH /criteria` 已支持用老师提交的 1–20 项最终列表整体覆盖当前维度（`backend/app/features/question_library/schemas.py:200`、`backend/app/features/question_library/service.py:460`）。20 是输入安全上限，不是固定候选数量。

## 必须补齐的后端合同

### 1. 首次注册状态

问题：未登录前端无法区分“系统为空，可创建首个管理员”和“管理员已存在，只能登录”。直接展示注册入口后再等 409，不能满足已确认的关闭入口行为。

计划：新增匿名只读 `GET /api/auth/bootstrap`，只返回：

```json
{"registration_available": true}
```

它不返回管理员姓名、邮箱、ID 或其他可枚举信息。数据库唯一约束继续作为并发注册最终防线。

### 2. 本机密码恢复

问题：当前 `admin_cli` 只管理评测集与凭证，没有密码恢复。

计划：新增 `account reset-password` 子命令。新密码通过 `getpass` 交互输入和二次确认，不接受 argv、环境变量或标准输出传值；复用认证层密码校验/哈希逻辑，成功后删除该管理员全部 Session，使旧密码与旧会话立即失效。

### 3. 评测集元数据与空集删除

问题：当前只支持创建/读取，不支持修改名称、描述或删除。

计划：

- `PATCH /api/scenes/{scene_id}`：更新名称和描述；同名返回 `409 SCENE_NAME_EXISTS`，无变化返回明确冲突或直接返回当前值，最终实现必须只有一种合同。
- `DELETE /api/scenes/{scene_id}`：只在事务内确认 `question_count == 0` 时删除；非空返回 `409 SCENE_NOT_EMPTY`。
- 删除空评测集时允许数据库级联删除它的凭证和零题批次回执；并发上传与删除必须由数据库约束/原子条件保证不会出现孤儿题目或半删状态。
- CLI 继续作为备用入口，并同步支持元数据修改和同一删除规则，不能绕过 Service。

### 4. 人工确认维度门禁

问题：AI 生成后已经有非空 `criteria_json`，当前 `publish()` 只检查列表非空，因此可以绕过老师选择与保存直接发布（`backend/app/features/question_library/service.py:540`）。

计划：新迁移为题目增加 `criteria_confirmed` 布尔字段：

- 上传、AI 生成成功、材料重新生成：`false`；
- 老师通过 `PATCH /criteria` 成功保存至少一项最终维度：`true`；
- 发布：除非 `criteria_confirmed == true`，否则返回 `409 CRITERIA_NOT_CONFIRMED`；
- 现有已发布数据迁移为 `true`，其他现有题目保守迁移为 `false`。

详情和列表公开 `criteria_confirmed`。`next_action` 应区分 `review_criteria` 与 `publish`，不能继续把两者合并成模糊的 `review_and_publish`。

### 5. 已发布题目重新打开审改

问题：当前已发布题目直接修改维度返回 `409 PUBLISHED_USE_SAVE_REGENERATE`；若材料没变化，又不能用 `save-regenerate` 制造无意义 AI 调用。

计划：新增 `POST /api/questions/{question_id}/review-reopen`，请求复用 `command_id + content_revision`：

- 只允许来源状态 `published`；
- 原子改为 `pending_review` 并清空当前 `published_at`；
- 保留六类材料、现有维度和 `criteria_confirmed=true`；
- 重复、陈旧 revision 或错误状态返回明确 409；
- 不创建版本、快照或历史记录。

### 6. 受保护的题目硬删除

问题：当前 `DELETE /api/questions/{id}` 除生成中外均无二次门禁，且无 revision 防并发。

计划：保留原路径但改为接收 JSON 请求体：

```json
{
  "content_revision": 1,
  "confirmation_title": null
}
```

- `generating`：`409 RUBRIC_GENERATING`；
- `published`：`409 PUBLISHED_REOPEN_REQUIRED`，必须先重新打开；
- 从未发布的 `pending_review` / `generation_failed`：普通确认后可删；
- 曾发布后重新打开的题目：必须提供与当前标题完全匹配的 `confirmation_title`，否则 `422 DELETE_CONFIRMATION_MISMATCH`。

为使刷新后仍可执行这条规则，迁移增加内部 `ever_published` 布尔值；发布时置真，重新打开和材料重生成不清除。详情只暴露派生的 `delete_confirmation_required`，不把它包装成版本历史。

### 7. 一次性凭证响应保护

签发/轮换响应应增加 `Cache-Control: no-store`。Next.js 通过同源 `/api` 代理在浏览器中直接接收明文，不能经过会记录 body 的自建 BFF；明文只进入瞬时组件状态和用户剪贴板。

## 状态与下一步动作

```text
上传成功                  -> generating / wait_for_generation
AI 生成成功               -> pending_review / review_criteria / confirmed=false
AI 生成失败               -> generation_failed / retry_generation
老师保存最终维度           -> pending_review / publish / confirmed=true
老师发布                  -> published / published / ever_published=true
已发布题目重新打开         -> pending_review / publish / confirmed=true
修改任一材料并重新生成      -> generating / wait_for_generation / confirmed=false
```

前端不能自行推断并覆盖不允许的状态；Service、Schema、OpenAPI 和测试必须同步拥有上述事实。

## 当前运行风险

- `.env` 当前标记为 `AI_RUNTIME_MODE=production`。
- 现场发现两棵来自本仓库的 Worker 进程。进程列表不能证明它们连接同一数据库，但最终真实验收前必须解析数据库身份，只保留一个服务于验收数据库的生产 Worker。
- `/healthz` 的 `ai=production` 只表示配置模式，不证明 Provider 调用或 Worker 处理成功；最终证据必须包含真实上传到真实动态维度生成的完整链路。

## 同步面

上述合同变化必须同步：

- Feature Schema、Router、Service、Repository；
- Alembic `0019` 迁移、fresh/upgrade/downgrade/schema-ready 检查；
- `backend/openapi.json`（只通过生成器更新）；
- API、迁移、并发、权限和错误码测试；
- README、管理员 CLI 和 Next.js 生成类型；
- `.trellis/spec/backend/` 与跨层规范中的现行状态机。
