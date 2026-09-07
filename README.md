# blue-benchmark

这是 M0 评测题平台：业务老师在本地 Agent 里完成真实任务后，调用仓库内上传 Skill，从当前可见上下文整理评测题并经确认后批量上传；后端保存题目的六类材料，并由真实 AI（受限 Deep Agent，运行在持久化检查点上）为每道题动态生成完整评分项——具体维度、0–10 整数建议通过分、少量关键分数表现说明（锚点）、维度依据与通过分依据（区分老师明确要求与 AI 推定，引用可对照材料核查）；管理员账号由环境变量（ADMIN_USERNAME/ADMIN_PASSWORD）写死并在后端启动时自动写入数据库，管理员在 Next.js 桌面管理端登录后完成评测集与凭证管理、带真实流式过程反馈的维度审改与发布。

仓库为后端 + 前端两层：**后端**是 FastAPI + SQLAlchemy/Alembic 业务数据库 + 恰好一个生产 Worker；**前端**是 Next.js App Router + TypeScript 的桌面管理端，浏览器经同源 `/api` 代理访问后端并复用 HttpOnly Session Cookie。题目、材料、评分维度和发布状态都保存在业务数据库，OpenAPI 是唯一跨层机器合同；前端类型由 `backend/openapi.json` 生成，不手写重复 DTO。

## 领域模型

- **场景优先**：场景是题目导航与归属的第一层业务容器。场景列表（`GET /api/scenes`）是管理端查询的起点；题目列表必须在场景范围内查询，`GET /api/questions` 必须携带有效 `scene_id`。平台不提供无场景的全量题目查询、跨场景搜索或跨场景筛选。
- **一道题的六类材料**：题目、参考样例、Bad case（绑定老师反馈）、标准答案、记忆材料，以及仅供识别的用例标题 `title`。
- **完整评分项**：每个维度包含 `criterion`（完整可执行的评判标准）、`pass_score`（0..10 整数及格分，固定满分 10 分、逐项及格）、`score_anchors`（少量关键分数的可观察表现说明；初始生成必须覆盖建议分，但对老师编辑永远不是白名单）、`criterion_basis` 与 `pass_score_basis`（依据说明 + 主张列表；每条主张标注 `teacher_explicit`/`ai_inferred`，老师明确要求必须附带可核查的材料引用）。人工新增维度可以显式携带空锚点与空依据。
- **生成运行基础**：生成由受限 Deep Agent 执行（只读挂载本题材料、无 shell/子代理/跨题记忆），图状态与工作文件持久化在专用 PostgreSQL 检查点库（加密序列化），同线程单写者由 advisory lock 保证；技术重试从检查点续跑而不重复初始输入。公开过程事件先落业务库（`question_run_events`，按 operation 连续 sequence）再经同源 SSE 送达浏览器，完成事件只在业务原子保存之后发出；生成结束后完整过程仍可回放。
- **状态机**：`generating → pending_review → published`，失败为 `generation_failed`，删除受理冻结为 `deleting`；已发布题目可 `review-reopen` 退回 `pending_review`。材料编辑与生成彻底解耦：材料逐模块自动保存（`PATCH /materials`，只写文本，不推进 `content_revision`、不动维度）；「重新生成」是独立确认动作（`POST /regenerate`），无条件作废全部维度并以新 thread 重跑，生成中触发即为打断重启（旧任务被 fencing 判 `superseded`）。已发布题目直接改材料被拒（先 `review-reopen`），重新生成则回到生成流程。
- **老师确认门禁**：AI 生成的维度只是候选草稿（`criteria_confirmed=false`），发布前必须经老师保存最终维度列表（`PATCH /criteria` 置 `criteria_confirmed=true`）；未确认的 AI 初稿不能发布。`next_action` 区分 `review_criteria`（待选择维度）与 `publish`（待发布）。
- **重新打开审改**：已发布题目通过 `POST /api/questions/{id}/review-reopen` 原子退回 `pending_review`，保留材料与维度、清空当前发布时间；不产生版本或快照。
- **受保护的完整删除**：`generating` 禁止删除；`published` 必须先重新打开；曾发布过的题目删除时必须提交与当前标题完全一致的 `confirmation_title`（服务端持久化“曾发布”事实，刷新后仍然生效）。`DELETE` 返回 `202` 只表示受理：题目原子冻结（`deleting`，全部写路径与事件回放拒绝）并登记持久清理作业；作业先清除该题全部历次运行 thread 的检查点数据（不依赖模型可用），验证零残留后才在同一业务事务删除题目、运行事件与生成历史。前端只有在题目真正 404 后才离开页面；清理失败可见、可重试，绝不提前报成功。
- **单管理员**：平台只有一个管理员账号，来自环境变量 `ADMIN_USERNAME`/`ADMIN_PASSWORD`（唯一权威）：API 启动时自动写入空库，已有账号与 env 不一致时以 env 为准覆盖（密码变化同时撤销全部旧会话），一致则零写入。不存在注册接口与首注流程。业务老师不建账号，只通过场景凭证提交材料；场景凭证只有“查询连接状态 + 批量上传”的最小权限。

## 本地准备

需要 Python 3.12–3.13、uv、Node.js ≥ 24、pnpm，以及 PostgreSQL（生产）或默认 SQLite（本地开发/测试）。

```bash
cp .env.example .env
```

编辑 `.env`：`ADMIN_USERNAME`、`ADMIN_PASSWORD`（单管理员账号，缺失或为空时 API 拒绝启动）、`AI_PROVIDER`、`AI_MODEL`、`AI_API_KEY`、可选 `AI_BASE_URL`、`AI_REQUEST_TIMEOUT_SECONDS`、`DATABASE_URL`、`CHECKPOINT_DATABASE_URL`（生成运行检查点库，psycopg DSN）、`LANGGRAPH_AES_KEY`（16/24/32 字节，检查点加密密钥，缺失时生产生成拒绝落库）、`OPERATION_LEASE_SECONDS`、`OPERATION_MAX_ATTEMPTS`。`AI_PROVIDER=openai` 使用 OpenAI 或 OpenAI 兼容厂商（兼容端点通常把 `/v1` 放在 `AI_BASE_URL`）；`AI_PROVIDER=anthropic` 使用 Anthropic 或兼容 Messages API 的服务。本地 HTTP 开发需显式设置 `SESSION_COOKIE_SECURE=false`。不要把真实密钥提交到 Git。

安装依赖：

```bash
uv sync --project backend --dev   # 后端
make frontend-install             # 前端（cd frontend && pnpm install）
```

## 启动 API 与 Worker

首次启动先执行业务迁移和检查：

```bash
make db-migrate
make db-check
```

在第一次启动生产 Worker 前，用真实样本验证目标 Provider 的完整生成合同（受限工具、流式、结构化结果、引用可核查）：

```bash
SMOKE_CHECKPOINT_DSN=postgresql://...@127.0.0.1:5432/<隔离检查点库> make ai-smoke
```

成功标记为 `AI_SMOKE=OK ...`；冒烟使用 C1 真实会话样本（`.local-samples/m0`，只读）与隔离检查点库，指向项目库会被拒绝；没有真实密钥或语料时明确失败，不能用 Fake 结果或通用连通性检查冒充。

同一个业务数据库只允许一个长驻 Worker（进程锁保证）。`make start-all` 会同时启动 API、恰好一个 Worker 和前端三个进程，任一退出即清理其余进程；也可以分开单独启动调试：

```bash
make backend         # API，http://127.0.0.1:8000
make worker          # 单个生产 Worker
make frontend-dev    # 前端 dev，http://127.0.0.1:3000（BACKEND_URL 默认指向 8000）
```

成功标记：

- API 健康检查：<http://127.0.0.1:8000/healthz> 返回 `status=ok`、`persistence=business database`，`ai` 与当前 `AI_RUNTIME_MODE` 一致；
- 前端控制台：<http://127.0.0.1:3000>，未登录一律进入登录页，使用 `.env` 里的 `ADMIN_USERNAME`/`ADMIN_PASSWORD` 登录；
- OpenAPI 文档：<http://127.0.0.1:8000/api/docs>。

若 API 因 schema 未就绪退出，先运行 `make db-migrate` 和 `make db-check`。Fake 模式（`AI_RUNTIME_MODE=fake` 或 `--fake`）仅用于确定性测试，只允许连接 SQLite 业务库，不能用它做真实 AI 验收。

## 管理端（Next.js）

前端是单管理员桌面控制台（最低支持 1280px 宽）：

- **登录**：唯一管理员来自环境变量（启动时自动写入数据库），登录页用用户名 + 密码登录，无注册入口、无“忘记密码/记住我”；改密码 = 改 `.env` 并重启 API。
- **评测集**：彩色文件夹卡片，创建/改名/改描述/空集删除；连接状态（未签发/已签发待验证/已连接/已停用）由脱敏凭证派生。
- **上传凭证**：显式签发/轮换/撤销；签发或轮换后只显示一次包含本地服务地址与长期凭证的 Agent 绑定提示词，关闭即不可恢复。
- **题目审改**：紧凑列表（标题搜索/状态筛选/最近更新优先）+ 双栏工作台（左侧六类材料、右侧状态与维度）；AI 候选维度首次全未选，老师选择/修改/新增并保存后才能发布；已发布可重新打开审改；删除按状态门禁（曾发布题需输入完整标题）。

前端契约命令：

```bash
make frontend-typecheck    # tsc --noEmit
make frontend-test         # Vitest 单元/组件测试
make frontend-check-api    # OpenAPI 生成类型漂移检查
make frontend-generate-api # 后端合同变更后重新生成类型
make frontend-build        # 生产构建
make frontend-e2e          # Playwright（Chromium 完整 + WebKit 核心）
```

## 管理员 CLI（备用运维入口）

管理端的常规操作在 Web 控制台完成；以下命令作为备用运维入口，直接读写业务数据库。在 `backend/` 目录下运行（参数不经过 shell 插值）：

```bash
cd backend && uv run python -m scripts.admin_cli scenes create --name 媒体场景
cd backend && uv run python -m scripts.admin_cli scenes list
cd backend && uv run python -m scripts.admin_cli scenes status --scene-id <scene_id>
cd backend && uv run python -m scripts.admin_cli scenes update --scene-id <scene_id> --name 新名称 [--description ...]
cd backend && uv run python -m scripts.admin_cli scenes delete --scene-id <scene_id>
cd backend && uv run python -m scripts.admin_cli credentials issue --scene-id <scene_id> --label ci
cd backend && uv run python -m scripts.admin_cli credentials rotate --scene-id <scene_id>
cd backend && uv run python -m scripts.admin_cli credentials revoke --scene-id <scene_id> --credential-id <credential_id>
```

明文凭证 token 只在 `issue`/`rotate` 成功时显示一次，后续 `status`/`list` 查询绝不返回明文。

- `scenes update` 提交完整的目标元数据：省略 `--description` 表示清空描述；同名冲突返回错误。
- `scenes delete` 与 API 共用同一 Service：只有当前无题目的评测集可删除，删除会级联撤销其凭证；非空场景被拒绝。
- 管理员账号不在 CLI 管理：`ADMIN_USERNAME`/`ADMIN_PASSWORD` 是唯一权威，API 启动时自动应用（改密即改 env 并重启，旧密码与全部旧会话立即失效）。

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
- `DELETE /api/questions/{id}`：请求体 `{ "command_id", "content_revision", "confirmation_title"? }`，按 revision、删除冻结、生成中、已发布、曾发布标题确认的顺序门禁；返回 `202` 受理与清理 operation，完成以题目 404 为准；
- `GET /api/questions/{id}/runs/{operation_id}/events`：完整公开过程事件分页读取（`after_sequence` 游标）；
- `GET /api/questions/{id}/runs/{operation_id}/events/stream`：同源 SSE 实时订阅（读取持久化事件，不拥有/启动任务；断线只影响订阅）。
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

后端测试使用每次全新的临时 SQLite，覆盖批量收题原子性/幂等/隔离、完整评分项生成与编辑合同、删除冻结与受理、运行事件持久化与 SSE、发布与状态机、迁移（旧 head 升级 + fresh DB + downgrade）、OpenAPI 合同，以及多轮对抗审查后的安全/并发加固回归。运行基础另有两层：`tests/test_deep_runtime*.py`（受限装配/事件归一/预算 + 独占 PostgreSQL 库上的持久化/单写者/加密/恢复/清理）与 `tests/test_question_runtime_postgres.py`(业务链路在真实检查点上的崩溃恢复与跨库删除)；验收运行须带 `RUNTIME_PG_REQUIRED=1` 使 PostgreSQL 缺位直接失败而不是静默跳过。前端用 Vitest（纯函数/组件）与 Playwright（Chromium 完整 + WebKit 核心，含 1280x720 与 1440x900 视口）。

```bash
make test    # 后端 pytest + OpenAPI 漂移 + 前端 typecheck/单测/类型漂移
make build   # 后端编译/导入 + 前端生产构建
make frontend-e2e   # Playwright（自动拉起隔离后端 + fake worker）
```

`make contract-check` 校验已提交的 `backend/openapi.json` 与当前 FastAPI 合同一致；`make frontend-check-api` 校验前端生成类型与 `openapi.json` 一致。后端合同变更后先运行：

```bash
make openapi                 # 重新导出
make frontend-generate-api   # 重新生成前端类型
```

不要手改 `backend/openapi.json` 或 `frontend/src/lib/api/generated.ts`。

## 显式真实 AI 验收

两套真实 Provider 验收都只允许本地显式运行，都要求隔离 PostgreSQL 验收库（指向项目库 `blue_benchmark`/`blue_benchmark_checkpoint` 会被拒绝）、C1 真实样本（缺失即失败，不降级占位样例），均只输出阶段标记、计数和错误码，不输出材料正文、密码、Cookie、token、提示词全文或 raw model output：

- **API 级**（真实样本批量上传 → 生产 Worker + 真实 Deep Agent 生成 → 预算截断后从检查点恢复（不重复初始输入）→ 完整合同与引用核查 → 任意整数保存 → 发布 → 重开 → 受理式删除 → 双库零残留 + 兄弟题不受影响）：

  ```bash
  cd backend && ACCEPT_BUSINESS_DSN=... ACCEPT_CHECKPOINT_DSN=... \
    uv run python -m scripts.accept_real_ai_rubric   # 输出 ACCEPT_REAL_AI=PASS
  ```

- **Web 级**（隔离两库 + 单生产 Worker + 真实浏览器：env 账号登录 → 评测集 → 凭证提示词 → 上传真实 case → 生成中浏览器实时收到增量（反假流式断言）→ 完整合同/引用核查 → 依据面板与任意整数保存 → 发布 → 重开 → 受理式删除并以 404 为准导航 → 检查点零残留）：

  ```bash
  ACCEPT_BUSINESS_DSN=... ACCEPT_CHECKPOINT_DSN=... make accept-web    # 输出 M0_WEB_ACCEPTANCE=PASS
  ```

## 本地数据一次性重置（受控运维入口）

`backend/scripts/reset_local_data.py` 是本项目旧测试数据一次性切换的专用工具（C5 授权范围），**不是**日常维护命令：

- 目标白名单固定为本地 Docker PostgreSQL（127.0.0.1:5432）的 `blue_benchmark` 与 `blue_benchmark_checkpoint`；任何其他库名、远端主机、缺凭证 DSN 一律拒绝；
- 默认 dry-run：只输出脱敏计划（库名、掩码 DSN、逐表行数），不做任何修改；
- `--execute` 必须附 `--confirm-targets blue_benchmark,blue_benchmark_checkpoint` 精确确认；
- 执行前置：目标库存在第三方活动连接即拒绝（先停止本项目 API/Worker；工具不杀任何进程）；容器与 TCP 端点经 system_identifier 核验为同一实例；
- 破坏性语句之前先经容器 pg_dump 双库备份到非 Git 产物目录（默认 `<仓库上级目录>/blue-benchmark-wt/_artifacts/m0-rubric-anchors-evidence/c5/<UTC时间戳>/`），备份校验失败即中止；
- 重置只重建两库内的 public schema：不删实例/volume/角色/其他库，不改 `.env` 密钥，不触碰 `.local-samples`；
- 重置后自动执行 Alembic 到当前 head、准备加密 checkpointer 表，并核验空题库与 schema 就绪；失败时按备份与 Git 成套回退。

```bash
make reset-local            # dry-run 计划（安全默认）
cd backend && uv run python -m scripts.reset_local_data --execute \
  --confirm-targets blue_benchmark,blue_benchmark_checkpoint
```

该命令绝不接入 `make test`、应用启动或普通迁移；一次性授权不延伸至切换后新上传的数据。日常单题删除走产品内的受保护删除流程。

## 服务器部署

`deploy/` 目录包含单机 Docker Compose 生产部署的全部材料与手册：本地构建镜像推送到阿里云容器镜像服务（ACR），服务器拉取运行，全程服务器不接触源代码。三处存放分工：**ACR 存软件镜像、服务器运行程序并保存当前数据、OSS 存每日导出的备份文件**；服务器/OSS/Mac 三处备份副本各只保留最新成功的一套。

- `deploy/README.md` — 运维总入口：架构一页图、发版、回滚、备份与三处副本、Mac 每日下载、日常观察
- `deploy/acr-guide.md` — ACR 开通与镜像推送（初学者版）
- `deploy/oss-guide.md` — OSS 开通、最小权限、内网访问、费用与残留检查、恢复下载（初学者版）
- `deploy/server-setup.md` — 服务器初始化与首次空库部署（含安全组、swap、版本前置检查、首次备份）
- `deploy/restore.md` — 数据恢复手册（完整恢复点 `blue-benchmark-backup/v1`）与每月恢复演练
- `deploy/compose.yaml` / `deploy/nginx/nginx.conf` / `deploy/.env.production.example` — 编排、反向代理与环境变量模板
- `deploy/backup.sh` / `deploy/backup.py` — 每日备份 cron 薄入口与备份/校验/下载工具（Python 3.10+ 标准库）

发版入口：`REGISTRY=<ACR地址> deploy/push-images.sh`（质量门 + 跨架构构建 + 推送）；服务器端按完整 Compose 服务图更新（nginx 随 api/web 更新自动重启刷新上游地址）。每日 Mac 下载：`python3 deploy/backup.py download --host <SSH主机别名>`。

## 目录边界

- `backend/`：FastAPI 应用、迁移、脚本、测试。
- `frontend/`：Next.js 管理端（App Router + TypeScript + CSS Modules），类型由 `openapi.json` 生成；Vitest + Playwright 测试。
- `skills/ai-eval-push/`：题目上传 Skill（`SKILL.md` + 标准库客户端脚本 + API 合同 reference + 隔离测试）。
- `deploy/`：生产部署编排、发布/备份脚本与操作手册。

平台面向单管理员、恰好一个生产 Worker；生产部署为单机 Docker Compose + 裸 IP HTTP（域名与 HTTPS 为已规划的后续步骤），不含 Kubernetes、多实例扩容、CI/CD 自动发布与移动端。
