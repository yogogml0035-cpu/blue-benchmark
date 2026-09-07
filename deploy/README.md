# 部署运维手册

本目录包含 Skill Eval Platform 的单机生产部署全部材料。
按你要做的事选择入口：

| 你要做的事 | 入口 |
| --- | --- |
| 第一次接触部署，搞清 ACR/OSS/服务器各是什么 | `acr-guide.md`（镜像）→ `oss-guide.md`（备份存储） |
| 首次部署（新服务器从零到可访问） | `server-setup.md` |
| 日常发版 / 回滚 | 本文档下面两章 + `push-images.sh` |
| 每日备份是怎么跑的 / OSS 副本 | 本文档"备份与三处副本"章 + `oss-guide.md` |
| Mac 每日下载备份 | 本文档"Mac 每日下载"章 |
| 出大事恢复数据 | `restore.md`（先读授权边界） |

配置文件：`compose.yaml`（编排）、`nginx/nginx.conf`（反向代理）、
`.env.production.example`（环境变量模板）、`backup.sh`/`backup.py`（备份）。

## 架构一页图

```
浏览器 → 服务器:80(nginx)
            ├─ /api/* → FastAPI(api) ── PostgreSQL(postgres)
            ├─ /healthz → FastAPI
            └─ 其他 → Next.js(web)
         Worker(worker，与 api 同镜像) 轮询数据库执行真实 AI 任务
         文件存储：appdata 卷（/app/storage）
         备份：backup.py 每日导出两库+文件 → 服务器/OSS/Mac 各留最新一套
```

只有 80 端口对外；数据库和其他服务都在 Docker 内部网络。

## 发版（每次代码更新后）

在你的 Mac 上，仓库根目录执行：

```bash
# 1) 质量门 + 构建 + 推送（约 5-10 分钟，取决于上行带宽）
REGISTRY=registry.cn-beijing.aliyuncs.com/skill-eval deploy/push-images.sh
```

脚本最后输出镜像标签（形如 `20260904-a1b2c3d`）和服务器端命令。
到服务器上执行：

```bash
cd /opt/skill-eval
# 2) 更新 .env 里的 TAG 为新标签
vi .env
# 3) 如果本次发版包含数据库迁移，先迁移（发版前先手动备份，见下）
docker compose run --rm api alembic upgrade head
# 4) 拉新镜像并按整个 Compose 服务图更新
docker compose pull
docker compose up -d
# 5) 确认状态并检查 Nginx 请求
docker compose ps        # 等待全部 healthy
curl -sf http://127.0.0.1/healthz
docker compose logs nginx --tail 20
```

**始终按完整服务图执行第 4 步，不要跳过依赖或单独重启某个服务。**
`compose.yaml` 已声明 nginx 对 api/web 的 `depends_on: restart: true`
（需要 Compose **2.20+**，`docker compose version` 查看；不满足先升级
Compose，不要绕过）：`up -d` 更新 api/web 时会自动重启 nginx，使其重新
解析上游地址，容器内部 IP 变化后公开入口仍然访问新实例。手动脱离
Compose 修改网络（docker network/rm 单容器等）不在这个保证范围内。

验收：浏览器登录验证页面正常 + `docker compose logs worker --tail 20`
无报错。

## 回滚

发现问题时，把 `.env` 里的 `TAG` 改回上一个标签，然后执行与发版第 4-5
步完全相同的完整服务图更新：

```bash
cd /opt/skill-eval
docker compose pull
docker compose up -d
docker compose ps && curl -sf http://127.0.0.1/healthz
```

注意事项：

- 只改代码的回滚：上面命令即可，数据不受影响；
- 如果新版本跑过**数据库迁移**且旧版本不兼容新结构：回滚代码的同时
  必须按 `restore.md` 恢复发版前的数据，且镜像必须与归档清单中的应用
  镜像相容。所以任何带迁移的发版，发版前先手动备份并确认成功：
  `bash /opt/skill-eval/backup.sh`；
- 三处副本都只留最新一套：一旦备份被新一轮成功替换，**不存在更早的
  历史恢复点**，不能承诺"回到 N 天前的数据"。

## 备份与三处副本（每日自动 + 每日手动）

`backup.py`（经 `backup.sh` 由 cron 每天 03:00 主机时区调用）生成唯一
格式 `skill-eval-backup/v1` 的完整恢复点：同一停写窗口内导出业务库、
checkpoint 库和 appdata 文件，打包为单归档 `backups/latest.tar.gz`
（含成员摘要与原密钥 HMAC；密钥本身不在归档里，另行安全保管）。

- 导出期间 API/Worker 短暂停止（停写窗口），导出完成立即恢复；OSS 上传
  在服务恢复之后进行，不延长停写；
- 任一步失败保留各处上一次成功的归档，输出分别给出备份 ID、生成时间和
  服务器/OSS 两处结果，绝不把局部成功说成完整成功；
- **三处各只留最新成功的一套**：服务器 `backups/latest.tar.gz`、OSS
  专用前缀（`latest.json` 指针 + 一个 bundle）、Mac `~/skill-eval-backups/
  latest.tar.gz`。没有日期目录，没有保留天数，更新期间新旧短暂共存属于
  失败保护而非历史留存。

观察备份是否成功：

```bash
tail -30 /opt/skill-eval/backup.log   # 最后一行应为"完整备份成功"；若是
                                      # "服务器完整备份成功；OSS 本次更新失败"，
                                      # 按 oss-guide.md 排查云端，次日备份自动重试
ls -l /opt/skill-eval/backups/        # 应只有 latest.tar.gz + backup.lock
```

恢复到最后一次成功备份意味着：持续失败或漏下载会扩大数据缺口，不承诺
硬性 24 小时上限。OSS 开通、费用与残留检查见 `oss-guide.md`。

## Mac 每日下载（人工执行）

这是你每天主动执行的维护动作，**没有**后台定时任务、提醒或自动云端
下载。在你的 Mac 上（只需 Python 3.10+ 和 SSH，不需要 Docker）：

```bash
# 一次性准备：~/.ssh/config 里配置服务器主机别名（例如 evalserver），
# 并把仓库的 deploy/backup.py 放到本机固定位置（例如 ~/bin/backup.py）

python3 ~/bin/backup.py download --host evalserver
# 可选：--remote-path（默认 /opt/skill-eval/backups/latest.tar.gz）
#       --local-dir（默认 ~/skill-eval-backups）
```

行为与边界：

- 输出显示本次取到的**服务器生成时间**和备份 ID——这是服务器已生成的
  版本，**不保证包含下载时刻之后新增的数据**（下载时间 ≠ 备份时间）；
- 校验（结构、成员摘要、传输完整性）通过后才原子覆盖本机
  `~/skill-eval-backups/latest.tar.gz`；断网、磁盘不足、校验失败都保持
  旧归档不变；
- 同 ID 重复下载幂等，不重复传输；本机目录只有 latest.tar.gz 与锁文件，
  不创建按日期累积的目录；
- 日常来源是服务器（消耗服务器公网流量，套餐额度与超额价格自行核实）；
  服务器不可用时才按 `oss-guide.md` 从 OSS 恢复下载（产生 OSS 外网流出
  流量费），两种来源不混用；
- 一天漏下载不等于备份失败，但你的 Mac 副本会停留在上一次成功下载的
  版本——`verify` 可随时查看本机归档的生成时间：

```bash
python3 ~/bin/backup.py verify ~/skill-eval-backups/latest.tar.gz
```

Mac 副本含完整业务数据：目录权限 700、文件 600（工具自动设置），
不要拷到共享位置；原 AES 密钥另行保管，不放在 Mac 归档旁边。

## 日常观察

```bash
cd /opt/skill-eval

docker compose ps                    # 各服务状态（healthy/Up）
docker compose logs -f worker        # 实时看 AI 任务日志
docker compose logs --tail 100 api   # 后端最近日志
docker compose logs --tail 100 nginx # 访问日志（谁在访问、什么路径）
docker stats --no-stream             # 各容器 CPU/内存占用
free -h                              # 系统内存与 swap 使用情况
df -h /                              # 磁盘（更新期间归档+候选短暂双份占用）
tail -30 /opt/skill-eval/backup.log  # 最近备份是否"完整备份成功"
```

判断 2 GiB 内存是否吃紧：`free -h` 中 swap 使用量持续大于几百 MB，
或 `docker stats` 里某容器内存接近其日常峰值两倍，就去控制台把实例
升级到 4 GiB（变更规格 → 重启即可，部署结构不用动）。

## 重启服务器之后

Docker 容器配置了 `restart: unless-stopped`，服务器重启后会自动拉起，
无需人工干预。重启完成后执行一次 `docker compose ps` 确认全部健康；
如果发现 `backups/backup-state.json` 残留（重启打断了备份），按
`restore.md` 第 2 步的说明人工核查后删除。

## 安全底线（当前版本已具备）

- 数据库端口不对公网开放，只存在于 Docker 内部网络
- `.env`（含 AI 密钥和数据库密码）权限 600，只在服务器上；OSS 的
  AccessKey 只在 ossutil 自己的配置里，不进 `.env` 不进 Git
- 备份归档目录 700、归档文件 600、OSS Bucket 私有、SSH/OSS 走加密传输；
  压缩不等于加密，归档含敏感业务数据，原 AES 密钥单独安全保管
- 登录接口限流：每个 IP 每分钟最多 5 次 + 3 次突发（nginx 配置）
- 应用容器以非 root 用户运行
- 日志轮转：单文件 10 MB、最多 3 份，防止磁盘写满

## 已知未解决项（域名到位后处理）

- 传输为 HTTP 明文：登录密码和会话 Cookie 不加密。拿到域名后：
  DNS 指向服务器公网 IP → 用支持 `shortlived` 配置的 ACME 客户端或先解析后
  正常申请 Let's Encrypt 证书 → nginx 加 443 与证书 → `.env` 中
  `SESSION_COOKIE_SECURE=true` → 80 重定向 443。不需要重新构建镜像。
- 无登录失败锁定和告警通知：当前靠限流兜底；如果日志中出现大量 401，
  考虑在 nginx 层加黑名单或应用内防护。
