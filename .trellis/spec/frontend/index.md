# 前端开发规范

适用于 `frontend/` 的 Next.js App Router M0 工作台。规范描述当前 React/TypeScript 实现和真实可验收的评测集流程；M1 知识库、M2 Skill/Agent 执行页面仍是未来边界。

## 规范索引

| 规范 | 何时读取 |
|---|---|
| [前端结构与依赖边界](./structure-and-boundaries.md) | 新增路由、Feature、Service、共享组件或移动文件 |
| [组件、交互与样式](./components-and-styling.md) | 编写页面组件、表单、状态视图、样式或可访问性交互 |
| [Hooks 与数据读取](./hooks-and-fetching.md) | 新增 Effect、数据获取、认证会话或自定义 Hook |
| [前端状态模型](./state-model.md) | 修改服务端资源快照、Case 状态、表单或错误状态 |
| [类型与 API 合同](./type-and-api-contracts.md) | 修改 DTO、OpenAPI、Feature Service 或生成类型 |
| [前端质量与验证](./quality-and-verification.md) | Review、类型检查、构建和人工状态验收 |
| [人工评分](./human-scoring.md) | 答卷入口、双区评分页、历史、条件理由和可访问性 |

## 开发前检查

- [ ] 已判断代码应放在 App 路由、Feature 还是共享层，没有提前建立空模块。
- [ ] 已复用 `apiFetch`、Feature Service、`useSession`、`PageFault` 和现有 UI 原语。
- [ ] 涉及后端合同的变更从 Pydantic / OpenAPI 开始，不手写第二份 DTO。
- [ ] 已区分服务端业务状态、页面加载状态、表单瞬时状态和开发预演状态。

## 质量检查

- [ ] 页面未直接 `fetch`，也未在前端复制授权或状态转换规则。
- [ ] 受保护内容、错误分流、busy 防重和服务端快照覆盖保持正确。
- [ ] 键盘、标签、焦点、alert、reduced-motion 等可访问性没有回退。
- [ ] 预演内容在生产构建中被完整门控，fixtures 仍使用生成类型。
- [ ] 运行 `cd frontend && pnpm typecheck`；路由或生产门控变更再运行 `pnpm build`。
