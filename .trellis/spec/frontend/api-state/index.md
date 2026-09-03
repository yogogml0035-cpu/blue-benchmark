# 前端 API 与状态层规范

适用于 `frontend/` 的数据获取、API 边界与会话状态。写涉及请求、错误处理或会话的代码前先读本层。

## 规范索引

| 规范 | 何时读取 |
|---|---|
| [API 与状态](./api-and-state.md) | 新增请求、处理错误/401、改会话或路由守卫、改 OpenAPI 边界 |

## 开发前检查

- [ ] 请求是否经过 `src/lib/api/client.ts::request()`，而非裸 `fetch`。
- [ ] 响应/请求类型是否来自 `generated.ts`，没有手写重复 DTO。
- [ ] 401 是否会误触发全局会话失效（探测/登录需 `authRedirect: false`）。
- [ ] 跳转目标是否经 `isSafeReturnPath()` 校验，无开放重定向。

## 质量检查

- [ ] `ApiError` 的 `code` 被用于分流，错误呈现在操作上下文而非只靠 toast。
- [ ] 登录/注册成功后 `refresh()` 再进入受保护应用，布局不弹回登录。
- [ ] `pnpm check:api` 无漂移；`generated.ts` 未被手改。
