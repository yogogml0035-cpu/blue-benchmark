#!/usr/bin/env bash
# 构建生产镜像并推送到阿里云容器镜像服务（ACR）。
#
# 用法（在仓库根目录执行）：
#   REGISTRY=registry.cn-beijing.aliyuncs.com/<命名空间> deploy/push-images.sh
#
# 也可以把 REGISTRY 写进 deploy/.env（该文件不入库），脚本会自动读取。
# 推送前需要先登录 ACR：docker login --username=<阿里云账号> <registry 域名>
#
# 脚本行为：
#   1. 运行完整质量门（make test），失败即中止
#   2. 用当前日期 + git 短哈希生成镜像标签
#   3. 以 linux/amd64 跨架构构建 web 与 api 两个镜像并直接推送
#   4. 输出标签和服务器端更新命令

set -euo pipefail

cd "$(dirname "$0")/.."

REGISTRY="${REGISTRY:-}"
if [[ -z "$REGISTRY" && -f deploy/.env ]]; then
  REGISTRY="$(grep -E '^REGISTRY=' deploy/.env | cut -d= -f2- || true)"
fi
if [[ -z "$REGISTRY" ]]; then
  echo "错误：未设置 REGISTRY。请通过环境变量或 deploy/.env 提供 ACR 仓库地址。" >&2
  echo "格式示例：registry.cn-beijing.aliyuncs.com/<命名空间>" >&2
  exit 1
fi

echo "==> 运行质量门（make test）"
make test

TAG="$(date +%Y%m%d)-$(git rev-parse --short HEAD)"
echo "==> 镜像标签：$TAG"

if ! git diff --quiet; then
  echo "警告：工作区有未提交改动，镜像将包含这些改动。"
  read -r -p "继续推送？[y/N] " answer
  [[ "$answer" == "y" || "$answer" == "Y" ]] || exit 1
fi

echo "==> 构建并推送 $REGISTRY/skill-eval-web:$TAG"
docker buildx build --platform linux/amd64 \
  -t "$REGISTRY/skill-eval-web:$TAG" \
  --push frontend/

echo "==> 构建并推送 $REGISTRY/skill-eval-api:$TAG"
docker buildx build --platform linux/amd64 \
  -t "$REGISTRY/skill-eval-api:$TAG" \
  --push backend/

echo
echo "推送完成。接下来在服务器上执行："
echo "  1. 把 /opt/skill-eval/.env 中的 TAG 改为：$TAG"
echo "  2. cd /opt/skill-eval"
echo "  3. docker compose run --rm api alembic upgrade head"
echo "  4. docker compose pull && docker compose up -d"
echo "  5. docker compose ps 确认全部 healthy"
