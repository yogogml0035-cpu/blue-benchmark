#!/usr/bin/env bash
# 每日备份：业务数据库 + 文件存储 → 阿里云 OSS（异地）+ 本地保留 7 天。
#
# 服务器上的安装位置：/opt/skill-eval/backup.sh
# 首次使用前：
#   1. 修改下面两个变量（OSS 桶名和备份路径前缀）
#   2. 确认 ossutil 已配置好 AccessKey（建议只授予该桶读写权限）
#   3. 手动运行一次：bash /opt/skill-eval/backup.sh
#   4. 在 OSS 控制台确认备份对象出现
#
# 定时任务（crontab -e 添加，每天 03:00）：
#   0 3 * * * /opt/skill-eval/backup.sh >> /opt/skill-eval/backup.log 2>&1

set -euo pipefail

# ---- 需要修改的配置 ----
OSS_BUCKET="oss://换成你的桶名"
OSS_PREFIX="skill-eval-backups"
COMPOSE_DIR="/opt/skill-eval"
LOCAL_KEEP_DAYS=7
# ------------------------

STAMP="$(date +%Y%m%d-%H%M%S)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
cd "$COMPOSE_DIR"

echo "[$(date '+%F %T')] 开始备份 $STAMP"

echo "==> 导出业务数据库"
docker compose exec -T postgres pg_dump -U "${POSTGRES_USER:-skill_eval}" "${POSTGRES_DB:-skill_eval}" \
  | gzip > "$WORK/db-$STAMP.sql.gz"

echo "==> 打包文件存储（uploads/evidence/versions/...）"
docker compose exec -T api tar czf - -C /app/storage . \
  > "$WORK/files-$STAMP.tar.gz"

echo "==> 上传到 OSS"
ossutil cp -f "$WORK/db-$STAMP.sql.gz" "$OSS_BUCKET/$OSS_PREFIX/$STAMP/db-$STAMP.sql.gz"
ossutil cp -f "$WORK/files-$STAMP.tar.gz" "$OSS_BUCKET/$OSS_PREFIX/$STAMP/files-$STAMP.tar.gz"

echo "==> 校验 OSS 对象存在"
for name in "db-$STAMP.sql.gz" "files-$STAMP.tar.gz"; do
  ossutil stat "$OSS_BUCKET/$OSS_PREFIX/$STAMP/$name" >/dev/null
done

echo "==> 保留本地副本 $LOCAL_KEEP_DAYS 天"
mkdir -p "$COMPOSE_DIR/backups/$STAMP"
cp "$WORK/db-$STAMP.sql.gz" "$WORK/files-$STAMP.tar.gz" "$COMPOSE_DIR/backups/$STAMP/"
find "$COMPOSE_DIR/backups" -maxdepth 1 -type d -mtime "+$LOCAL_KEEP_DAYS" \
  ! -path "$COMPOSE_DIR/backups" -exec rm -rf {} +

echo "[$(date '+%F %T')] 备份完成：$OSS_BUCKET/$OSS_PREFIX/$STAMP/"
