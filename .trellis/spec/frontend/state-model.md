# 前端状态模型

## 状态分类

当前没有全局状态库。状态按所有权分为：

| 类型 | 当前所有者 | 示例 |
|---|---|---|
| 认证会话 | `useSession` | 当前用户、loading、anonymous、failed |
| 服务端资源快照 | 页面级 Client Component | `ScenarioShelf` 的 Workspace 列表、`StudioPage` 的 `StudioProjection`、`QuestionPage` 的 `CoCreationSession` |
| 表单/交互瞬时状态 | 所属组件 | 输入值、`busy`、任务分组、抽屉/标准展开状态 |
| URL 状态 | Next Router / Search Params | Workspace/Task/Version ID、工作台 section、`returnTo`、开发 `preview` |
| 领域状态展示语义 | `case-builder/lib/caseState.ts` | Case 状态名称、语义色、下一步、进度轨迹 |

不要把这些状态合并成一个通用 store。当前单用户、服务端快照驱动的工作台不需要跨页面客户端缓存。

## 工作台投影

场景工作台的唯一事实来源是 `GET /api/workspaces/{id}/upload-batches/studio` 返回的 `StudioProjection`，包含 `next_action`、`active_operation`、`latest_receipt` 和 `blocking_issues`。前端不得根据文件列表自行推导“下一步是什么”；所有当前工作流状态分支以 `next_action.kind` 为准。

文件角色确认通过 `PATCH /upload-batches/{batchId}/files/{fileId}/disposition` 逐个提交；每次提交推进 `batch_revision`，连续提交时必须用最新 revision（参考 `StudioShell::FileRoleConfirmation::submit`）。

共创会话的 `status` 字段穷尽 `queued | processing | waiting_for_teacher | ready_for_confirmation | confirmed | failed | projection_pending | continuity_reset`，前端 UI 分支必须覆盖全部八个状态（参考 `case-builder/components/QuestionPage.tsx`）。

## 服务端快照优先

FastAPI 返回的 `StudioProjection`、`CoCreationSessionView` 和 `WorkingSetDraftView` 是页面恢复和命令完成后的来源。回答、重试、确认、覆盖审查和冻结后用服务端快照覆盖本地资源；刷新后重新 GET。前端不得自行宣布资料整理、题定稿或版本冻结完成。

页面加载状态用可辨识联合，而不是几个可能冲突的布尔值：

```ts
type Load =
  | { status: "loading" }
  | { status: "ready"; case: Case }
  | { status: "failed"; fault: PageFault };
```

参考 `ScenarioShelf::ListState`、`StudioPage::Load` 和 `QuestionPage::Load`。提交中的 `busy`、后台刷新等瞬时状态可以独立，但不得与服务端业务状态同名冒充持久化事实。

## 集中派生状态

Case 状态展示和允许的下一步集中在 `caseState.ts::STATE_META`，进度条由 `trackFor` 派生。新增或改名状态时更新这个穷举映射，不要在多个组件散落 `if (state === ...)` 的不同文案和语义色。

草稿是否走过提问可由服务端返回的 `teacher_answer` 证据派生，参考 `hasTeacherAnswer`；不要只依赖刷新即丢失的 `answered` 本地标记。

## 错误状态

HTTP 错误先由 `toPageFault` 收敛成 `unauthorized | forbidden | not_found | conflict | failed`。401 跳登录并保留 `returnTo`；403 / 404 不渲染资源内容；409 重新读取最新快照或提供明确刷新动作。不要用旧缓存掩盖授权或冲突错误。

`useStudioData` 与共创轮询必须给每次请求绑定 generation；workspace/batch/session 变化后旧响应只能丢弃。静默读取遇到 401/403/404 必须清空资源快照，网络瞬断才可按产品需要保留同一资源的旧快照。
