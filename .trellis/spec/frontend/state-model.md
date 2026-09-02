# 前端状态模型

## 状态分类

当前没有全局状态库。状态按所有权分为：

| 类型 | 当前所有者 | 示例 |
|---|---|---|
| 认证会话 | `useSession` | 当前用户、loading、anonymous、failed |
| 服务端资源快照 | 页面级 Client Component | `ScenarioShelf` 的 Workspace 列表、`StudioPage` 的 `StudioProjection`、`AuthoringConversationPage` 的 `AuthoringConversation` |
| 表单/交互瞬时状态 | 所属组件 | 输入值、`busy`、任务分组、抽屉/标准展开状态 |
| URL 状态 | Next Router / Search Params | Workspace/Task/Version ID、工作台 section、`returnTo`、开发 `preview` |
| 领域状态展示语义 | 各自 Feature 组件的穷举映射 | 建题会话、rubric 和人工评分分别只展示自己的服务端状态 |

不要把这些状态合并成一个通用 store。当前单用户、服务端快照驱动的工作台不需要跨页面客户端缓存。

## 工作台投影

场景工作台的唯一事实来源是 `GET /api/workspaces/{id}/upload-batches/studio` 返回的 `StudioProjection`，包含 `next_action`、`active_operation`、`latest_receipt` 和 `blocking_issues`。前端不得根据文件列表自行推导“下一步是什么”；所有当前工作流状态分支以 `next_action.kind` 为准。

任务分组页还要把批次状态、活动操作和任务包列表一起看：`task_packages=[]` 不能单独解释为“没有下一步”。当批次为 `ready_for_confirmation`、没有活动操作且存在未忽略资料时，空列表代表“AI 没有候选分组”，应显示手动新增/分配/确认入口；处理中或失败时应显示等待/回当前重试；没有可用资料时应提供上传新批次的出口，不能把用户送回同一空状态。

文件角色确认通过 `PATCH /upload-batches/{batchId}/files/{fileId}/disposition` 逐个提交；每次提交推进 `batch_revision`，连续提交时必须用最新 revision（参考 `StudioShell::FileRoleConfirmation::submit`）。

共创会话的 `status` 字段穷尽 `queued | processing | waiting_for_teacher | ready_for_confirmation | confirmed | failed | projection_pending | continuity_reset`，前端 UI 分支必须覆盖全部八个状态（参考 `case-builder/components/AuthoringConversationPage.tsx`）。

## 服务端快照优先

FastAPI 返回的 `StudioProjection`、`AuthoringConversationView`、`QuestionListResponse` 和 rubric snapshot 是页面恢复和命令完成后的来源。回答、重试、确认、发布、停用和恢复后用服务端快照覆盖本地资源；刷新后重新 GET。前端不得自行宣布题目已发布或版本已形成。

页面加载状态用可辨识联合，而不是几个可能冲突的布尔值：

```ts
type Load =
  | { status: "loading" }
  | { status: "ready"; case: Case }
  | { status: "failed"; fault: PageFault };
```

参考 `ScenarioShelf::ListState`、`StudioPage::Load` 和 `AuthoringConversationPage::Load`。提交中的 `busy`、后台刷新等瞬时状态可以独立，但不得与服务端业务状态同名冒充持久化事实。

## 集中派生状态

建题会话、rubric 和人工评分的状态展示分别由对应 Feature 组件的穷举映射负责；新增或改名状态时更新服务端合同、该 Feature 的文案和错误视图，不要重新引入旧案例编辑器的共享状态映射。

草稿是否走过提问可由服务端返回的 `teacher_answer` 证据派生，参考 `hasTeacherAnswer`；不要只依赖刷新即丢失的 `answered` 本地标记。

## 错误状态

HTTP 错误先由 `toPageFault` 收敛成 `unauthorized | forbidden | not_found | conflict | failed`。401 跳登录并保留 `returnTo`；403 / 404 不渲染资源内容；409 重新读取最新快照或提供明确刷新动作。不要用旧缓存掩盖授权或冲突错误。

`useStudioData` 与共创轮询必须给每次请求绑定 generation；workspace/batch/session 变化后旧响应只能丢弃。静默读取遇到 401/403/404 必须清空资源快照，网络瞬断才可按产品需要保留同一资源的旧快照。

## Scenario: Question lifecycle workspace

### 1. Scope / Trigger

- Trigger: the new `当前 / 题 / 版本` workbench reads authored question
  lifecycle and automatic evaluation-set history.
- Scope: question list, authoring draft, rubric publish, disable/restore/delete,
  and read-only versions. Legacy Working Set state is not a daily UI source.

### 2. Signatures

- `GET /api/workspaces/{workspaceId}/questions` is the question list snapshot.
- `POST .../question-drafts/{draftId}/lifecycle` handles `derive`, `disable`,
  `restore`, and `delete` with draft CAS.
- `POST .../question-drafts/{draftId}/rubric/start` is the single question
  confirmation plus rubric-generation action.
- `POST .../question-drafts/{draftId}/rubric/publish` is the single rule
  confirmation plus automatic current-set publication action.

### 3. Contracts

- `lifecycle_status` is server-owned: `draft | active | disabled | deleted`.
  The UI never infers it from rubric status or button state.
- Publishing returns a server snapshot only after the ready v2 package and
  current-set version exist. The runtime partition is allowlisted; bad samples,
  reference answers, rubric and teacher judgment remain in judge/provenance.
- Disable/restore/delete uses a pending lifecycle transition, ready-version
  CAS, then visible state commit. Package failure clears pending state and does
  not change the visible lifecycle.

### 4. Validation & Error Matrix

- stale draft revision -> `409 STALE_QUESTION_DRAFT`;
- publish disabled/deleted -> `409 QUESTION_NOT_ACTIVE`;
- new submission/score after disabled/deleted -> `409 QUESTION_NOT_ACTIVE`;
- deleted restore -> `409 QUESTION_LIFECYCLE_CONFLICT`;
- automatic package/storage failure -> `503` with no visible lifecycle/version
  mutation;
- runtime input disposition/hash mismatch -> `409 QUESTION_REVISION_NOT_READY`.

### 5. Good/Base/Bad Cases

- Good: one combined action confirms the question, generates rules, publishes
  it, and the UI says it is in the current evaluation set.
- Base: the teacher pauses in rubric review; GET restores the draft and the
  publish action remains the only high-consequence action.
- Bad: a UI button claims published while no version exists, a disabled question
  accepts a new submission, or the version page exposes a manual next draft.

### 6. Tests Required

- Preview/browser: combined action labels, lifecycle list, read-only versions,
  disabled/restore/delete states and 390px layout.
- API: bad-sample allowlist, no contract prerequisite, idempotent publish,
  automatic package/runtime leakage, lifecycle CAS and write gate.
- Recovery: PostgreSQL and SQLite migrations, pending transition package failure,
  production Worker/Provider EvalData E2E, and real browser E2E.

### 7. Wrong vs Correct

#### Wrong

```tsx
const published = rubric.status === "published";
return <span>{published ? "已进入评测集" : "待审阅"}</span>;
```

#### Correct

```tsx
const published = question.lifecycle_status === "active" && Boolean(question.active_revision_id);
return <span>{published ? "已进入当前评测集" : "继续审阅"}</span>;
```
