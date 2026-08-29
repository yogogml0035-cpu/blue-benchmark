# Hooks 与数据读取

## 当前模式

仓库没有 React Query、SWR 或全局缓存层。Feature Service 封装 HTTP，Client Component 使用 React Effect 读取，并把结果保存在页面局部的可辨识联合状态中。

唯一独立的业务 Hook 是 `features/auth/hooks/useSession.ts::useSession`。它封装 `GET /api/auth/me`，返回：

```text
loading | authenticated(user) | anonymous(fault) | failed(fault)
```

并提供稳定的 `reload()`。受保护页面必须消费这个 Hook，不要各自复制认证请求和 401 分流。

## Effect 读取约定

参考 `useSession`、`ScenarioShelf`、`CaseUpload` 和 `CaseDetail`：

- 依赖不满足（预演模式、未认证、缺少资源 ID）时直接返回，不发请求；
- 请求前进入显式 loading 状态；
- Effect 内用 `active` 标记，并在 cleanup 置为 false，避免卸载后写状态；
- `catch` 参数按 `unknown` 处理，经 `toPageFault` 统一收敛；
- 需要被 Effect 或事件复用的读取函数使用 `useCallback`，依赖数组保持完整；
- 使用 `useSearchParams` 的 Client Component 必须由路由页的 `Suspense` 兜底。

不要在 render 期间发请求，也不要忽略 cleanup 后继续更新已经卸载的页面。

## 何时新建 Hook

只有状态逻辑被多个组件复用，或它本身代表清晰的产品边界（如 Session、预演查询参数）时才新建 `use*` Hook。单个页面的一次读取、提交或开关继续保留在该 Feature 组件里；不要用 Hook 文件数量代替架构边界。

如果未来引入缓存库，应先明确失效、认证清理、命令后快照覆盖和预演隔离，再单独更新本规范；当前不要混用第二套获取模式。
