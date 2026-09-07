# 前端 API 与状态

适用于 `frontend/` 的数据边界与会话状态。前端不持有业务事实，业务状态永远以 FastAPI 响应为准；前端只缓存"当前会话是谁"和"未提交的草稿"。

## 唯一 fetch 包装器

- 所有请求必须经过 `src/lib/api/client.ts::request()`，组件内不得散落裸 `fetch`。
- 请求一律走同源 `/api/*`（由 `next.config.mjs` rewrite 到 `BACKEND_URL`），不直接写后端绝对地址，保证 HttpOnly Session Cookie 同源携带。
- `request()` 统一处理：JSON 解析、`204` 空响应、`AbortSignal`、`cache: "no-store"`、非 2xx 转 `ApiError`。
- 后端错误合同映射为 `ApiError { status, code, message, details }`；组件按 `code` 分流，不要解析自由文本或只靠状态码。

## 401 与会话失效

- `request()` 的 `authRedirect`（默认 `true`）控制 401 是否触发全局失效处理器。业务数据请求保持默认；会话探测（`/auth/me`）与凭证提交（`/auth/login`）必须显式 `authRedirect: false`，否则"匿名探测"与"登录失败"会误触发跳转。
- 会话失效处理器在 `session-context.tsx` 注册，整轮会话只跳转一次（`redirected` 一次性开关），避免跳转循环。
- `logout` 期间保持 `loggingOut=true` 直到导航完成，受保护布局据此抑制自己的匿名重定向，避免两者竞争追加 `returnTo`。

## 会话状态

- `SessionProvider`（`src/features/auth/session-context.tsx`）是唯一的会话事实源：`status: loading | authenticated | anonymous` + `user`。
- 登录成功后必须先 `await refresh()`（重取 `/auth/me`）再导航进受保护应用，否则受保护布局仍读到旧 `anonymous` 状态而把用户弹回登录。
- 受保护布局在 `loading` 时渲染稳定骨架，`anonymous` 时按 `returnTo` 重定向，不渲染业务内容。

## 安全跳转（returnTo）

- `returnTo` 只接受站内相对路径，统一经 `src/lib/redirect.ts::isSafeReturnPath()` 校验：必须以单个 `/` 开头，拒绝 `//`、反斜杠、控制字符与任何带 scheme/外域的形态。
- 登录成功后用 `resolvePostAuthPath()`，不安全值一律回落 `/evaluation-sets`，杜绝开放重定向。

## OpenAPI 类型边界

- `src/lib/api/generated.ts` 由 `pnpm generate:api` 从 `../backend/openapi.json` 生成，禁止手改；`pnpm check:api` 校验无漂移。
- 请求/响应类型一律从 `generated.ts` 的 `components["schemas"]` 派生（如 `src/lib/api/auth.ts`），组件与特性层不得手写重复 DTO。
- 生成器运行在独立子包 `tools/api-gen/`（TypeScript 5），因为 openapi-typescript 依赖 TS5 编译器 API，而应用用 TypeScript 7 做类型检查；不要试图把两者合并到同一 typescript 版本。

## 禁止

- 组件内裸 `fetch` 或直接拼后端绝对地址。
- 把会话事实存进 localStorage/sessionStorage 或 URL（会话只来自 `/auth/me`）。
- 用乐观更新掩盖 409/422：写操作失败必须把 `ApiError` 呈现到对应操作上下文。
