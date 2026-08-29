# 前端状态模型

## 状态分类

当前没有全局状态库。状态按所有权分为：

| 类型 | 当前所有者 | 示例 |
|---|---|---|
| 认证会话 | `useSession` | 当前用户、loading、anonymous、failed |
| 服务端资源快照 | 页面级 Client Component | `ScenarioShelf` 的 Workspace 列表、`CaseDetail` 的 `Case` |
| 表单/交互瞬时状态 | 所属组件 | 输入值、`busy`、拖拽、当前审读节、展开状态 |
| URL 状态 | Next Router / Search Params | Workspace/Case ID、`returnTo`、开发 `preview` |
| 领域状态展示语义 | `case-builder/lib/caseState.ts` | Case 状态名称、语义色、下一步、进度轨迹 |

不要把这些状态合并成一个通用 store。当前单用户、四页面闭环不需要跨页面客户端缓存。

## 服务端快照优先

FastAPI 返回的 `CaseDetail` 是页面恢复和命令完成后的来源。回答、重试、确认后用响应中的 `case` 覆盖本地资源；刷新后重新 GET。前端不得自行推进 `ready_for_ai -> waiting_for_input` 或 `waiting_for_confirmation -> confirmed`。

页面加载状态用可辨识联合，而不是几个可能冲突的布尔值：

```ts
type Load =
  | { status: "loading" }
  | { status: "ready"; case: Case }
  | { status: "failed"; fault: PageFault };
```

参考 `ScenarioShelf::ListState`、`CaseDetail::Load`。提交中的 `busy`、后台刷新等瞬时状态可以独立，但不得与服务端业务状态同名冒充持久化事实。

## 集中派生状态

Case 状态展示和允许的下一步集中在 `caseState.ts::STATE_META`，进度条由 `trackFor` 派生。新增或改名状态时更新这个穷举映射，不要在多个组件散落 `if (state === ...)` 的不同文案和语义色。

草稿是否走过提问可由服务端返回的 `teacher_answer` 证据派生，参考 `hasTeacherAnswer`；不要只依赖刷新即丢失的 `answered` 本地标记。

## 错误状态

HTTP 错误先由 `toPageFault` 收敛成 `unauthorized | forbidden | not_found | conflict | failed`。401 跳登录并保留 `returnTo`；403 / 404 不渲染资源内容；409 重新读取最新快照或提供明确刷新动作。不要用旧缓存掩盖授权或冲突错误。
