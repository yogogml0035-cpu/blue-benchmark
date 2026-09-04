# 实施计划

本计划分两个阶段：

- **阶段 A：仓库修改**——在本仓库新增部署文件（在任务 worktree 内完成，遵守 worktree 闭环规则）。
- **阶段 B：服务器部署**——在阿里云服务器上执行的操作（不属于仓库变更，按操作手册逐步执行）。

## 阶段 A：仓库修改清单（按顺序执行）

### A1. 前端开启 standalone 输出

- 修改 `frontend/next.config.mjs`：在 `nextConfig` 中添加 `output: "standalone"`。
- 验证：`cd frontend && pnpm build`，确认生成 `frontend/.next/standalone/` 目录，其中包含可独立运行的 `server.js`。
- 风险：standalone 输出不包含 `public/` 与 `.next/static/`，Dockerfile 必须显式复制这两部分，否则静态资源 404。

### A2. 新增前端 Dockerfile

- 新增 `frontend/Dockerfile`，三阶段构建（deps → build → run），基础镜像 `node:20-alpine`，构建参数固定 `NEXT_TELEMETRY_DISABLED=1`，run 阶段暴露 3000，入口 `node server.js`。
- 新增 `frontend/.dockerignore`：排除 `node_modules`、`.next`、`test-results`、`e2e`。
- 验证：本地 `docker buildx build --platform linux/amd64 -t skill-eval-web:test frontend/` 构建成功；`docker run --rm -p 3000:3000 -e BACKEND_URL=http://host.docker.internal:8000 skill-eval-web:test` 后 `curl http://127.0.0.1:3000` 返回登录页。

### A3. 新增后端 Dockerfile

- 新增 `backend/Dockerfile`，两阶段构建（uv sync → run），基础镜像 `python:3.12-slim`，run 阶段携带 `app/`、`migrations/`、`scripts/`、`alembic.ini`，默认入口 `uvicorn app.main:app --host 0.0.0.0 --port 8000`。
- 新增 `backend/.dockerignore`：排除 `storage/`、`__pycache__`、`.venv`、`tests/`。
- 注意：`storage/` 不进镜像，运行时由卷挂载提供。
- 验证：本地构建成功；配合本地 Postgres 容器启动后 `/api/health` 返回 200。

### A4. 新增部署编排目录 `deploy/`

- `deploy/compose.yaml`：定义 nginx、web、api、worker、postgres 五个服务；命名卷 `pgdata`、`appdata`；`env_file: .env`；日志轮转（json-file，10m×3）；postgres 与 api 配置 healthcheck；worker 与 api 共用镜像、不同入口；仅 nginx 映射 80 端口，其余服务只暴露到内部网络。
- `deploy/nginx/nginx.conf`：`/api/` 与 `/` 全部转发到 `web:3000`（浏览器只与 Next.js 同源，复用现有 rewrite）；登录路径 `limit_req` 限流（5r/m，burst=3）；`client_max_body_size` 按上传需求设置（建议 ≥ 200m，以现有上传大小上限为准，实施时从后端代码确认）。
- `deploy/.env.production.example`：生产环境变量模板（不含任何真实密钥），字段与 `design.md` 环境变量一节一致；`SESSION_COOKIE_SECURE=false`、`BACKEND_URL=http://api:8000`、`DATABASE_URL` 主机名为 `postgres`。
- 验证：在本地用测试 `.env` 执行 `docker compose -f deploy/compose.yaml config` 通过；`docker compose up` 后完整业务路径可用（注册管理员 → 登录 → 创建场景 → 触发一次真实 AI 任务并看到结果）。

### A5. 新增本地发布脚本

- 新增 `deploy/push-images.sh`：读取 git 短哈希生成镜像 tag（`YYYYMMDD-<hash>`），用 `docker buildx build --platform linux/amd64 --push` 构建并推送 web 与 api 两个镜像到 ACR 仓库（registry 地址从脚本变量或环境变量读取）；推送前要求工作区通过 `make test`（脚本内先执行，失败即中止）。
- 验证：脚本在本地执行一次，ACR 控制台可见新 tag。

### A6. 新增服务器端脚本与手册

- 新增 `deploy/backup.sh`：pg_dump 业务库 + 打包文件卷 + `ossutil` 上传 OSS + 清理本地临时文件；保留最近 7 份本地备份。
- 新增 `deploy/restore.md`：恢复操作手册（恢复数据库、恢复文件卷、重新拉起服务、验证业务路径），并包含每月恢复验证步骤。
- 新增 `deploy/acr-guide.md`：面向初学者的 ACR 完整说明——开通个人版、创建命名空间和镜像仓库、设置固定密码、本地 `docker login`、推送与拉取、服务器端 `docker login` 与免密拉取配置（凭据助手或 root 权限下保存凭据的风险说明）。
- 新增 `deploy/server-setup.md`：服务器初始化手册——安全组规则（80 开放、22 限源、Postgres 端口不开）、创建 `/opt/skill-eval/`、配置 2G swap、安装 ossutil、配置每日 03:00 备份 cron、首次 `docker compose pull && up -d`。
- 新增 `deploy/README.md`：发版与回滚手册——本地发版流程（测试 → push-images → 服务器 pull+up）、回滚流程（改 tag → pull+up）、日志查看、`docker stats` 内存观察、升级到 4 GiB 的说明。

### A7. 文档与收尾

- 更新根 `README.md`：新增"服务器部署"小节，指向 `deploy/README.md`。
- 按 AGENTS.md 完成门禁执行定向检索与质量门：`git diff --check`、`make test`、`make build`。

## 阶段 B：服务器部署步骤（操作手册摘要，详见 deploy/ 下各文档）

### B1. ACR 准备（本地浏览器操作）

1. 开通容器镜像服务个人版（免费），创建命名空间与两个镜像仓库（web、api）。
2. 设置访问凭证，本地 `docker login` 验证推送权限。
3. 另外将 `nginx:1.27-alpine` 与 `postgres:16-alpine` 拉取后重新打 tag 推入 ACR（一次性操作，让服务器只依赖 ACR，绕开不稳定的 Docker Hub）。

### B2. 服务器初始化

1. SSH 登录，确认 `uname -m` 为 `x86_64`、Docker 可用、磁盘剩余 ≥ 30 GiB。
2. 安全组：入方向仅放行 80（0.0.0.0/0）与 22（建议限源）；确认 5432、8000、3000 均未开放。
3. 创建 `/opt/skill-eval/`，上传 `compose.yaml`、`nginx.conf`、`backup.sh`，创建 `.env`（按模板填真实值，`chmod 600`）。
4. 配置 2G swap；安装并配置 ossutil（AK 仅授予目标 OSS 桶的读写权限）。
5. `docker login` ACR；注册每日备份 cron。

### B3. 首次部署

1. `docker compose pull && docker compose up -d`。
2. 等待 healthcheck 通过：`docker compose ps` 全绿。
3. 注册管理员账号（首个注册者成为唯一管理员）。

### B4. 上线验收（必须全部走真实路径）

1. `make ai-smoke` 的服务器等价命令在 api 容器内执行，确认真实 Provider 可达。
2. 完整业务路径：登录 → 创建/进入一个场景 → 提交一个会触发 Worker 的任务 → 观察 Worker 日志中的真实 AI 调用 → 前端看到真实模型产出。
3. 模拟进程重启：`docker compose restart worker`，确认未完成任务按现有恢复语义继续。
4. 备份验收：手动触发 `backup.sh`，确认 OSS 中出现备份对象；按 `restore.md` 在临时环境完成一次恢复演练。
5. 失败即回滚或修复，不以"容器起来了"作为验收结论。

### B5. 后续每次发版

1. 本地：改代码 → `make test` 通过 → `deploy/push-images.sh`。
2. 服务器：更新 `compose.yaml` 中两个镜像 tag → `docker compose pull && docker compose up -d` → 复验 B4 第 2 步。
3. 出问题：tag 改回上一版本，重复第 2 步；涉及迁移损坏时按 `restore.md` 恢复。

## 风险点与回滚点

| 风险 | 缓解 | 回滚点 |
|------|------|--------|
| standalone 输出缺失静态资源 | A2 验证步骤覆盖 | 移除 `output: "standalone"` 即回到原状 |
| 跨架构构建缓慢或失败 | buildx 已确认支持；失败时改用本地原生构建冒烟、推送仍走 amd64 | 不影响仓库现状 |
| 2 GiB 内存 OOM | swap 兜底 + 不在服务器构建 + `docker stats` 观察 | 控制台升级 4 GiB，部署结构不变 |
| AI 费用失控 | 密钥仅存于服务器 `.env`（600 权限）；日志不打印密钥 | 轮换密钥并更新 `.env` |
| 迁移破坏导致回滚失败 | 发版前自动每日备份 + 手动备份 | `restore.md` 恢复流程 |
| HTTP 明文（已知接受的风险） | 登录限流 + 域名到位后启用 HTTPS | 域名 + 证书后 `SESSION_COOKIE_SECURE=true` |

## 实施前检查

- 创建任务分支与专属 worktree（`codex/server-deployment`），复制 `.env` 到 worktree。
- 确认 `frontend/package.json` 的 Node 版本要求与 `node:20-alpine` 兼容（Next.js 16 要求 Node ≥ 20，满足）。
- 确认后端 `pyproject.toml` 的 Python 版本与 `python:3.12-slim` 一致（实施时核对 `requires-python`）。
- 从后端代码确认上传大小上限，回填 `client_max_body_size`。
