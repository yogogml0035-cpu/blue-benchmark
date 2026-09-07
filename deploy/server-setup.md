# 服务器初始化与首次部署手册

从零到站点可访问的完整步骤。所有命令都在服务器上执行（SSH 登录后），
标注"浏览器"的步骤在阿里云控制台网页上操作。

预计耗时：1-2 小时（含等待镜像拉取）。

## 0. 前置准备（开始前确认）

- [ ] 已完成 `deploy/acr-guide.md` 第一至第四步（ACR 开通、仓库创建、Mac 已登录、基础镜像已转存）
- [ ] 已按 `deploy/oss-guide.md` 第一至第五步准备好备份 Bucket、最小权限
      AccessKey 和 `.env` 的 OSS 三项配置（没有就先创建，区域与服务器同地域、私有、不开版本控制）
- [ ] 本地已用 `deploy/push-images.sh` 推送过至少一个版本的 `skill-eval-web` 和 `skill-eval-api`
- [ ] 记下服务器的公网 IP（控制台 → 云服务器 ECS → 实例）

## 1. 安全组（浏览器）

控制台 → ECS → 实例 → 安全组 → 配置规则 → 入方向，确保只有这些放行规则：

| 端口 | 授权对象 | 用途 |
|------|---------|------|
| 22 | 你的常用出口 IP/32（推荐）或 0.0.0.0/0 | SSH |
| 80 | 0.0.0.0/0 | 站点访问 |

**确认 5432（数据库）、8000、3000 都没有放行**。数据库绝不能暴露公网。

## 2. 登录服务器并检查环境

```bash
ssh root@你的公网IP

# 逐项确认
uname -m                    # 必须输出 x86_64
docker version | head -3    # 有版本输出即可
docker compose version      # 必须 v2.20+（nginx 依赖重启与备份工具的支持基线）
python3 --version           # 必须 3.10+（backup.py 只用标准库；缺失就先安装）
df -h /                     # 磁盘可用 ≥ 30G
free -h                     # 内存约 2G
```

如果 `uname -m` 不是 `x86_64`（比如是 aarch64），停止，告诉开发者——
镜像构建的目标架构需要跟着改。Compose 低于 2.20 或没有 python3 时先
停止并安装/升级，不要绕过（备份与代理地址刷新都依赖这两个基线）。

## 3. 配置 swap（内存兜底）

2 GiB 内存必须配 swap，防止瞬时内存冲高直接杀进程：

```bash
if [ ! -f /swapfile ]; then
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi
free -h   # Swap 一行应显示 2G
```

## 4. 创建部署目录并上传文件

```bash
mkdir -p /opt/skill-eval/nginx
cd /opt/skill-eval
```

从你的 Mac 上传 4 个文件（在 Mac 上执行，不是服务器；`.env` 下一步在服务器上新建）：

```bash
cd <仓库目录>
scp deploy/compose.yaml deploy/backup.sh deploy/backup.py root@你的公网IP:/opt/skill-eval/
scp deploy/nginx/nginx.conf root@你的公网IP:/opt/skill-eval/nginx/
```

`backup.sh` 只是 cron 稳定入口，实际逻辑在 `backup.py`（Python 3.10+
标准库，无需安装依赖）。两个文件都必须放在 `/opt/skill-eval/`。

## 5. 创建 .env（服务器上）

```bash
cd /opt/skill-eval
cp /dev/null .env   # 或直接 vi .env
vi .env
```

内容照抄仓库里的 `deploy/.env.production.example`，填入：

- `REGISTRY`：`registry-vpc.cn-beijing.aliyuncs.com/skill-eval`（内网地址，见 acr-guide 第五步）
- `TAG`：`push-images.sh` 最后输出的标签（形如 `20260904-a1b2c3d`）
- `POSTGRES_PASSWORD`：一个随机强密码（可以用 `openssl rand -hex 16` 生成）
- `DATABASE_URL`：把里面的密码换成同一个强密码，其他照抄
- `CHECKPOINT_DATABASE_URL`：把里面的密码也换成同一个强密码，其他照抄
- `LANGGRAPH_AES_KEY`：在服务器上用 `openssl rand -hex 16` 生成后填入；生成后不可更换。
  **立刻把这个密钥另存到你的密码管理器**——备份归档的 HMAC 校验和 checkpoint
  解密都依赖它，丢失密钥 = 无法完整恢复；密钥不进日志、不进 Git、不放在归档旁边
- `OSS_BUCKET` / `OSS_PREFIX` / `OSS_ENDPOINT`：按 `oss-guide.md` 第五步填写
  （Bucket 名、专用前缀、同地域内网 Endpoint；三项都不含密钥，OSS 的
  AccessKey 由 ossutil 自己的配置管理）
- `AI_*` 五项：照抄你本地开发 `.env` 里的值

保存后收紧权限：

```bash
chmod 600 /opt/skill-eval/.env
```

## 6. 登录 ACR（服务器上）

```bash
docker login --username=你的阿里云账号名 registry-vpc.cn-beijing.aliyuncs.com
# 密码 = ACR 固定密码（见 acr-guide 第三步）
```

## 7. 配置 OSS 备份工具

```bash
# 安装 ossutil（阿里云官方命令行工具，2.x；backup.py 同时兼容 ossutil64 命令名）
curl -o /usr/local/bin/ossutil https://gosspublic.alicdn.com/ossutil/v2/2.1.1/ossutil-2.1.1-linux-amd64
chmod +x /usr/local/bin/ossutil

# 配置凭据：按提示输入 oss-guide.md 第三步创建的 RAM 用户 AccessKey
# （只授予备份专用前缀读写权限，不要用主账号 AK）
ossutil config
```

备份位置不在脚本里改：`backup.py` 每次运行都从 `.env` 的 `OSS_BUCKET`、
`OSS_PREFIX`、`OSS_ENDPOINT` 读取（第五步已填写）。注册每日定时任务
（cron 路径固定为 backup.sh，内部调用 backup.py run）：

```bash
chmod +x /opt/skill-eval/backup.sh
( crontab -l 2>/dev/null; echo '0 3 * * * /opt/skill-eval/backup.sh >> /opt/skill-eval/backup.log 2>&1' ) | crontab -
crontab -l   # 确认出现 0 3 * * *（按服务器主机时区执行，date 命令确认时区）
```

## 8. 首次启动

```bash
cd /opt/skill-eval

# 1) 拉取全部镜像
docker compose pull

# 2) 初始化数据库结构（仅首次或版本带迁移时需要）
docker compose run --rm api alembic upgrade head

# 3) 创建 checkpoint 数据库（持久 Agent 运行时用，只需一次；
#    重复执行报 already exists 属正常）
docker compose exec postgres createdb -U skill_eval skill_eval_checkpoint

# 4) 启动全部服务
docker compose up -d

# 5) 等待并确认状态（首次启动约需 30-60 秒）
sleep 30 && docker compose ps
```

`docker compose ps` 中 api、postgres、web 应显示 `(healthy)`，worker 和 nginx 为 `Up`。

## 9. 注册管理员

浏览器打开 `http://你的公网IP/`，注册账号。

**注意：第一个注册的人成为平台唯一管理员，之后再也不能注册第二个账号。
确保是你本人第一个注册，注册后立即用密码管理器保存密码。**

## 10. 上线验收（全部必做）

1. `curl http://你的公网IP/healthz` 返回 `{"status":"ok",...,"ai":"production"}`
2. 登录后台，创建或进入一个场景
3. 提交一个会触发 AI 的任务（按平台现有业务流程），在服务器上
   `docker compose logs -f worker` 能看到真实 AI 调用日志，前端最终看到真实模型产出
4. 手动跑一次首次备份（此时 `backups/latest.tar.gz` 还不存在，首次运行
   会创建它；导出期间 API/Worker 短暂停止属预期）：
   ```bash
   bash /opt/skill-eval/backup.sh
   ```
   成功标准：日志分别给出"服务器副本已更新"与"OSS 副本：已发布 ..."，
   最后一行是"完整备份成功"；`ls /opt/skill-eval/backups/` 只有
   `latest.tar.gz` 和 `backup.lock`；OSS 控制台专用前缀下恰好一个
   `latest.json` 加 `bundles/` 里一个归档。任何一步失败都不要当作
   "备份已建立"，按输出提示排查后重跑
5. 在浏览器开发者工具确认登录 Cookie 已写入（名称 `skill_eval_session`）

任何一步失败都不要宣布上线成功：先看 `docker compose logs <服务名>`，
修复后重跑该步。

## 11. 上线后的每日例行

- **每天（Mac）**：手动执行一次备份下载（只需本机 Python 3.10+ 和 SSH，
  不需要 Docker）：
  ```bash
  python3 <仓库目录>/deploy/backup.py download --host <你的SSH主机别名>
  ```
  输出会显示服务器生成时间与备份 ID；校验通过才覆盖本机
  `~/skill-eval-backups/latest.tar.gz`，失败保留旧归档。这是人工动作，
  没有后台任务；详见 `README.md` 的"Mac 每日下载"章。
- **每天（服务器，可选）**：`tail -30 /opt/skill-eval/backup.log` 确认
  最后一行是"完整备份成功"。
- **每月**：按 `restore.md` 的"每月恢复演练"在本地隔离环境演练一次恢复。
- **每 1-3 个月（浏览器/服务器）**：按 `oss-guide.md` 第七、八步检查
  账单与专用前缀残留。
