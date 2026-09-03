# Skill Eval Platform（后端）

这是 M0 评测题后端：业务老师在本地 Agent 里完成真实任务后，调用仓库内上传 Skill，从当前可见上下文整理评测题并经确认后批量上传；后端保存题目的六类材料，并自动为每道题生成两字段评分维度（`criterion + pass_score`，固定 10 分、逐项及格），供后续新前端与评测运行使用。

当前仓库是**纯后端工程**：FastAPI + SQLAlchemy/Alembic 业务数据库 + 单消费者 Worker。没有前端，也不依赖 Node.js/pnpm。题目、材料、评分维度和发布状态都保存在业务数据库，OpenAPI 是唯一对外机器合同。

## 领域模型

- **场景优先**：场景是题目导航与归属的第一层业务容器。场景列表（`GET /api/scenes`）是管理端查询的起点；题目列表必须在场景范围内查询，`GET /api/questions` 必须携带有效 `scene_id`。平台不提供无场景的全量题目查询、跨场景搜索或跨场景筛选。
- **一道题的六类材料**：题目、参考样例、Bad case（绑定老师反馈）、标准答案、记忆材料，以及仅供识别的用例标题 `title`。
- **两字段评分维度**：每个维度只有 `criterion`（完整可执行的评判标准）与 `pass_score`（0..10 整数及格分），固定满分 10 分，任一维度不及格整题不通过。
- **状态机**：`generating → pending_review → published`，失败为 `generation_failed`；已发布题目可 `review-reopen` 退回 `pending_review`；“保存并重新生成”是唯一材料编辑动作，覆盖材料、作废旧维度并重新排队生成。
- **老师确认门禁**：AI 生成的维度只是候选草稿（`criteria_confirmed=false`），发布前必须经老师保存最终维度列表（`PATCH /criteria` 置 `criteria_confirmed=true`）；未确认的 AI 初稿不能发布。`next_action` 区分 `review_criteria`（待选择维度）与 `publish`（待发布）。
- **重新打开审改**：已发布题目通过 `POST /api/questions/{id}/review-reopen` 原子退回 `pending_review`，保留材料与维度、清空当前发布时间；不产生版本或快照。
- **受保护删除**：`generating` 禁止删除；`published` 必须先重新打开；曾发布过的题目删除时必须提交与当前标题完全一致的 `confirmation_title`（服务端持久化“曾发布”事实，刷新后仍然生效）。
- **单管理员**：平台只有一个管理员账号；业务老师不建账号，只通过场景凭证提交材料。场景凭证只有“查询连接状态 + 批量上传”的最小权限。`GET /api/auth/bootstrap` 匿名返回 `registration_available`，只暴露是否仍可首注。

## 本地准备

需要 Python 3.12–3.13、uv，以及 PostgreSQL（生产）或默认 SQLite（本地开发/测试）。

```bash
cp .env.example .env
```

编辑 `.env`：`AI_PROVIDER`、`AI_MODEL`、`AI_API_KEY`、可选 `AI_BASE_URL`、`AI_REQUEST_TIMEOUT_SECONDS`、`DATABASE_URL`、`OPERATION_LEASE_SECONDS`、`OPERATION_MAX_ATTEMPTS`。`AI_PROVIDER=openai` 使用 OpenAI 或 OpenAI 兼容厂商（兼容端点通常把 `/v1` 放在 `AI_BASE_URL`）；`AI_PROVIDER=anthropic` 使用 Anthropic 或兼容 Messages API 的服务。本地 HTTP 开发需显式设置 `SESSION_COOKIE_SECURE=false`。不要把真实密钥提交到 Git。

安装依赖：

```bash
uv sync --project backend --dev
```

## 启动 API 与 Worker

首次启动先执行业务迁移和检查：

```bash
make db-migrate
make db-check
```

在第一次启动生产 Worker 前，建议用合成输入验证目标 Provider 的结构化输出：

```bash
make ai-smoke
```

成功标记为 `AI_SMOKE=OK ...`；该命令会产生一次真实模型调用，没有真实密钥时应先补齐配置，不能用 Fake 结果冒充真实 AI 验收。

同一个业务数据库只允许一个长驻 Worker。`make start-all` 会同时启动 API 和一个 Worker；也可以分两个终端分别执行：

```bash
make backend   # API，http://127.0.0.1:8000
make worker    # Worker
```

成功标记：

- API 健康检查：<http://127.0.0.1:8000/healthz> 返回 `status=ok`、`persistence=business database`，`ai` 与当前 `AI_RUNTIME_MODE` 一致；
- OpenAPI 文档：<http://127.0.0.1:8000/api/docs>。

若 API 因 schema 未就绪退出，先运行 `make db-migrate` 和 `make db-check`。Fake 模式（`AI_RUNTIME_MODE=fake` 或 `--fake`）仅用于确定性测试，只允许连接 SQLite 业务库，不能用它做真实 AI 验收。

## 管理员 CLI（无前端阶段）

场景与凭证管理通过仓库命令完成，直接读写业务数据库。在 `backend/` 目录下运行（参数不经过 shell 插值）：

```bash
cd backend && uv run python -m scripts.admin_cli scenes create --name 媒体场景
cd backend && uv run python -m scripts.admin_cli scenes list
cd backend && uv run python -m scripts.admin_cli scenes status --scene-id <scene_id>
cd backend && uv run python -m scripts.admin_cli scenes update --scene-id <scene_id> --name 新名称 [--description ...]
cd backend && uv run python -m scripts.admin_cli scenes delete --scene-id <scene_id>
cd backend && uv run python -m scripts.admin_cli credentials issue --scene-id <scene_id> --label ci
cd backend && uv run python -m scripts.admin_cli credentials rotate --scene-id <scene_id>
cd backend && uv run python -m scripts.admin_cli credentials revoke --scene-id <scene_id> --credential-id <credential_id>
cd backend && uv run python -m scripts.admin_cli account reset-password
```

明文凭证 token 只在 `issue`/`rotate` 成功时显示一次，后续 `status`/`list` 查询绝不返回明文。

- `scenes update` 提交完整的目标元数据：省略 `--description` 表示清空描述；同名冲突返回错误。
- `scenes delete` 与 API 共用同一 Service：只有当前无题目的评测集可删除，删除会级联撤销其凭证；非空场景被拒绝。
- `account reset-password` 通过两次隐藏交互输入接收新密码（不接受 argv/环境变量），成功后旧密码与全部旧会话立即失效。

## 外部批量收题

上传 Skill 用场景凭证（Bearer `sep_...`）调用：

```
POST /api/external/question-batches
```

请求体为 `{ "schema_version": "1.0", "command_id": ..., "cases": [ ... ] }`，每题含 `client_case_id`、`title`、`task_prompt`、`reference_examples[]`、`bad_cases[]`、`reference_answer`、`memory_materials[]`。整批全成全败；相同 `command_id + 相同 payload` 幂等重放，变更 payload 返回冲突。场景由凭证决定，payload 不接受 `scene_id`。上传成功后每题自动排队生成评分维度。

凭证可用 `GET /api/external/connection` 查询自身连接状态（返回绑定场景与凭证 ID，绝不返回 token）。

## 管理员题目查询（场景优先）

管理员接口走 Session Cookie。题目列表必须在场景范围内查询：

```
GET /api/questions?scene_id=<scene_id>
GET /api/questions?scene_id=<scene_id>&status=pending_review
```

- `scene_id` 必填：缺少参数返回 `422 VALIDATION_ERROR`，不会退化为返回全部题目；
- 场景不存在返回 `404 RESOURCE_NOT_FOUND`，不伪装成空列表；
- `status` 可选，只在指定场景内筛选；
- 题目详情与命令路由仍是 `/api/questions/{question_id}/...`；
- 场景凭证不能访问任何管理员题目接口（返回 401）。

题目命令路由（均为管理员会话）：

- `PATCH /api/questions/{id}/criteria`：老师保存最终维度列表（1–20 项），成功后 `criteria_confirmed=true`；
- `POST /api/questions/{id}/publication`：要求非空维度且 `criteria_confirmed=true`，否则 `409 CRITERIA_NOT_CONFIRMED`；成功置 `ever_published=true`；
- `POST /api/questions/{id}/review-reopen`：仅 `published → pending_review`，保留材料/维度，清空当前发布时间；
- `DELETE /api/questions/{id}`：请求体 `{ "content_revision", "confirmation_title"? }`，按 revision、生成中、已发布、曾发布标题确认的顺序门禁。
- `PATCH /api/scenes/{id}` / `DELETE /api/scenes/{id}`：评测集改名/描述与空集删除（非空返回 `409 SCENE_NOT_EMPTY`）。

## 题目上传 Skill

`skills/ai-eval-push/` 提供场景绑定的上传 Skill：本地 Agent 从当前可见上下文识别 `0..N` 道题并整理六类材料，老师整批预览确认后，用场景凭证调用上述批量接口。Skill 只负责识别、整理、确认与上传，不读取/管理已上传题目、不生成规则、不发布。

```bash
python skills/ai-eval-push/scripts/push_eval_cases.py connection
python skills/ai-eval-push/scripts/push_eval_cases.py validate --batch-file batch.json
python skills/ai-eval-push/scripts/push_eval_cases.py push --batch-file batch.json
```

Skill 客户端测试（隔离 HTTP + 秘密/路径泄漏回归）：

```bash
cd backend && uv run pytest ../skills/ai-eval-push/tests/ -q
```

## 合同与自动化验证

后端测试使用每次全新的临时 SQLite，覆盖批量收题原子性/幂等/隔离、评分维度生成与重试、发布与状态机、迁移（旧 head 升级 + fresh DB + downgrade）、OpenAPI 合同，以及一轮对抗审查后的安全/并发加固回归。

```bash
make test    # pytest + OpenAPI 漂移检查
make build   # 后端编译/导入验证
```

`make contract-check` 校验已提交的 `backend/openapi.json` 与当前 FastAPI 合同一致。后端合同变更后先运行：

```bash
make openapi
```

不要手改 `backend/openapi.json`。

## 显式真实 AI 验收

真实 Provider 端到端（批量上传 → 生产 Worker 生成维度 → 初稿拒发布 → 老师保存确认 → 发布 → 重新打开审改 → 再发布）只允许本地显式运行：

```bash
cd backend && uv run python -m scripts.accept_real_ai_rubric
```

成功输出 `ACCEPT_REAL_AI=OK`；runner 只输出阶段标记、计数和错误码，不输出材料正文或凭证。

## 目录边界

- `backend/`：FastAPI 应用、迁移、脚本、测试。
- `skills/ai-eval-push/`：题目上传 Skill（`SKILL.md` + 标准库客户端脚本 + API 合同 reference + 隔离测试）。
- 前端、Next.js、Playwright、TypeScript DTO 生成均已移除，不再作为运行或验收依赖。
