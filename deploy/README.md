# 部署运维手册

本目录包含 Skill Eval Platform 的单机生产部署全部材料。
首次部署请按顺序阅读：

1. `acr-guide.md` — ACR 是什么、怎么开通和推送镜像（先读，在 Mac 上完成）
2. `server-setup.md` — 服务器初始化和首次部署（在服务器上完成）
3. 本文档 — 日常发版、回滚和观察
4. `restore.md` — 出大事时的数据恢复（平时不用看，但要存在）

## 架构一页图

```
浏览器 → 服务器:80(nginx)
            ├─ /api/* → FastAPI(api) ── PostgreSQL(postgres)
            ├─ /healthz → FastAPI
            └─ 其他 → Next.js(web)
         Worker(worker，与 api 同镜像) 轮询数据库执行真实 AI 任务
         文件存储：appdata 卷（/app/storage）
```

只有 80 端口对外；数据库和其他服务都在 Docker 内部网络。

## 发版（每次代码更新后）

在你的 Mac 上，仓库根目录执行：

```bash
# 1) 质量门 + 构建 + 推送（约 5-10 分钟，取决于上行带宽）
REGISTRY=registry.cn-beijing.aliyuncs.com/skill-eval deploy/push-images.sh
```

脚本最后会输出镜像标签（形如 `20260904-a1b2c3d`）和服务器端命令。
到服务器上执行：

```bash
cd /opt/skill-eval
# 2) 更新 .env 里的 TAG 为新标签
vi .env
# 3) 如果本次发版包含数据库迁移，先迁移（不放心可先备份）
docker compose run --rm api alembic upgrade head
# 4) 拉新镜像并滚动重启
docker compose pull
docker compose up -d
# 5) 确认状态
docker compose ps
```

验收：浏览器登录验证页面正常 + `docker compose logs worker --tail 20` 无报错。

## 回滚

发现问题时，把 `.env` 里的 `TAG` 改回上一个标签，然后：

```bash
cd /opt/skill-eval
docker compose pull
docker compose up -d
```

注意事项：

- 只改代码的回滚：上面两条命令即可，数据不受影响
- 如果新版本跑过**数据库迁移**且旧版本不兼容新结构：回滚代码的同时
  必须按 `restore.md` 恢复发版前的数据库备份。所以发版前先手动备份：
  `bash /opt/skill-eval/backup.sh`

## 日常观察

```bash
cd /opt/skill-eval

docker compose ps                    # 各服务状态（healthy/Up）
docker compose logs -f worker        # 实时看 AI 任务日志
docker compose logs --tail 100 api   # 后端最近日志
docker compose logs --tail 100 nginx # 访问日志（谁在访问、什么路径）
docker stats --no-stream             # 各容器 CPU/内存占用
free -h                              # 系统内存与 swap 使用情况
df -h /                              # 磁盘（日志/备份副本会缓慢增长）
tail -20 /opt/skill-eval/backup.log  # 最近备份是否成功
```

判断 2 GiB 内存是否吃紧：`free -h` 中 swap 使用量持续大于几百 MB，
或 `docker stats` 里某容器内存接近其日常峰值两倍，就去控制台把实例
升级到 4 GiB（变更规格 → 重启即可，部署结构不用动）。

## 重启服务器之后

Docker 容器配置了 `restart: unless-stopped`，服务器重启后会自动拉起，
无需人工干预。重启完成后执行一次 `docker compose ps` 确认全部健康即可。

## 安全底线（当前版本已具备）

- 数据库端口不对公网开放，只存在于 Docker 内部网络
- `.env`（含 AI 密钥和数据库密码）权限 600，只在服务器上
- 登录接口限流：每个 IP 每分钟最多 5 次 + 3 次突发（nginx 配置）
- 应用容器以非 root 用户运行
- 日志轮转：单文件 10 MB、最多 3 份，防止磁盘写满

## 已知未解决项（域名到位后处理）

- 传输为 HTTP 明文：登录密码和会话 Cookie 不加密。拿到域名后：
  DNS 指向公网 IP → 用支持 `shortlived` 配置的 ACME 客户端或先解析后
  正常申请 Let's Encrypt 证书 → nginx 加 443 与证书 → `.env` 中
  `SESSION_COOKIE_SECURE=true` → 80 重定向 443。不需要重新构建镜像。
- 无登录失败锁定和告警通知：当前靠限流兜底；若日志中出现大量 401，
  考虑在 nginx 层加黑名单或升级应用内防护。
