# Skill Eval Platform

这是 M0 评测集工作台：业务老师从真实资料开始，确认任务分组，逐轮形成场景标准和单题判定依据，把选中的题加入唯一下一版草稿，最后冻结为可回查的不可变版本包。

当前源码边界：业务事实保存在 SQLAlchemy/Alembic 业务数据库，上传文件保存在服务端文件存储，后台操作由单消费者 Worker 处理；默认 AI adapter 是确定性的 Fake，真实 provider smoke 和生产 Checkpointer 需要单独配置与验证。M2 的 Skill/Agent 执行、评测运行和报告不在当前实现内。

## 本地准备

需要 Python 3.12–3.13、uv、Node.js、pnpm 和 PostgreSQL（真实本地运行）。

```bash
cp .env.example .env
```

编辑 `.env` 中的 `DATABASE_URL`、`CHECKPOINT_DATABASE_URL` 和 `LANGGRAPH_AES_KEY`。Checkpointer 数据库必须和业务数据库分开，密钥必须是 16、24 或 32 字节；不要把真实密钥提交到 Git。`STORAGE_ROOT=./storage` 会相对于仓库根目录解析，API 和 Worker 可以从不同工作目录启动而继续使用同一存储。

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

如果要启用生产 Checkpointer，先确认 `.env` 已配置独立数据库和密钥，再执行一次显式 schema setup：

```bash
make checkpoint-setup
```

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

成功标记：

- API 健康检查：<http://127.0.0.1:8000/healthz> 返回 `status=ok`，且 `persistence=business database`；
- OpenAPI：<http://127.0.0.1:8000/api/docs>；
- 前端：<http://localhost:3000/login>；
- 前端只请求同源 `/api/*`，Next.js Rewrite 转发到 `BACKEND_URL`；
- Worker 终端在有任务时逐个处理，空闲时持续等待，不要再启动第二个消费者。

若 API 进程因 schema 未就绪退出，先运行 `make db-migrate` 和 `make db-check`。若页面一直显示“等待后台处理”，检查 Worker 是否连接了同一个 `DATABASE_URL` 和 `STORAGE_ROOT`；端口能打开或返回 HTTP 200 不能代替这项检查。

## 合同与自动化验证

后端测试使用临时 SQLite 和临时存储，默认不读取 `.local-samples/`，包含合成多文件/ZIP、长 JSONL 尾部读取、两任务分组、多次 attempts、共创恢复、版本冻结、三分区隔离和历史完整性检查。

```bash
make test
make build
```

`make test` 还会检查已提交的 `backend/openapi.json` 和 `frontend/src/lib/api/generated.ts` 是否仍由当前 FastAPI 合同生成。后端合同变更后先运行：

```bash
make openapi
```

不要手改生成文件。

## 显式真实样本验收

真实资料只允许本地显式运行，不进入 Git、默认 CI 或日志。准备好用户确认的三份文件后运行：

```bash
cd backend && uv run python scripts/accept_real_samples.py --samples-dir ../.local-samples/m0
```

成功输出应包含 `M0_REAL_SAMPLE_ACCEPTANCE=PASS`。runner 使用临时数据库、临时存储和 Fake adapter，只输出阶段标记、任务数和 attempts 数，不输出样本原文、老师回答、凭证、内部 thread/checkpoint 或实际哈希。若失败，按 `stage=...` 检查样本目录是否恰好包含一份 JSONL、一份 ZIP 和一份 Markdown，以及 API/Worker 的本地依赖是否可用。

## 浏览器人工验收路径

真实浏览器路径必须使用运行中的 API、单个 Worker 和前端，不以 Preview、静态截图、文档或 HTTP 200 作为闭环证据：

1. 在 `/login` 注册内部业务账号，进入 `/workspaces` 创建一个私有场景。
2. 上传一批完整材料：JSONL 事件流、包含三份 Markdown 的 ZIP，以及 Markdown Brief。等 Worker 完成资料整理。
3. 在“当前”确认每份资料的角色和可见范围：Brief/运行材料进入“给 Skill 的材料”，事件流/对话记录进入“形成记录”。
4. 在“题”检查 AI 分组；用“新增任务”和每份资料的“归属任务”下拉框把两组真实材料拆成两个任务，必要时用“合并到其他任务”，再确认分组。
5. 打开第一道题。若场景标准尚未确认，题页会先进行“场景标准共创”；每轮只回答一个问题，确认标准后自动进入“题稿共创”。刷新页面，确认已提交的回答仍在。
6. 两道题分别完成单题判定依据共创并定稿。完成后在“版本”创建下一版草稿，把两道题加入，运行覆盖审查；有风险时必须填写说明并明确确认。
7. 冻结版本后打开历史版本详情并下载完整包。解包确认只有 `manifest.json`、`runtime.json`、`judge.json`、`provenance.json`；检查 Manifest、三个分区 hash 和下载响应头一致，`runtime` 不含参考结果、评分规则、attempts、老师判断或形成记录。
8. 在资料整理、等待回答、回答已保存但 Worker 尚未恢复、冻结排队时刷新或关闭重开页面；确认状态只由服务端快照恢复，重复点击不会产生第二个任务、回答或版本。
9. 删除已完成共创的 Checkpoint thread 后回查题、场景标准、形成记录和版本包；活动中的待答会话不能被清理流程误删。另用第二个账号访问第一个账号的场景、题和版本，必须得到 `403` 且不渲染私有内容。

当前 M0 只验收主观型文案/新闻稿场景。通过当前回归集不等于 Skill 已全面可靠；覆盖风险和样本边界必须随冻结版本保留。
