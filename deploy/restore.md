# 数据恢复手册

适用场景：服务器磁盘损坏、误删数据、升级失败需要回到旧版本并恢复数据。

恢复目标（与规划一致）：最多丢失最近 24 小时数据，允许停机数小时。

## 前置条件

- 能登录服务器（或一台装好 Docker 的替代服务器）
- 拥有最近一次 OSS 备份的访问权限（ossutil 已配置）
- 知道要恢复到的备份时间戳（`STAMP`，格式 `YYYYMMDD-HHMMSS`）

## 恢复步骤

### 1. 停止当前服务，防止恢复期间写入

```bash
cd /opt/skill-eval
docker compose stop api worker nginx
```

### 2. 从 OSS 下载备份

```bash
STAMP=换成备份时间戳
mkdir -p /tmp/restore && cd /tmp/restore
ossutil cp oss://你的桶名/skill-eval-backups/$STAMP/db-$STAMP.sql.gz .
ossutil cp oss://你的桶名/skill-eval-backups/$STAMP/files-$STAMP.tar.gz .
gunzip db-$STAMP.sql.gz
```

### 3. 恢复数据库

```bash
cd /opt/skill-eval
# 确保 postgres 在运行
docker compose up -d postgres
# 删除旧库并重建（会清空当前所有业务数据！）
docker compose exec -T postgres dropdb -U skill_eval --if-exists skill_eval
docker compose exec -T postgres createdb -U skill_eval skill_eval
docker compose exec -T postgres psql -U skill_eval -d skill_eval < /tmp/restore/db-$STAMP.sql
```

### 4. 恢复文件存储

```bash
# 清空现有文件卷（会丢失恢复点之后上传的所有文件！）
docker compose run --rm --entrypoint sh api -c 'rm -rf /app/storage/* /app/storage/.[!.]* 2>/dev/null || true'
# 解包备份
docker compose run --rm -v /tmp/restore:/restore --entrypoint sh api \
  -c 'tar xzf /restore/files-$STAMP.tar.gz -C /app/storage'
```

### 5. 启动服务并验证

```bash
docker compose up -d
docker compose ps   # 等待全部 healthy
```

验证业务路径（缺一不可）：

1. 浏览器打开 `http://服务器IP/`，用管理员账号登录
2. 打开一个包含历史题目的场景，确认题目和材料完整
3. 下载或预览一个历史上传的文件，确认文件内容与数据库记录一致
4. 触发一次真实 AI 任务，确认 Worker 正常消费

### 6. 恢复完成后

- 立即手动运行一次 `bash /opt/skill-eval/backup.sh`，建立新的备份基线
- 删除 `/tmp/restore` 中的备份文件（其中含完整业务数据）

## 每月恢复演练

备份没有演练过等于没有备份。每月至少一次：

1. 在本地电脑（不是生产服务器）用 Docker 起一个临时 `postgres:16-alpine`
2. 从 OSS 拉取最新备份，按上面第 3 步恢复到临时库
3. 用 `psql -c '\dt'` 确认表存在、用 `psql -c 'select count(*) from users;'` 之类的查询确认有数据
4. 解压文件备份到临时目录，确认目录结构包含 uploads/、evidence/、versions/
5. 把演练结果（成功/失败及原因）记录到 `.trellis/workspace/` 当月日志

## 与版本回滚的关系

- 只回滚代码（镜像标签改回旧版）：不需要恢复数据，直接改 `TAG` 后 `docker compose pull && up -d`
- 新版本的数据库迁移破坏了旧结构：回滚代码的同时必须按本手册恢复数据库
- 因此：任何包含数据库迁移的发版，发版前先手动跑一次 `backup.sh`
