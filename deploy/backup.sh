#!/usr/bin/env bash
# 每日备份薄入口：实际逻辑全部在 deploy/backup.py（唯一格式 blue-benchmark-backup/v1）。
#
# 本脚本只做一件事：以稳定路径被 cron 调用，然后 exec 进入 backup.py run。
# 一次成功备份 = 同一停写窗口内导出的业务库 + checkpoint 库 + appdata 文件，
# 打包为 backups/latest.tar.gz（服务器只留这一套最新归档，没有日期目录，
# 没有 LOCAL_KEEP_DAYS 保留天数）；服务恢复之后才上传 OSS（OSS 也只留最新
# 一套：候选校验通过、指针切换后才删除精确的上一对象）。
#
# 服务器上的安装位置：/opt/blue-benchmark/backup.sh 与 /opt/blue-benchmark/backup.py
# 首次使用前：
#   1. 在 /opt/blue-benchmark/.env 填好 OSS_BUCKET、OSS_PREFIX、OSS_ENDPOINT
#      （见 deploy/.env.production.example 的占位说明；OSS 凭证仍由
#      ossutil 自身配置管理，不写进 .env）
#   2. 确认 ossutil 已安装并配置好 AccessKey（建议只授予该桶专用前缀读写权限）
#   3. 手动运行一次：bash /opt/blue-benchmark/backup.sh
#   4. 确认输出分别给出服务器副本与 OSS 副本的备份 ID/时间和结果
#
# 定时任务（crontab -e 添加，每天 03:00，按服务器主机时区执行；
# 用 date 确认主机时区，需要北京时间时保证主机时区为 Asia/Shanghai）：
#   0 3 * * * /opt/blue-benchmark/backup.sh >> /opt/blue-benchmark/backup.log 2>&1
#
# Mac 每日下载与本 cron 相互独立：在你的 Mac 上手动执行
#   python3 backup.py download --host <你的SSH主机别名>
# （只需本机 Python 3.10+ 和 SSH，不需要 Docker；见 deploy 文档。）

set -euo pipefail

COMPOSE_DIR="${COMPOSE_DIR:-/opt/blue-benchmark}"

# 前置：Python 3.10+（服务器与 Mac 工具前置项，不假定默认已安装）
if ! command -v python3 >/dev/null 2>&1; then
  echo "缺少 python3；请先安装 Python 3.10+（backup.py 仅用标准库）" >&2
  exit 1
fi

exec python3 "${COMPOSE_DIR}/backup.py" run --compose-dir "${COMPOSE_DIR}"
