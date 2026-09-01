# 人工评分前端规范

## Scenario: 独立答卷评分工作台

### 1. Scope / Trigger

- Trigger：已发布题目修订进入“提交答卷”和“人工评分”页面。
- Scope：App Router、Feature Service、评分表单、历史和开发 Preview；不引入全局 Store、第二套 DTO 或 AI Judge UI。

### 2. Signatures

- `/workspaces/{workspaceId}/question-revisions/{questionRevisionId}/submissions/new`：粘贴或上传入口。
- `/workspaces/{workspaceId}/submissions/{submissionId}`：答卷阅读、规则查看、逐项评分、结果和历史。
- `humanScoringService` 只调用 `apiFetch`，类型只来自 `src/lib/api/generated.ts`。
- 页面状态：`loading | ready(snapshot) | failed(fault)`；评分草稿仅属于当前组件，服务端只有 `submitted` final。

### 3. Contracts

- 桌面 DOM 顺序固定为“答卷 → 题目标准 → 连续评分 → 历史”；宽屏评分区约 400px sticky，窄屏单列展开。
- 每个评分项显示名称、满分、标准答案期望得分/理由、给分点、扣分点、关键项判定和待评分数；客户端 POST 不发送 `total_score`、`critical_passed`、`passed`。
- 分数输入以字符串保存，允许清空后再输入；条件理由保持挂载，只切换必填语义，避免焦点丢失。hard-fail 用原生 `fieldset` + radio。
- 提交成功后用服务端 `GET submission` 覆盖页面快照；已提交结果只读，重新评分从最新历史开始。回读遇到 `401/403/404` 或失败必须清空旧私有快照。
- 评分输入、单选标签和主提交控件最小 44px 命中区；错误有 `aria-invalid`/`aria-describedby`，焦点落到实际错误字段；结果区域 `aria-live=polite` 并在提交后获得焦点。
- UI 常显人话，不显示内部 criterion ID、完整 UUID、storage key、hash、Worker/运行元数据；Preview 只在开发构建启用。

### 4. Validation & Error Matrix

- Session loading → 撑住最终布局的 skeleton；anonymous → 登录面板/跳转；forbidden/not-found → 不渲染旧答卷；网络或业务失败 → 安静错误面板和唯一下一步。
- 空粘贴/未选文件 → 字段错误；后端 413/415/422/409 → 保留可修正草稿并显示局部错误，不用前端猜测结果。
- 已有历史 → 评分表变只读；点击重新评分才载入本地草稿，并携带最新 parent。
- `prefers-reduced-motion: reduce` 下沿用全局退化规则，不能添加持续动画或 `transition: all`。

### 5. Good/Base/Bad Cases

- Good：从已发布题目进入入口，上传一份答卷，评分区始终看得到标准锚点；提交后刷新仍是只读结果，重评历史按序展示 parent lineage。
- Base：窄屏长正文、长理由和长文件名都换行或滚动，不横向溢出；请求回读暂时失败时页面转为故障态而不继续展示旧正文。
- Bad：把评分做成数字卡片墙、展示内部 ID、客户端自行显示“通过”、低分理由卸载导致焦点丢失、生产构建显示 PreviewBar。

### 6. Tests Required

- `pnpm typecheck`、`pnpm build`、`make contract-check`；浏览器 Preview 覆盖 entry/loading/invalid/draft/submitted/rescore/history/forbidden。
- 真实生产前端 E2E：监听 console/pageerror 和评分 POST，断言请求无伪造总分字段；使用 EvalData 真实上游流程后上传本地 Markdown，刷新、重评、检查 parent、390px 无溢出。
- 手动/自动可访问性：Tab 顺序、焦点可见、错误关联、hard-fail radio、44px 命中区、reduced motion；越权页面不出现答卷正文。

### 7. Wrong vs Correct

#### Wrong

```tsx
const passed = score >= 60;
return <p>{passed ? "通过" : "未通过"}</p>;
```

#### Correct

```tsx
await submitScore(workspaceId, submissionId, { command_id, items, parent_score_id });
const snapshot = await getSubmission(workspaceId, submissionId);
setLoad({ status: "ready", snapshot });
```

## Scenario: Cross-revision rescore UI

### 1. Scope / Trigger

- Trigger: a submitted answer enters rescore mode and the teacher can choose a
  later published revision of the same logical question.
- Scope: the native revision selector, criterion draft reset, and historical
  revision rendering; the submission body and score history remain read-only.

### 2. Signatures

- `HumanSubmissionResponse.question_revisions` is the only source for target
  revision views; do not fetch a second hand-written revision DTO.
- `submitScore` sends `question_revision_id` only for an explicit rescore;
  first scoring keeps the compatibility omission.
- `ScoreHistory` resolves each `HumanScore.question_revision_id` against the
  response map before rendering criterion details.

### 3. Contracts

- The selector lists only revisions in the response's same-question map and
  defaults to the latest score's revision.
- Switching to a different revision creates a fresh empty local score draft;
  it never carries criterion IDs or scores from the old revision. Switching
  back to the latest revision may restore that latest score as the starting
  draft.
- The left standard column, right scoring form, title, pass threshold, and
  history metadata all use the active revision view. Internal IDs remain hidden.

### 4. Validation & Error Matrix

- no alternate revision -> show a calm single-version hint, not a disabled
  fake selector;
- target map missing a score's revision -> do not reinterpret it using the
  original revision; show an unreadable-revision fallback label;
- server rejects target or parent -> keep the editable draft and surface the
  server fault without claiming a result;
- switching revision while busy -> selector disabled and criterion draft stable.

### 5. Good/Base/Bad Cases

- Good: v1 history and v2 history display their own names/maxima; selecting v1
  from a v2 rescore clears v2-only inputs and remains usable on a narrow screen.
- Base: only v1 exists; rescore stays available with a one-line explanation and
  no redundant control.
- Bad: using the original revision to label every history item or preserving
  v2 scores after selecting v1 makes the visible evidence disagree with the
  submitted score.

### 6. Tests Required

- Preview/browser: loading, submitted, history, rescore, selector options,
  criterion reset, forbidden state, keyboard access, and 390px overflow.
- Type/build: generated API contract, `pnpm typecheck`, and `pnpm build`.

### 7. Wrong vs Correct

#### Wrong

```tsx
const criterion = originalRevision.criteria.find((item) => item.id === scoreItem.criterion_id);
```

#### Correct

```tsx
const scoreRevision = snapshot.question_revisions[score.question_revision_id];
const criterion = scoreRevision?.criteria.find((item) => item.id === scoreItem.criterion_id);
```
