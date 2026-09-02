# Hooks 与数据读取

## 当前模式

仓库没有 React Query、SWR 或全局缓存层。Feature Service 封装 HTTP，Client Component 使用 React Effect 读取，并把结果保存在页面局部的可辨识联合状态中。

唯一独立的业务 Hook 是 `features/auth/hooks/useSession.ts::useSession`。它封装 `GET /api/auth/me`，返回：

```text
loading | authenticated(user) | anonymous(fault) | failed(fault)
```

并提供稳定的 `reload()`。受保护页面必须消费这个 Hook，不要各自复制认证请求和 401 分流。

### 预演隔离

`useSession({ skip: true })` 只供已识别的开发 `preview` 状态使用：Hook 必须直接返回匿名哨兵状态且不调用 `/api/auth/me`，这样 fixture 页面在 API 未启动时也不会产生 500 或泄漏真实会话。`skip` 变为 `false` 时保留 `loading` 初始语义，再开始真实读取；不能把预演账号伪装成服务端登录用户。

## Effect 读取约定

参考 `useSession`、`ScenarioShelf`、`StudioPage`、`AuthoringConversationPage` 和 `VersionPage`：

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

## Scenario: 开发预演的 Session 边界

### 1. Scope / Trigger

- Trigger：页面使用 `?preview=` 展示本地 fixture，而 API 可能没有启动。
- Scope：认证 Hook 的读取边界；不改变真实页面的 Cookie、登录或权限合同。

### 2. Signature

- `useSession({ skip?: boolean }) -> loading | authenticated | anonymous | failed + reload()`。

### 3. Contract

- `skip=true` 时返回匿名哨兵状态，不发 `/api/auth/me`，不把预演身份当成服务端用户。
- `skip=false` 时继续从 `loading` 开始并读取真实 Session；预演切回实况不能复用旧的私有身份。

### 4. Validation & Error Matrix

- 已识别 preview + API 关闭 -> 无网络请求、无 500 console error；
- 实况 + 无 Session -> `anonymous`，由页面保留 `returnTo` 后进入登录；
- 实况 + 网络失败 -> `failed`，由页面提供重新读取；
- preview 状态变化 -> 迟到的真实请求 cleanup 后不得覆盖 fixture。

### 5. Good / Base / Bad

- Good：`/workspaces/x?preview=success` 只渲染 fixture，业务请求数为 0。
- Base：点击“实况”后恢复真实 `loading` 并读取 API。
- Bad：预演页仍调用 `/api/auth/me`，或从上一个账号闪现用户名。

### 6. Tests Required

- Playwright 在 API 未启动时覆盖登录、工作台、建题、rubric 和人工评分 preview；断言 `/api/` 请求为空、console/pageerror 为空，并检查 320/390px 不横溢。

### 7. Wrong vs Correct

```tsx
// Wrong: fixture 分支只阻止业务 GET，会话请求仍然发生。
const session = useSession();

// Correct: 读取所有者在 Hook 边界显式表达预演跳过。
const session = useSession({ skip: Boolean(preview) });
```
