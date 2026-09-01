# Skill Eval Platform

这是 M0 评测集工作台：业务老师从真实资料开始，在可恢复的建题会话里确认题目输入、标准答案和可选坏样本，再形成 100 分制评分规则；发布会自动进入当前评测集并留下不可变历史，之后可停用、恢复、删除和人工评分。

当前源码边界：业务事实保存在 SQLAlchemy/Alembic 业务数据库，上传文件保存在服务端文件存储，后台操作由单消费者 Worker 处理。常驻 Worker 默认使用真实 AI；自动化测试和显式 `AI_RUNTIME_MODE=fake` 才使用确定性的 Fake。M2 的 Skill/Agent 执行、评测运行和报告不在当前实现内。

## 本地准备

需要 Python 3.12–3.13、uv、Node.js、pnpm 和 PostgreSQL（真实本地运行）。

```bash
cp .env.example .env
```

编辑 `.env` 中的 `AI_PROVIDER`、`AI_MODEL`、`AI_API_KEY`、可选的 `AI_BASE_URL`、`AI_REQUEST_TIMEOUT_SECONDS`、`AI_MAX_COCREATION_QUESTIONS`、`DATABASE_URL`、`CHECKPOINT_DATABASE_URL` 和 `LANGGRAPH_AES_KEY`。`AI_PROVIDER=openai` 使用 OpenAI 或 OpenAI 兼容厂商（兼容端点通常把 `/v1` 放在 `AI_BASE_URL`），`AI_PROVIDER=anthropic` 使用 Anthropic 或兼容 Messages API 的服务（Anthropic SDK 会在自定义 Base URL 后请求 `/v1/messages`）；不要同时依赖 Key 自动猜测。`AI_REQUEST_TIMEOUT_SECONDS` 为每次模型请求设置有限 deadline；Worker 会在长处理期间续租，但每次请求仍必须有上限。`AI_MAX_COCREATION_QUESTIONS` 限制单次共创的老师提问轮数，达到上限后使用同一 AI Profile 的完成式结构化候选并把未知项列为阻塞缺口，不能无限追问。Checkpointer 数据库必须和业务数据库分开，URL 使用 psycopg 可连接的 PostgreSQL scheme，密钥必须是 16、24 或 32 字节；不要把真实密钥提交到 Git。`STORAGE_ROOT=./storage` 会相对于仓库根目录解析，API 和 Worker 可以从不同工作目录启动而继续使用同一存储。

安装依赖：

```bash
uv sync --project backend --dev
pnpm --dir frontend install --frozen-lockfile
```

## 启动 API、Worker 和前端

首次启动先执行业务迁移和检查：

```bash
make db-migrate
make db-check
```

生产 Worker 要求真实模型配置和独立 Checkpointer。先确认 `.env` 已配置，再执行一次显式 schema setup：

```bash
make checkpoint-setup
```

在第一次启动 Worker 前，建议用合成输入验证目标 Provider 的工具调用和结构化输出：

```bash
make ai-smoke
```

成功标记为 `AI_PROVIDER_SMOKE=PASS ...`。该命令会产生一次模型调用；没有真实密钥时应先补齐配置，不能把 Fake 结果当作真实 AI 验收。

分别打开三个终端：

```bash
make backend
```

```bash
make worker
```

```bash
make frontend
```

同一个业务数据库只允许一个长驻 Worker。`make start-all` 已经会启动一个 Worker，不要再在其他终端执行 `make worker` 或用另一种 `AI_RUNTIME_MODE` 启动第二个消费者；Worker 会在领取任务前取得数据库级互斥锁。环境变量优先级高于 `.env`，因此显式设置过 `AI_RUNTIME_MODE=fake` 的旧终端仍会使用 Fake，即使 `.env` 写的是 `production`。切换模式前先确认只有一个 Worker 进程，并停止旧进程。

成功标记：

- API 健康检查：<http://127.0.0.1:8000/healthz> 返回 `status=ok`、`persistence=business database`，且 `ai` 与当前 `AI_RUNTIME_MODE` 一致；
- OpenAPI：<http://127.0.0.1:8000/api/docs>；
- 前端：<http://localhost:3000/login>；
- 前端只请求同源 `/api/*`，Next.js Rewrite 转发到 `BACKEND_URL`；
- Worker 终端在有任务时逐个处理，空闲时持续等待，不要再启动第二个消费者；它会在配置、Checkpointer 连接或 schema 未就绪时于领取任务前退出。

若 API 进程因 schema 未就绪退出，先运行 `make db-migrate` 和 `make db-check`。若 Worker 报 Checkpointer schema 未就绪，先运行 `make checkpoint-setup`。若页面一直显示“等待后台处理”，检查 Worker 是否连接了同一个 `DATABASE_URL` 和 `STORAGE_ROOT`；端口能打开或返回 HTTP 200 不能代替这项检查。仅用于显式本地演示时，可设置 `AI_RUNTIME_MODE=fake` 或运行 `cd backend && uv run python -m app.lib.operations.worker --fake`；Fake Worker 只允许连接 SQLite 业务库，不要用该模式做真实 AI 验收。

## 合同与自动化验证

后端测试使用每次全新的临时 SQLite 和临时存储，默认不读取 `.local-samples/`，包含合成多文件/ZIP、长 JSONL 尾部读取、题目生命周期、多次 attempts、共创恢复、自动版本形成、三分区隔离和历史完整性检查。

```bash
make test
make build
```

`make test` 还会检查已提交的 `backend/openapi.json` 和 `frontend/src/lib/api/generated.ts` 是否仍由当前 FastAPI 合同生成。后端合同变更后先运行：

```bash
make openapi
```

不要手改生成文件。

## 第一阶段：建题会话

当前已实现的第一阶段入口是：

- `/workspaces/{workspace_id}/authoring/new`：绑定上传批次或直接手动输入；
- `/workspaces/{workspace_id}/authoring/{conversation_id}`：正文式会话记录、候选题轨、边界确认、资料角色、题目输入和标准答案确认。

会话的公开快照来自 FastAPI，安全事件通过有限 SSE 窗口增量读取；SSE 断线不会取消后台 Worker，刷新后仍以 GET 快照恢复。AI 候选不会自动成为标准答案，未经过老师确认的题目不能进入规则阶段。旧题稿路径只做重定向，不再维护第二套编辑器。

前端真实 AI 浏览器验收是显式命令，默认不会在 CI 中运行：

```bash
E2E_REAL_AI=1 \
E2E_TIMEOUT_MS=1800000 \
PLAYWRIGHT_CHROMIUM_PATH="/path/to/chromium" \
pnpm --dir frontend test:e2e:authoring
```

用例只读取调用者指定的 `/Users/hsikey/BenchMark/EvalData` 三个文件，输出阶段断言，不打印资料正文；它要求 API、单个生产 Worker 和前端已分别启动。题目边界确认后，每道题通过独立的题级 Agent 追问和 checkpoint 恢复，标准答案仍必须由老师显式提供或认可。

## 显式真实样本验收

真实资料只允许本地显式运行，不进入 Git、默认 CI 或日志。准备好用户确认的三份文件后，可用 Fake/SQLite 做确定性边界验收：

```bash
cd backend && uv run python scripts/accept_real_samples.py --samples-dir /Users/hsikey/BenchMark/EvalData
```

成功输出应包含 `M0_REAL_SAMPLE_ACCEPTANCE=PASS`。runner 使用临时数据库、临时存储和 Fake adapter，只验证资料边界和业务合同，不代表真实模型已经执行；真实模型证据见下方 Provider/浏览器 E2E。它只输出阶段标记、任务数和 attempts 数，不输出样本原文、老师回答、凭证、内部 thread/checkpoint 或实际哈希。若失败，按 `stage=...` 检查样本目录是否恰好包含一份 JSONL、一份 ZIP 和一份 Markdown，以及 API/Worker 的本地依赖是否可用。

## 第二阶段：评分规则与题目发布

题目输入、标准答案和坏样本确认后，单一动作“确认题目并生成打分规则”进入 `/workspaces/{workspace_id}/authoring/{conversation_id}/rubric`。页面以逐项正文方式审阅规则：每项显示满分、给分点、扣分点、关键项、标准答案期望得分和理由；满分合计必须为 100，标准答案必须过总分线并通过关键项。唯一高后果动作是“确认规则并发布到评测集”。

发布会创建不可变 `BenchmarkQuestionRevision`，自动更新当前评测集并产生 `m0-evaluation-package-v2` 历史版本；`runtime.json` 不含标准答案、坏样本、rubric、通过线或形成记录。版本页只读历史，不再操作下一版、组集或手动版本形成。

## 第三阶段：待评答卷与人工评分

发布后的题目修订可从版本工作台或规则发布页进入：

- `/workspaces/{workspace_id}/question-revisions/{question_revision_id}/submissions/new`：粘贴一份文本，或上传单个 UTF-8 `.md` / `.txt` 文件，大小不超过 1 MiB；
- `/workspaces/{workspace_id}/submissions/{submission_id}`：阅读这一份独立答卷，按发布快照逐项填写分数、关键项判定和必要理由。

答卷只绑定一条已发布题目修订。评分不调用 AI，服务端从不可变 rubric 重新计算总分、关键项和通过结果；提交后评分不可覆盖，重新评分会新增 parent-linked 历史。答卷正文只在当前账号的授权详情接口返回，不能进入日志、Worker 运行元数据或版本包。

## 浏览器人工验收路径

真实浏览器路径必须使用运行中的 API、单个 Worker 和前端，不以 Preview、静态截图、文档或 HTTP 200 作为闭环证据：

1. 在 `/login` 注册内部业务账号，进入 `/workspaces` 创建一个私有场景。
2. 上传 JSONL、ZIP 和 Markdown 三份 EvalData 文件，等待 Worker 完成资料整理。
3. 进入建题会话，选择题目边界，确认资料角色、任务要求、标准答案和可选坏样本。
4. 点击“确认题目并生成打分规则”，在规则页逐项审阅后点击“确认规则并发布到评测集”。
5. 回到“题”确认题目显示“已发布”，回到“版本”确认自动历史版本可读、可下载且 runtime 隔离。
6. 修改已发布题目时先派生下一修订；停用、恢复、删除都自动形成历史版本，停用/删除后新待评结果与评分写入被拒绝，但既有历史仍可读。
7. 从已发布题目进入人工评分，使用本地 Markdown 答卷；提交、刷新、同修订重评和同题跨修订重评，检查 390px 窄屏、键盘焦点、硬失败判定和无横向溢出。

当前 M0 只验收主观型文案/新闻稿场景。通过当前回归集不等于 Skill 已全面可靠；覆盖风险和样本边界必须随自动历史版本保留。

### 真实 Provider 与 PostgreSQL E2E

先完成业务迁移、独立 Checkpointer setup 和 `make ai-smoke`，再启动一个 API、一个真实 Worker 和前端。真实验收 runner 必须显式指定已批准的样本目录；例如本机评测集：

```bash
cd backend && uv run python scripts/accept_real_ai_e2e.py \
  --samples-dir /Users/hsikey/BenchMark/EvalData \
  --base-url http://127.0.0.1:8000
```

runner 只输出阶段标记、计数和错误类型，不输出样本正文、模型回答、凭证或内部 Checkpoint。`AI_REQUEST_TIMEOUT_SECONDS` 默认 180 秒，真实成本边界测试可显式设置 `AI_MAX_COCREATION_QUESTIONS=1`，并保持单 Worker。完成式 fallback 仍需要老师确认，不能把模型建议直接当作业务标准。
该 runner 会核验本轮 batch、建题会话和 rubric OperationJob 的内部 Worker 运行标记均为 `production`，并串联发布即入集、停用、恢复、删除和历史读写门禁；如果误用 `--fake` Worker，不能得到真实验收通过。
