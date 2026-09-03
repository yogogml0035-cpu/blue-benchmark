# 前端质量与测试

适用于 `frontend/` 的质量门与测试策略。依赖由 `package.json` + `pnpm-lock.yaml` 精确锁定，不引入浮动版本。

## 质量门

```bash
pnpm --dir frontend typecheck      # tsc --noEmit（TypeScript 7）
pnpm --dir frontend test           # Vitest 单元/组件
pnpm --dir frontend check:api      # OpenAPI 生成类型漂移检查
pnpm --dir frontend build          # Next.js 生产构建
pnpm --dir frontend test:e2e       # Playwright（Chromium + WebKit）
```

跨层变更同时运行后端 `make test`（含 OpenAPI 漂移）与上述前端门。

## 测试分层

- **Vitest 单元/组件**（`src/**/*.test.{ts,tsx}`）：纯逻辑（`redirect.ts`、`client.ts` 错误解析/401 分流）与控件行为（错误关联、密码可见切换、loading 稳定）。用 `@testing-library/react` + jsdom；`src/test/setup.ts` 统一 `jest-dom` 与 `cleanup()`。
- **Playwright 浏览器**（`e2e/*.spec.ts`）：真实 FastAPI + 真实会话 Cookie。spec 文件名带数字前缀（`01-`、`02-`）保证串行顺序；`fullyParallel:false` + `workers:1`。
  - Chromium 完整流程（首注/登录/登出/会话恢复/returnTo/Canvas）。
  - WebKit 与 1280x720 跑核心登录流程。

## E2E 隔离后端

- `e2e/global-setup.ts` 为每次运行启动隔离后端：临时 SQLite + `alembic upgrade head` + `uvicorn`（fake AI 模式，8123 端口）。**清理由 `globalSetup` 返回的函数完成**——Playwright 只调用 setup 的返回函数，`globalTeardown` 具名导出不会被执行（曾因此泄漏进程与临时目录）。
- **教训（务必保留）**：
  - 全新 SQLite 必须先迁移再起服务；应用启动不会建表（`no such table`）。
  - 杀后端要杀整个进程组（`uv run` 会另起 uvicorn 子进程，单杀 wrapper 会留孤儿占端口）。
  - `globalSetup` 启动前先 `freePort`（并打印被杀 PID），防止上一次泄漏的进程以"健康但库已被删"的状态污染本轮；setup 中途失败也要清理进程与临时目录。
  - 后端访问日志写入 `$TMPDIR/m0-e2e-backend.log`，便于排查请求顺序。
  - 串行依赖：`01-`（首注，需空库）必须先于 `02-`（登录，`ensureAdmin` 兜底）；`workers:1` + 文件名数字前缀共同保证顺序，改动前先理解该约定。
- webServer 用 `pnpm build && pnpm start`（生产构建）。**不要用 `next dev`**：本环境 dev 的 HMR WebSocket 握手在 headless Chromium 下失败，导致 React 不水合、页面逻辑不执行；生产构建稳定。`BACKEND_URL` 只在 **build 期** 注入生效（rewrite 目标在构建期固化到 `.next/routes-manifest.json`，运行期再注入无效）。

## 契约/一致性

- 认证测试断言真实后端行为：空库 `bootstrap=true`、首注后 `false`、登出后管理员仍存在、用户名与邮箱均可登录。
- 选择器优先 `getByRole`/`getByLabel`；`getByLabel("密码")` 需 `{ exact: true }`（避免命中"显示密码"按钮与"确认密码"）；`role="alert"` 需过滤面板文案（Next 路由播报器也带 `role=alert`）。

## 禁止

- 用 `next dev` 跑 E2E 或验收。
- E2E 依赖共享/开发数据库（必须每次新建隔离库）。
- 用固定延迟/假登录模拟（必须真实 API + 真实 Cookie）。
