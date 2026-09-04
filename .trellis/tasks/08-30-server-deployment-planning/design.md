# 服务器部署设计

## 目标架构

单机 Docker Compose 部署，服务器上不放源代码，所有应用以镜像形式从阿里云容器镜像服务（ACR）拉取。

```
互联网用户（你）
    │
    ▼ 80 端口（安全组唯一放行的业务端口）
┌─────────────────────────────────────────────────┐
│  Nginx 反向代理                                  │
│  /api/* 与 /healthz → api:8000                  │
│  其余                → web:3000                  │
└─────────────────────────────────────────────────┘
    │
    ▼
┌──────────┐     ┌──────────┐     ┌──────────┐
│  web     │     │  api     │────▶│ postgres │
│ Next.js  │     │ FastAPI  │     │  5432    │
│ :3000    │     │ :8000    │     │（内网）   │
└──────────┘     └──────────┘     └──────────┘
                      │
                      ▼ 读写
                 ┌──────────┐
                 │ /app/    │  ← appdata 持久卷
                 │ storage/ │
                 └──────────┘
                      │
                      ▼ 异步
                 ┌──────────┐
                 │ worker   │  ← 与 api 共用镜像
                 │（单实例） │
                 └──────────┘
```

生产环境由 nginx 直接承担 `/api/*` 到后端的路由（开发环境才走 Next.js
rewrite），因此 web 镜像不需要任何后端地址配置，镜像与部署环境解耦。

## 容器清单

| 容器名 | 镜像 | 来源 | 端口 | 说明 |
|--------|------|------|------|------|
| nginx | `nginx:1.27-alpine` | 推送到 ACR | 80 | 反向代理，唯一对外端口 |
| web | `skill-eval-web:<tag>` | 本地构建 → ACR | 3000（内网） | Next.js standalone |
| api | `skill-eval-api:<tag>` | 本地构建 → ACR | 8000（内网） | FastAPI uvicorn |
| worker | `skill-eval-api:<tag>` | 与 api 同镜像 | 无 | `python -m app.lib.operations.worker` |
| postgres | `postgres:16-alpine` | 推送到 ACR | 5432（内网） | 业务数据库 |

安全组只开放 80（HTTP）和 22（SSH，建议限源）。

## 镜像构建策略

### web 镜像

多阶段构建，总大小约 150-200 MB：

1. **deps 阶段**：`node:20-alpine`，安装 pnpm，复制 lockfile，`pnpm install --frozen-lockfile`
2. **build 阶段**：复制源码，设 `NEXT_TELEMETRY_DISABLED=1`，执行 `pnpm build`。需要先修改 `frontend/next.config.mjs` 添加 `output: 'standalone'`。
3. **run 阶段**：基础镜像同样为 `node:24-alpine`（前端 `engines` 要求 Node ≥ 24，pnpm 11 亦不兼容 Node 20），从 build 阶段复制 `.next/standalone/`、`.next/static/`、`public/`。启动命令 `node server.js`。

`standalone` 模式会将所有依赖打包进一个自包含目录，运行时不需要 `node_modules`，镜像体积大幅缩小。

### api 镜像

多阶段构建，总大小约 200-300 MB：

1. **build 阶段**：`python:3.12-slim`，安装 uv，复制 `pyproject.toml` + `uv.lock`，`uv sync --frozen --no-dev`
2. **run 阶段**：`python:3.12-slim`，从 build 阶段复制虚拟环境和 `backend/` 源码。默认启动命令 `uvicorn app.main:app --host 0.0.0.0 --port 8000`

worker 容器使用同一镜像，只覆盖启动命令。

### 跨架构构建

你的 Mac 是 Apple Silicon（arm64），阿里云 ECS 是 amd64。构建时必须指定：

```bash
docker buildx build --platform linux/amd64 -t <registry>/skill-eval-api:<tag> --push backend/
```

`--push` 会在构建完成后直接推送到 ACR，不需要本地 `docker push`。

## 持久化设计

| 卷名 | 容器内路径 | 内容 |
|------|-----------|------|
| `pgdata` | `/var/lib/postgresql/data` | PostgreSQL 数据文件 |
| `appdata` | `/app/storage` | uploads、evidence、versions、staging、submissions |

Compose 使用命名卷（`volumes: pgdata` / `appdata`），Docker 自动管理，不需要手动指定宿主机路径。

`api` 和 `worker` 容器必须挂载同一个 `appdata` 卷，保证文件一致性。

## 环境变量

服务器上创建 `/opt/skill-eval/.env`，Compose 通过 `env_file` 读取（`REGISTRY`、`TAG`、`POSTGRES_*` 由 compose.yaml 插值使用）。内容与你本地 `.env` 等价：

```env
REGISTRY=registry-vpc.cn-beijing.aliyuncs.com/<命名空间>
TAG=<push-images.sh 输出的标签>
SESSION_COOKIE_SECURE=false
AI_RUNTIME_MODE=production
AI_PROVIDER=<你现有的值>
AI_MODEL=<你现有的值>
AI_API_KEY=<你现有的值>
AI_BASE_URL=<你现有的值>
AI_REQUEST_TIMEOUT_SECONDS=180
AI_MODEL_RETRIES=1
POSTGRES_USER=skill_eval
POSTGRES_PASSWORD=<强密码>
POSTGRES_DB=skill_eval
DATABASE_URL=postgresql+psycopg://skill_eval:<同一个强密码>@postgres:5432/skill_eval
DATABASE_SCHEMA_CHECK_ON_STARTUP=true
OPERATION_LEASE_SECONDS=60
OPERATION_MAX_ATTEMPTS=3
```

注意：
- `SESSION_COOKIE_SECURE=false`：HTTP 部署必须设为 false，否则 Cookie 无法写入，登录不可用
- `DATABASE_URL` 中的主机名是 `postgres`（Compose 服务名），不是 `127.0.0.1`
- web 容器不需要 `BACKEND_URL`：生产环境 `/api/*` 由 nginx 直接转发到后端

## 备份设计

### 策略

- 每日凌晨 3:00 自动备份（宿主机 cron）
- 备份内容：PostgreSQL 数据库 + 文件存储
- 备份目标：阿里云 OSS（异地存储，独立于服务器故障域）
- 恢复目标：最多丢失 24 小时数据，故障后允许停机数小时

### 备份脚本

`/opt/skill-eval/backup.sh`：

1. 使用 `docker compose exec postgres pg_dump` 导出数据库为 SQL 文件
2. 使用 `tar` 打包 `/var/lib/docker/volumes/skill-eval_appdata/_data/`（或 `docker run --rm -v skill-eval_appdata:/data alpine tar czf - -C /data .`）
3. 使用 `ossutil cp` 上传到 OSS 桶
4. 删除本地临时文件
5. 保留最近 7 天的本地备份（可选，用于快速恢复）

### 恢复验证

每月至少执行一次恢复验证：

1. 在本地或另一台机器上拉取 `postgres:16-alpine` 镜像
2. 启动临时容器，挂载备份的 SQL 文件
3. 执行 `psql -f backup.sql` 恢复数据库
4. 启动 api 容器指向恢复的数据库，验证健康检查通过
5. 验证文件备份可以解压且目录结构完整

## 发版与回滚

### 发版流程

```
本地：改代码 → 跑测试 → 构建并推送镜像（带新 tag）
服务器：docker compose pull → docker compose up -d
```

tag 策略：使用 `YYYYMMDD-<git短哈希>` 格式，例如 `20260904-a1b2c3d`。

### 回滚

修改 `compose.yaml` 中的镜像 tag 为上一个版本，然后：

```bash
docker compose pull && docker compose up -d
```

数据库迁移回滚：Alembic 不支持自动降级到任意版本。如果新版本包含破坏性迁移，回滚时需要从备份恢复数据库。

## 登录限流

首版不做应用内限流（需要改后端代码），通过 Nginx 配置基础防护：

```nginx
limit_req_zone $binary_remote_addr zone=login:10m rate=5r/m;

server {
    location /api/auth/login {
        limit_req zone=login burst=3 nodelay;
        proxy_pass http://web:3000;
    }
    # ...
}
```

这限制每个 IP 每分钟最多 5 次登录请求，超出返回 503。对正常用户无影响（谁一分钟登录 5 次以上？），但能有效阻止暴力撞库。

## 日志

所有容器日志由 Docker 收集，配置 `json-file` 驱动 + 日志轮转（`max-size: 10m`，`max-file: 3`），防止磁盘被日志撑满。

查看日志：

```bash
docker compose logs -f api
docker compose logs -f worker
docker compose logs --tail 100 nginx
```

## 健康检查

| 容器 | 健康检查 |
|------|---------|
| api | 容器内 python urllib 请求 `http://127.0.0.1:8000/healthz` |
| postgres | `pg_isready -U skill_eval -d skill_eval` |
| web | 容器内 node fetch `http://127.0.0.1:3000` |
| worker | 无 HTTP 端点，依赖 `restart: unless-stopped` |

Compose 中配置 `healthcheck` + `depends_on: condition: service_healthy`，确保启动顺序正确。后端健康端点为 `/healthz`（不在 `/api` 前缀下），nginx 同时暴露该路径便于外部探活。

数据库结构变更不随容器启动自动执行：首次部署和含迁移的发版必须先运行
`docker compose run --rm api alembic upgrade head`，api 容器的启动时
schema 检查会阻止在未迁移的库上启动（已验证该失败路径）。

## 2 GiB 内存约束

- 不在服务器上构建镜像（全部在本地构建后推送）
- 配置 2 GiB swap 兜底：`fallocate -l 2G /swapfile`
- Compose 中设置内存限制：`deploy.resources.limits.memory`
- 监控内存使用：`docker stats` 或 `free -h`

如果频繁 OOM，升级服务器到 4 GiB（控制台变更规格 → 重启，不需要改部署结构）。

## 服务器初始化

1. 创建 `/opt/skill-eval/` 目录
2. 上传 `compose.yaml`、`nginx.conf`、`.env`、`backup.sh`
3. 配置 swap
4. 安装 `ossutil`（阿里云 OSS 命令行工具）
5. 配置 cron 定时备份
6. 登录 ACR：`docker login <registry>`
7. 拉取镜像并启动

## 与域名的衔接

当前设计为 HTTP + 公网 IP。后续配置域名时：

1. 域名解析到服务器公网 IP
2. 申请 Let's Encrypt 证书（需要域名，裸 IP 不行）
3. Nginx 添加 443 监听 + SSL 配置
4. `.env` 中 `SESSION_COOKIE_SECURE=true`
5. 80 端口重定向到 443

不需要改应用代码或重新构建镜像，只改 Nginx 配置和环境变量。
