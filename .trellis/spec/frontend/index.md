# 前端开发规范

适用于 `frontend/` 的 Next.js App Router 桌面管理端（React + TypeScript + pnpm）。仓库从纯后端工程扩展而来：FastAPI 仍是业务事实源，Next.js 只做呈现、草稿与调用；浏览器经同源 `/api` 代理，复用后端 HttpOnly Session Cookie。

## 规范索引

| 层 | 何时读取 |
|---|---|
| [API 与状态](./api-state/index.md) | 请求、错误处理、401/会话、路由守卫、OpenAPI 边界 |
| [组件与样式](./components-style/index.md) | UI 组件、BenchMark 视觉令牌、布局/视口、动效、可访问性 |
| [质量与测试](./quality-testing/index.md) | 质量门、单元/组件/浏览器测试、E2E 隔离后端 |

## 开发前检查

- [ ] 已从 `frontend/` 实际代码判断现状，没有把历史前端（已删除的旧页面/旧领域模型）当成现状。
- [ ] 涉及请求/类型时，确认 `generated.ts` 与 `../backend/openapi.json` 一致（`pnpm check:api`）。
- [ ] 涉及界面时，确认复用 `src/components/ui|shell` 与 `--benchmark-*` 令牌。
- [ ] 涉及会话/跳转时，确认走 `session-context.tsx` 与 `redirect.ts` 的安全校验。

## 质量检查

- [ ] `pnpm typecheck && pnpm test && pnpm check:api && pnpm build` 通过。
- [ ] 新增流程有对应 Vitest 或 Playwright 覆盖。
- [ ] 桌面 `1280x720`/`1440x900` 无横向溢出、无裁切、无默认组件库观感。
