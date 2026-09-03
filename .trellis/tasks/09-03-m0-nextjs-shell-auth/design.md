# Technical Design

## Stack

- Next.js 16 App Router + React 19 + TypeScript；pnpm 精确锁定。
- CSS Custom Properties + CSS Modules；lucide-react 图标。
- openapi-typescript 生成 `src/lib/api/generated.ts`。
- Vitest/Testing Library 做纯逻辑与组件测试，Playwright 做 Chromium/WebKit 流程。
- 不引入 Tailwind、UI kit、全局状态或数据缓存框架。

## Routes

- `/`：根据 `/auth/me` 与 `/auth/bootstrap` 选择应用、注册或登录。
- `/login`：已有管理员登录。
- `/register`：仅 registration_available 时可用。
- `(app)/layout`：恢复 session、渲染 AppShell、统一处理 401。
- `/evaluation-sets`：本子任务只提供可挂载的占位路由，业务在下一子任务完成。

## API Boundary

`next.config.mjs` rewrite `/api/:path*` 到 server-only `BACKEND_URL`。统一 client 处理 JSON/204、AbortSignal、AppError 和 no-store；不建立 Next Route Handler BFF。`returnTo` 必须以单个 `/` 开头且拒绝 `//`、scheme 和外域。

## Visual Foundation

建立 page/nav/surface/text/muted/action/focus/success/danger 与文件夹多色语义 token。AppShell 支持 232px/80px 桌面折叠。正文 letter-spacing 为 0；AURA 字标用独立字符 gap 表达。

登录页移植原型粒子算法，使用固定随机种子并只在 resize 重绘，保持 Chrome/Safari 和截图稳定。登录/注册共享认证面板但文案、字段和提交动作明确分离。

## Trellis Frontend Context

使用 `trellis-meta` 安全更新 `.trellis/config.yaml`，注册 `backend` 与 `frontend` package。基于已经落地的壳层建立 `.trellis/spec/frontend/index.md` 及 API/状态、组件/样式、质量/测试规范；不写模板占位。后续子任务启动前把这些现存规范加入其 context manifests。

## Auth State

首次 bootstrap 与 session 请求可并行；有效 session 优先进入 app。注册 409 ADMIN_EXISTS 后刷新 bootstrap 并转登录，不继续显示可创建第二管理员。所有 pending/error 控件保持稳定尺寸。

## Rollback

`frontend/` 在本子任务内仍不承载业务数据，可整体回退；同时恢复 Makefile/OpenAPI 类型命令，不能留下指向不存在目录的脚本。
