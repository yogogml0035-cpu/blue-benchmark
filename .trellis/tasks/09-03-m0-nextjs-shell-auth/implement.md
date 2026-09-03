# Implementation Plan

1. 创建 `frontend/` App Router 工程、精确依赖、pnpm lock、tsconfig、Next/Vitest/Playwright 配置和 ignore 项。
2. 增加 OpenAPI 类型生成、漂移检查、统一 API client 与错误模型。
3. 建立 semantic tokens、共享 UI、AppShell、错误/空/加载边界和图标规范。
4. 实现 session provider/guard、根路由决策和安全 returnTo。
5. 实现 AURA 粒子认证面、首次注册、登录、密码可见切换和登出。
6. 使用 `trellis-meta` 注册 backend/frontend packages；基于真实代码建立 frontend API/状态、组件/样式和质量测试 specs。
7. 增加 API client/auth/redirect/visual component 测试与 Chromium/WebKit 流程。
8. 在 `1280x720` 和 `1440x900` 截图检查非空 Canvas、表单可用、无重叠/溢出；实际 Safari 复核核心登录。
9. 运行 typecheck/test/build、OpenAPI 漂移、后端回归和 `git diff --check`，通过 `trellis-check` 后提交、合并、main 复验与归档。
10. Child 3 启动前，将新 frontend specs 加入 Child 3、4、5 的 context manifests 并重新 validate。

## Risky Files

- `frontend/next.config.mjs`（Cookie 同源代理）
- `frontend/src/lib/api/client.ts`（全局错误/认证行为）
- `frontend/src/features/auth/`（首注与跳转状态）
- `frontend/src/app/globals.css`（全站视觉 token）

## Stop Conditions

- Cookie 在 Next rewrite 后未由 `localhost:3000` 正确保存/发送；
- PNG 假表单进入可交互背景或 Canvas 在任一正式浏览器为空；
- 注册入口仅靠前端隐藏、第二管理员可被创建；
- generated API types 与 OpenAPI 漂移。
