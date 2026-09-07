# 备份格式与运行时刷新合同

## Scenario: 部署备份/恢复与 Nginx 地址刷新

### 1. Scope / Trigger

- 触发：`deploy/backup.py` 是新备份合同（基础设施集成：PostgreSQL 导出、OSS、SSH）；`deploy/compose.yaml` 的 nginx 依赖重启是跨服务运行时合同。修改任何一处必须保持本文件同步。
- 唯一所有者：归档格式 `blue-benchmark-backup/v1`、验证、发布、下载逻辑全部只在 `deploy/backup.py`；`backup.sh` 是 cron 薄入口（仅 python3 存在性检查 + `exec backup.py run`），不得回增业务逻辑。

### 2. Signatures

```
backup.py run            [--compose-dir DIR] [--backups-dir DIR]
backup.py verify         ARCHIVE [--aes-key-file FILE | env LANGGRAPH_AES_KEY]
backup.py download       --host SSH别名 [--dest DIR]
backup.py restore-check  ARCHIVE --aes-key-file FILE [--compose-dir DIR]
```

- 仅 Python 3.10+ 标准库；argv 直接传密钥被拒绝（只认 `--aes-key-file` 或环境变量）。
- 归档成员固定四个：`manifest.json`、`business.sql`、`checkpoint.sql`、`files.tar`，外层 gzip（mtime=0 可复现）。
- OSS 对象布局固定：`<prefix>/bundles/<backup-id>.tar.gz` + `<prefix>/latest.json` 指针（对象名、ID、大小、整包 SHA-256）。
- 服务器/Mac 本地布局固定：`backups/latest.tar.gz`（Mac 为 `~/blue-benchmark-backups/latest.tar.gz`）+ `backup.lock`，没有日期目录。

### 3. Contracts

- 配置来源：`docker compose config --format json` 解析 API/Worker/PostgreSQL 环境与挂载；不 shell source `.env`。环境变量：`OSS_BUCKET`、`OSS_PREFIX`、`OSS_ENDPOINT`（无密钥；ossutil 凭证由其自身私有配置管理）。
- `manifest.json`：格式版本、备份 ID、导出时间（UTC）、应用镜像标识、业务 schema 版本（run 在停写窗口内经 `docker compose exec` 查询业务库 `alembic_version` 得到；查询失败记 null，输出显示「未知」，不中止备份）、各成员大小与 SHA-256、以原 `LANGGRAPH_AES_KEY` 计算的 HMAC-SHA256（密钥本身不写入）。
- 成功输出合同：服务器与 OSS 两处结果分别输出；两处都成功最后一行才是 `完整备份成功`；OSS 失败时最后一行是 `服务器完整备份成功；OSS 本次更新失败，云端仍指向上一次成功备份`，退出码 0（服务器恢复点完整成立）。
- Nginx 刷新合同：`nginx.depends_on.api/web` 必须同时有 `condition: service_healthy` 与 `restart: true`（Compose 2.20+ 基线）；发版/回滚走完整 Compose 服务图（`pull && up -d`），禁止跳过依赖或单独重启某服务。

### 4. Validation & Error Matrix

| 条件 | 行为 |
|---|---|
| 缺成员 / 重复成员 / 截断 / 成员摘要不一致 | verify/restore-check 拒绝，非零退出 |
| 错误 AES 密钥（HMAC 不匹配） | 拒绝恢复，"重新开放写入前失败"，不生成替代密钥 |
| 路径越界（`../`、绝对路径）/ symlink / hardlink | 解包与校验拒绝 |
| 旧松散两件格式（`db-*.sql.gz`/`files-*.tar.gz`）| 拒绝，无兼容读取路径 |
| DSN 带 query/fragment、host 非本 Compose postgres、库名为 postgres/template0/template1 | 预检拒绝 |
| checkpoint 库不存在 | 拒绝（区别于"库存在但暂无 checkpoint 表"的合法新库） |
| 已有未知 latest / 符号链接 | 不自动覆盖，拒绝 |
| 并发 run / download | flock 互斥拒绝（run 退出码 2） |
| 残留 backup-state.json | 下次 run 拒绝重入，要求人工核查 |
| OSS Bucket 开版本控制/保留锁、前缀为根 | 预检失败，先于停写，不静默关闭保护 |
| 停写边界存在未授权写入连接 | 恢复服务并失败 |
| 导出/打包/上传任一失败 | 保留各处上次成功归档，绝不输出"完整备份成功" |

### 5. Good/Base/Bad Cases

- Good：run 成功 → 事件序 stop < dump×2 < files < start < 原子替换 < OSS 发布；`backups/` 只有 latest.tar.gz + backup.lock；OSS 恰好 1 bundle + 1 latest.json。
- Base：首次部署 checkpoint 库存在但无表 → 备份成功；OSS 未配置 `OSS_*` → 跳过云端并如实报告。
- Bad：第二个库导出失败 → 服务已恢复、旧 latest 保留、无成功字样；Mac 下载校验失败 → 旧归档不变；发布指针写入结果不明 → 先回读再决定，不猜测删除。

### 6. Tests Required

- 默认层 `backend/tests/test_deploy_backup.py`：假 docker/ossutil/ssh（PATH 替身）+ tmp_path 合成数据；断言点包括事件序、失败保留旧版、否定性拒绝矩阵、两轮替换后各处仅一套、输出无密码/密钥。改动 backup.py 任何分支必须同步该文件。
- 默认层 `backend/tests/test_deploy_runtime.py`：compose.yaml 静态断言（restart: true + service_healthy）、`docker compose config` 校验、push-images.sh 无绕过用法、生产 nginx.conf 关键指令未破坏。
- 集成层（`DEPLOY_INTEGRATION_REQUIRED=1`，开启后 Docker 缺失必须 fail 不许 skip）：真实 postgres 导出→verify→恢复回环；静态 IP 两阶段强制上游换 IP + nginx 确被重启 + 请求到达新标记实例（复用旧 IP 不算通过）；代理回归覆盖 URI/查询、X-Forwarded-*、Cookie、登录限流 429、SSE 分批抵达。资源用唯一项目名前缀，只绑本地随机端口（避开 80/3000/8000），teardown 按前缀核验清理。

### 7. Wrong vs Correct

#### Wrong

```bash
# 发版时只重启 API（nginx 滞留旧解析地址）
docker compose up -d --no-deps api
# 备份保留 7 天日期目录
find backups -maxdepth 1 -type d -mtime +7 -exec rm -rf {} +
```

#### Correct

```bash
# 完整服务图更新，nginx 随依赖自动重启刷新地址
docker compose pull && docker compose up -d   # api/postgres/web 应 healthy，worker/nginx 为 Up（无 healthcheck）；再 curl /healthz
# 三处各只留最新成功一套，原子替换 latest.tar.gz，无日期目录
```
