# 修复无候选任务分组时的死循环

## Goal

处理资料整理成功但 AI 未生成候选任务分组时，前端仍可手动创建并确认任务分组，避免当前页与题页之间的死循环。

## First-principles breakdown

### Target behavior

用户上传资料并完成资料用途确认后，进入“题”页必须仍然有一条可完成的任务分组路径：

- 有 AI 候选分组时，继续编辑、拆分/合并并确认现有候选；
- 没有 AI 候选分组但仍有可用资料时，允许老师从零新增任务、分配资料并确认；
- 确认成功后，刷新或重新进入页面能看到服务端保存的已确认任务。

### Hard constraints

- 任务分组确认仍由后端 `POST .../task-groups/confirmation` 作为唯一事实写入入口；前端不能伪造已确认状态。
- 不能凭空替老师推断分组；零候选时只提供明确的手动编辑入口。
- 已有候选分组的行为、拆分/合并、资料归属校验、忙碌态和错误处理不能回退。
- 只有确实没有可用资料时才显示空状态；不扩展 API、数据库或账号流程。

### Invalidated assumption

当前实现隐含假设“资料整理成功必然至少产生一个 `task_package`”。后端合同允许 `groups=[]` 并保留可用文件，因此这个假设不成立；前端不能把 `task_packages=[]` 统一解释为流程结束或不可操作。

## Requirements

- 调整「题」页的空列表分支，使零候选但存在未忽略资料时进入任务分组编辑器。
- 零候选编辑器提供清晰的状态说明、可新增任务、资料归属选择和确认按钮；提交载荷必须沿用现有分组 Service 和后端合同。
- 零候选且没有可用资料时保留空状态，并给出不会造成死循环的明确下一步。
- 为零候选分支补充可重复的浏览器回归证据，并运行既有前端类型检查、构建和仓库质量门。

## Acceptance Criteria

- [x] 从“当前”点击进入“题”后，若同一批次存在可用资料但没有候选任务，页面不再显示无操作的空提示，而是显示可新增/分配/确认的任务分组编辑器。
- [x] 新增一个任务、分配至少一份资料并确认后，页面显示已确认任务；刷新后仍显示该任务，不重复创建。
- [x] 原有至少一个候选分组的路径仍显示候选内容，确认后仍正常进入已确认任务列表。
- [x] 没有可用资料时不会出现一个无法提交的假编辑器，页面提供明确可恢复的状态。
- [x] `cd frontend && pnpm typecheck`、`cd frontend && pnpm build`、`make test` 通过，且 `git diff --check` 无输出。

## Validation evidence

- 隔离 SQLite + 真实 Next.js/浏览器链路验证：零候选但有可用资料时，入口保持同一 `batch` URL，出现“新增任务”；手动分配后确认成功，刷新后仍只有一个已确认任务。
- 对抗状态验证：分析 queued/running 时显示等待并回当前；分析完成后任务列表重读；全部资料 ignored 时显示“上传新的资料”；候选存在但资料用途未确认时显示回当前入口，不显示不可提交编辑器。
- 自动质量门：`pnpm typecheck`、`pnpm build`、`make test`（111 passed，OpenAPI contract current）和 `git diff --check` 均通过。

## Notes

- 这是前端状态分支修复，暂不修改后端合同、数据库模型或生成 API 文件。
- Keep `prd.md` focused on requirements, constraints, and acceptance criteria.
- Lightweight tasks can remain PRD-only.
