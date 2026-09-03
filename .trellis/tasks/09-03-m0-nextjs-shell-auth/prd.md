# 建立 Next.js 壳层与认证

## Goal

建立可维护、可构建、类型化的 Next.js 桌面前端基础，并把 AURA 登录/注册设计接到真实单管理员 Session Cookie 流程。

## Dependency

- `09-03-m0-web-backend-contracts` 已合并并在 `main` 复验。
- 使用其 OpenAPI bootstrap 与认证合同，不在前端复制业务判断。

## Requirements

- 使用 Next.js App Router、React、TypeScript、pnpm 精确锁定依赖。
- `/api/*` 同源 rewrite 到 FastAPI；OpenAPI 生成类型并具备漂移检查。
- 建立统一 API client、错误解析、认证状态、受保护 layout 和安全 `returnTo`。
- 系统为空时展示首次注册，已有管理员时只展示登录；成功后进入评测集路由。
- 不展示忘记密码和记住我；会话失效和登出行为真实可恢复。
- 登录视觉延续 AURA 粒子场景与右侧面板；PNG 只作比对，功能页使用干净确定性粒子层。
- 建立 AURA semantic tokens、共享 AppShell、基础控件、Dialog、状态/错误/骨架组件和 reduced-motion。
- 将 backend/frontend 注册为 Trellis packages，并基于实际壳层代码建立首版 frontend API/状态、组件/样式与质量测试规范，供后续 UI 子任务使用。
- 桌面最低 `1280x720`，主要视觉 `1440x900`；不实现移动端。

## Acceptance Criteria

- [ ] 前端可以安装、类型检查、测试和生产构建，锁文件稳定。
- [ ] 生成 API 类型与 backend OpenAPI 一致，组件无重复手写 DTO。
- [ ] 空库首注、首注后注册关闭、用户名/邮箱登录、会话恢复、401 跳转和登出均通过真实 API。
- [ ] returnTo 只接受站内相对路径，不存在开放重定向或跳转循环。
- [ ] 登录页在 Chrome `1440x900` 与 AURA 基线一致，在 Chrome/Safari `1280x720` 可操作。
- [ ] AppShell、基础控件、键盘焦点、错误关联和 reduced-motion 有组件或浏览器验证。
- [ ] Trellis 能识别 backend/frontend packages，frontend spec 索引和首版规范有真实代码依据且通过上下文验证。

## Out Of Scope

- 评测集业务、凭证、题目列表和审改流程。
- 后端业务重写、移动端、公网部署。
- 把带烘焙假表单的 PNG 直接作为真实登录页。

## Open Questions

- 无。
