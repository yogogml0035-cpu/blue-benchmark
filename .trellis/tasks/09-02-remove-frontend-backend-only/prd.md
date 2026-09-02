# 移除旧前端并收敛后端工程

## Goal

彻底删除当前 Next.js 前端和只为它服务的工程依赖，让仓库成为可独立安装、启动、测试和交付 OpenAPI 的后端工程。

## Requirements

- 删除 `frontend/`、前端锁文件与仅供前端使用的根级配置。
- 删除 Makefile 中 Next.js、pnpm、typecheck、Playwright 和前端 DTO 生成依赖。
- 后端 OpenAPI 文件继续由生成器维护，并由后端脚本验证漂移。
- 移除 `FRONTEND_URL`、旧 `draft_url` 和仅针对旧 UI 的 CORS 假设；API 响应改为稳定资源 ID/相对 API 信息。
- README 改为后端、Worker、OpenAPI 和 Skill 使用说明，不保留不可运行的浏览器路径。
- 删除已失效的 `.trellis/spec/frontend/`，同步 backend/shared spec。

## Acceptance Criteria

- [ ] 仓库无 `frontend/`、Next.js、pnpm、Playwright 或前端生成类型依赖。
- [ ] `make test`、OpenAPI 生成/验证和后端启动无需 Node.js。
- [ ] 外部上传响应不依赖尚不存在的新前端 URL。
- [ ] 所有后端功能和测试仍可运行，文档准确描述当前边界。
