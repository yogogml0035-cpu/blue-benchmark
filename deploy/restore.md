# 数据恢复手册（完整恢复点 blue-benchmark-backup/v1）

适用场景：服务器磁盘损坏、误删数据、升级失败需要回到最近一次成功备份。

恢复目标：恢复到**最近一次成功备份**。服务器每天 03:00（主机时区）生成一套
完整恢复点；备份时刻之后新增或修改的数据会丢失。本手册不提供实时恢复、
历史时间点恢复或零数据损失能力。

**授权边界：生产环境的实际恢复是破坏性操作，必须事先获得你对目标环境和
数据范围的单独明确授权。本文档是人工操作步骤，不是无人值守清库工具；
每一步都由你执行并确认结果。**

## 三类操作的区分

| 你要做的事 | 去哪里 |
| --- | --- |
| 首次空库部署（新服务器从零开始） | `server-setup.md` |
| 日常备份、OSS 副本、Mac 每日下载 | `README.md` + `oss-guide.md` |
| 发版回滚（只回退代码版本，数据不动） | `README.md` 的回滚章节 |
| 恢复数据（替换现有两库和文件） | 本文档 |

## 什么是完整恢复点

一套完整恢复点 = 一个归档文件 `latest.tar.gz`（格式 `blue-benchmark-backup/v1`），
内含同一停写窗口导出的四个成员：

| 成员 | 内容 |
| --- | --- |
| `manifest.json` | 格式版本、备份 ID、导出时间、应用镜像标识、业务 schema 版本、各成员大小与 SHA-256、用原密钥计算的 HMAC-SHA256 |
| `business.sql` | 业务库结构和数据 |
| `checkpoint.sql` | checkpoint 库结构和数据（加密的执行连续性状态） |
| `files.tar` | appdata 卷中本项目文件（uploads/evidence/versions 等） |

三处副本，每处只留最新成功的一套：

- 服务器：`/opt/blue-benchmark/backups/latest.tar.gz`
- OSS：`<OSS_PREFIX>/latest.json` 指针 + `<OSS_PREFIX>/bundles/<备份ID>.tar.gz`
- Mac：`~/blue-benchmark-backups/latest.tar.gz`（每日手动下载）

两条铁律：

1. **两库加文件必须成套恢复**，不能用不同时间的任意两份备份拼凑；
   仅业务库加文件的旧松散备份不是完整恢复点，工具会直接拒绝。
2. **原 `LANGGRAPH_AES_KEY` 必须单独安全保管**（密码管理器，不在服务器上、
   不在 Git 里）。丢失密钥 = checkpoint 无法解密，完整恢复必须被拒绝；
   不允许重新生成密钥代替恢复，不允许假造执行历史。

## 前置条件

- 目标服务器（或一台装好 Docker 的替代服务器）可用，已安装：
  - Docker Compose **2.20+**（`docker compose version` 查看）
  - Python **3.10+**（`python3 --version` 查看）
  - 本仓库的 `deploy/backup.py`（与生成归档的版本一致或更新）
- 手上有：一套可用归档、原 `LANGGRAPH_AES_KEY`（建议先写入一个 600 权限的
  密钥文件，例如 `~/keys/blue-benchmark-aes.key`，恢复后删除）、清单中记录的
  应用镜像标签（恢复环境的镜像必须与归档相容）
- 明确知道要恢复到的备份 ID 和生成时间（`verify` 输出会显示）

## 恢复步骤

以下命令中：`/opt/blue-benchmark` 是部署目录，`latest.tar.gz` 指你选定的那套
归档（服务器上即 `/opt/blue-benchmark/backups/latest.tar.gz`；从别处取回的先
放到一个临时目录，例如 `/tmp/restore/latest.tar.gz`，命令里写实际路径）。

### 0. 取得归档

- 服务器还在：直接用 `/opt/blue-benchmark/backups/latest.tar.gz`。
- 服务器没了：按 `oss-guide.md` 的"恢复下载"从 OSS 取回（先读 `latest.json`
  指针，再下载对应 bundle）。Mac 副本也可以作为来源，格式完全相同。

### 1. 验证归档与原密钥（任何写入之前，失败即停）

```bash
cd /opt/blue-benchmark
python3 backup.py restore-check /tmp/restore/latest.tar.gz \
  --aes-key-file ~/keys/blue-benchmark-aes.key
```

核对输出中的：格式版本、备份 ID、生成时间、应用镜像标识、业务 schema 版本。
也可以先用不带密钥的 `python3 backup.py verify <归档>` 查看结构与成员摘要
（此时 HMAC 未核对，真正恢复前必须用原密钥通过 `restore-check`）。`verify` 的密钥除 `--aes-key-file` 外也可经环境变量 `BLUE_BENCHMARK_BACKUP_AES_KEY`（值为原 `LANGGRAPH_AES_KEY`）提供；`restore-check` 仅接受 `--aes-key-file`。为避免密钥落入 shell 历史，推荐始终用密钥文件。

以下情况必须停在这里，不进入后续任何步骤：

- 缺少 `checkpoint.sql` 成员（旧格式松散备份）——拒绝完整恢复；
- HMAC 校验失败（密钥不对或归档被篡改）——不生成替代密钥；
- 归档损坏/截断/成员摘要不一致；
- 目标两库、应用镜像版本没有逐项核实。

### 2. 暂停备份调度并取得维护互斥锁

```bash
# 注释掉每日备份 cron（恢复完成后再取消注释）
crontab -l | sed 's|^0 3 \* \* \* /opt/blue-benchmark/backup.sh|#&|' | crontab -
crontab -l   # 确认该行已被注释
```

备份与人工恢复共用同一把维护互斥锁（`/opt/blue-benchmark/backups/backup.lock`，
flock 文件锁）。恢复期间不要运行 `backup.sh`/`backup.py run`；如果误跑，
它会因锁被占用或残留维护状态而拒绝执行，不会与恢复互相干扰。

如果 `backups/backup-state.json` 存在（上一次备份被 SIGKILL/断电打断的
残留），先 `docker compose ps` 人工核查 api/worker 是否在运行，确认无遗留
停机后删除该文件再继续。

### 3. 停止本项目写入

```bash
cd /opt/blue-benchmark
docker compose stop api worker nginx
docker compose ps   # api/worker/nginx 应为 exited，postgres 保持运行
```

### 4. 确认替换范围（想清楚再继续）

本恢复会**替换**：

- 数据库 `blue_benchmark`（业务库）的全部数据：题目、材料、评分维度、运行事件、
  管理员账号——备份之后新增的全部丢失；
- 数据库 `blue_benchmark_checkpoint` 的全部数据：加密的执行连续性状态；
- `appdata` 卷中本项目文件（uploads/evidence/versions 等）。

本恢复**不动**：同一 PostgreSQL 实例上的其他数据库、pgdata 卷本身、
`.env`、镜像、OSS/Mac 上的副本。

确认这正是你要的后果后再继续。

### 5. 重建目标两库（不整盘删除）

```bash
cd /opt/blue-benchmark
docker compose up -d postgres          # 确保 postgres 在运行（healthy）
docker compose exec postgres dropdb -U blue_benchmark --if-exists blue_benchmark
docker compose exec postgres dropdb -U blue_benchmark --if-exists blue_benchmark_checkpoint
docker compose exec postgres createdb -U blue_benchmark blue_benchmark
docker compose exec postgres createdb -U blue_benchmark blue_benchmark_checkpoint
```

### 6. 受控输入导入两个 SQL（错误即停）

把归档里的两个 SQL 解出到临时目录（解包路径由 tar 的 data filter 严格
校验，拒绝越界成员）：

```bash
mkdir -p /tmp/restore/sql
tar -xzf /tmp/restore/latest.tar.gz -C /tmp/restore/sql \
  business.sql checkpoint.sql
```

导入（`-i` 从容器内文件读入，不经 shell 重定向；`ON_ERROR_STOP=1` 任何
SQL 错误立即中止）：

```bash
docker cp /tmp/restore/sql/business.sql   $(docker compose ps -q postgres):/tmp/business.sql
docker cp /tmp/restore/sql/checkpoint.sql $(docker compose ps -q postgres):/tmp/checkpoint.sql

docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U blue_benchmark -d blue_benchmark \
  -c '\i /tmp/business.sql'
docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U blue_benchmark -d blue_benchmark_checkpoint \
  -c '\i /tmp/checkpoint.sql'
```

任何一条报错就停下：此时两库处于半恢复状态，**不要启动 api/worker**，
回到第 5 步重来或排查原因。旧手册中"文件解包命令引用 `$STAMP` 但变量未
传入容器"的问题在新流程中不存在：恢复点就是单个 `latest.tar.gz`，所有
命令写的都是宿主机/容器内的实际路径。

### 7. 恢复文件卷（路径严格校验）

```bash
# 把 files.tar 解出到宿主机临时目录（data filter 拒绝越界/危险成员）
mkdir -p /tmp/restore/files
tar -xzf /tmp/restore/latest.tar.gz -C /tmp/restore/files files.tar
mkdir -p /tmp/restore/appdata
tar -xf /tmp/restore/files/files.tar -C /tmp/restore/appdata

# 先删除第 3 步 stop 后仍引用卷的 exited 容器（只删容器，不动任何卷；
# nginx 不挂载 appdata），否则下面的 volume rm 会报 "volume is in use"
docker compose rm -f api worker

# 清空 appdata 卷并写回（一次性容器挂载卷本身，不依赖已停止的 api）
docker volume rm -f blue-benchmark_appdata
docker volume create blue-benchmark_appdata
docker run --rm \
  -v blue-benchmark_appdata:/app/storage \
  -v /tmp/restore/appdata:/restore:ro \
  alpine sh -c 'cp -a /restore/. /app/storage/'
```

> 卷名以 `docker volume ls | grep appdata` 实际输出为准（compose 项目名前缀，
> 默认部署目录 /opt/blue-benchmark 对应 `blue-benchmark_appdata`）。
> `docker volume rm` 会丢失卷中当前全部文件——这正是第 4 步确认过的后果。
> **绝不要用 `docker compose down -v` 绕过 "volume is in use"**：它会连
> `pgdata` 卷一起删除——第 6 步刚导入的数据随之丢失，只能回到第 5 步在
> 全新空实例上重做；若未察觉而继续，第 8 步 `alembic check` 的报错语义会
> 与本文档预期完全对不上，首次恢复者无从诊断。正确做法就是上面的
> `docker compose rm -f api worker`。

### 8. 启动前验证（任一失败保持未开放写入）

```bash
# 1) 业务 schema 与镜像版本相容：用归档清单里的镜像标签跑迁移检查
#    （清单"应用镜像"与"业务 schema 版本"见第 1 步输出；.env 的 TAG 必须相容）
docker compose run --rm api alembic check

# 2) 业务数据抽查
docker compose exec postgres psql -U blue_benchmark -d blue_benchmark \
  -Atc 'SELECT count(*) FROM eval_questions;'

# 3) checkpoint 数据存在（表由备份带来；解密验证在第 9 步由应用完成）
docker compose exec postgres psql -U blue_benchmark -d blue_benchmark_checkpoint \
  -Atc 'SELECT count(*) FROM checkpoints;'
```

`alembic check` 失败说明镜像与归档 schema 不相容：三处副本只留最新一套，
更旧镜像不兼容现存唯一备份时**不能**执行历史版本回滚；停下，改用与归档
相容的镜像标签（清单里有记录），不要强行启动。

### 9. 恢复服务与代理（完整 Compose 入口）

```bash
cd /opt/blue-benchmark
docker compose up -d          # 完整服务图；nginx 会随 api/web 一起刷新
docker compose ps             # 等待 api/postgres/web healthy，worker/nginx Up
curl -sf http://127.0.0.1/healthz
```

不要用 `--no-deps` 或单独重启某个服务——那会绕过 nginx 的依赖重启，
代理可能滞留旧容器地址。

### 10. 验证实际业务与任务恢复

浏览器逐项确认（缺一不可）：

1. `http://服务器IP/` 用管理员账号登录（会话 Cookie 正常写入）；
2. 打开一个包含历史题目的场景，题目和六类材料完整；
3. 下载或预览一个历史上传文件，内容与题目记录一致（文件摘要核对）；
4. **原密钥解密验证**：对一个历史题目执行"重新生成"（确认弹窗后触发），
   确认 Worker 正常消费、生成过程 SSE 实时输出、最终产出完整评分项。
   checkpoint 库的加密状态只有这一步能真正证明可用；失败说明密钥或
   checkpoint 数据有问题，回到第 1 步重新核对，不要把生成失败当作"数据已恢复"。

### 11. 恢复调度与建立新基线

```bash
# 取消 cron 注释
crontab -l | sed 's|^#\(0 3 \* \* \* /opt/blue-benchmark/backup.sh\)|\1|' | crontab -
crontab -l    # 确认 0 3 * * * 恢复

# 立即手动跑一次备份，建立恢复后的新基线（服务器+OSS 同时更新）
bash /opt/blue-benchmark/backup.sh
```

Mac 端当天再手动执行一次 `backup.py download`，三处重新对齐到同一恢复点。

### 12. 精确清理临时文件（含敏感数据）

恢复**成功**或**明确中止**后，删除本次产生的全部临时文件：

```bash
rm -rf /tmp/restore            # 归档副本、SQL、解包文件都在这里
docker compose exec postgres rm -f /tmp/business.sql /tmp/checkpoint.sql
rm ~/keys/blue-benchmark-aes.key   # 如果密钥文件是本次恢复临时创建的
```

只清理本次恢复创建的文件；不扫描、不删除你之前保存的任何历史文件。
不生成自动 `.bak`、不保留半恢复的历史库。

## 失败语义（必须遵守）

- 第 1、8、10 步任何一项失败：**保持未开放写入**（api/worker 不启动或
  立即停回），不输出"恢复成功"，不进入下一步；
- 缺少 checkpoint 成员、错误密钥、损坏归档：工具会明确拒绝；不接受
  "只恢复业务库"的降级方案作为完整恢复；
- 不生成替代密钥、不假造执行历史、不猜测转换旧格式；
- 中止恢复后按第 12 步清理临时文件；两库如已重建但导入失败，它们处于
  空库/半恢复状态，重新从第 5 步执行完整流程。

## 与版本回滚的关系

- 只回滚代码（镜像标签改回旧版）：按 `README.md` 回滚章节执行完整
  Compose 更新即可，数据不受影响；
- 新版本的数据库迁移破坏了旧结构：回滚代码的同时必须按本手册恢复数据，
  且镜像标签必须与归档清单中的应用镜像相容（见第 8 步）；
- 因此：任何包含数据库迁移的发版，发版前先手动跑一次
  `bash /opt/blue-benchmark/backup.sh` 并确认输出"完整备份成功"。

## 每月恢复演练

备份没有演练过等于没有备份。每月至少一次，在**本地隔离环境**（不是生产
服务器）演练：

1. 用 Docker 起一个临时 `postgres:16-alpine`（独立容器名与端口，不碰现有服务）；
2. 取最新归档（Mac 副本即可），按第 1 步 `restore-check` 核对格式与密钥；
3. 按第 5-8 步把两库导入临时库，抽查行数与 checkpoint 表；
4. 解包 `files.tar` 到临时目录，确认 uploads/evidence/versions 结构与摘要；
5. 把演练结果（成功/失败及原因）记录到 `.trellis/workspace/` 当月日志。

演练只创建、只删除本次演练自己的容器/卷/临时目录。
