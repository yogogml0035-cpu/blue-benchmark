<!-- TRELLIS:START -->
# Trellis Instructions

These instructions are for AI assistants working in this project.

This project is managed by Trellis. The working knowledge you need lives under `.trellis/`:

- `.trellis/workflow.md` — development phases, when to create tasks, skill routing
- `.trellis/spec/` — package- and layer-scoped coding guidelines (read before writing code in a given layer)
- `.trellis/workspace/` — per-developer journals and session traces
- `.trellis/tasks/` — active and archived tasks (PRDs, research, jsonl context)

If a Trellis command is available on your platform (e.g. `/trellis:finish-work`, `/trellis:continue`), prefer it over manual steps. Not every platform exposes every command.

If you're using Codex or another agent-capable tool, additional project-scoped helpers may live in:
- `.agents/skills/` — reusable Trellis skills
- `.codex/agents/` — optional custom subagents

Managed by Trellis. Edits outside this block are preserved; edits inside may be overwritten by a future `trellis update`.

<!-- TRELLIS:END -->

# 项目级补充约定

## Git 与 Trellis 任务分支闭环

### 基本原则

- `main` 只保存已经集成并验证通过的状态，不直接承载日常业务开发。
- 每个可以独立实施、检查和验收的 Trellis 子任务使用一条短生命周期分支，默认命名为 `codex/<task-slug>`，并从已经验证且干净的 `main` 创建。
- 父任务负责规划、依赖顺序和最终集成，不默认长期占用一条覆盖全部子任务的大分支。只有多个子任务确实不可独立验收且用户明确批准时，才共用分支。
- 一个子任务必须完成“分支开发 → 质量检查 → 提交 → 合并回 `main` → `main` 复验 → Trellis 收尾 → 删除旧分支”的完整闭环，才能从 `main` 启动下一个子任务。

### 开始子任务

1. 检查当前分支、工作区、所有 worktree、`main` 与 `origin/main` 的关系；不得覆盖、stash、reset 或混入不属于当前任务的改动。
2. 确认当前子任务已获实施批准，并读取对应 PRD、design、implement 和适用 `.trellis/spec/`。
3. 从最新且验证通过的 `main` 创建任务分支；运行 `task.py start` 后，确保 `task.json.branch` 为任务分支、`base_branch` 为 `main`。
4. 若 `main` 在开发期间前进，先把最新 `main` 集成回任务分支，解决冲突并重新运行完整质量检查；禁止用 force、hard reset 或跳过验证来制造可合并状态。

### 提交与合并门禁

- 先在任务分支完成验收标准和 Trellis `trellis-check`。最低验证为 `git diff --check` 与 `make test`；涉及前端、生产构建或跨层运行路径时同时运行 `make build`，任务文档规定的其他命令也必须通过。
- 按一个稳定职责一个提交批次组织 commit；不得提交已知失败、半完成迁移、未同步生成文件或无回滚边界的改动。
- 任务分支提交完成且工作区干净后，切换到 `main`。若 `main` 没有分叉，使用 fast-forward 合并；若不能 fast-forward，返回任务分支集成最新 `main`、重新验证后再合并，不得强行改写 `main` 历史。
- 若远端保护、团队评审或发布流程要求 PR，必须通过 PR 合并，不得绕过保护规则；本地结论不能替代远端合并状态。

### `main` 合并后复验

合并命令成功不等于任务完成。必须在 `main` 上再次确认：

1. 当前工作区干净，`main` 包含本任务的全部提交，且 `git log main..<task-branch>` 为空。
2. 在合并后的 `main` 重新运行该任务的完整质量门；至少执行 `git diff --check`、`make test`，适用时执行 `make build`。
3. 若改动需要进入远端，确认本地 `main` 与 `origin/main` 指向同一已验证提交，并确认 PR/远端分支状态与本地结论一致。
4. 质量门通过后再执行 Trellis 归档和会话记录；不得用 branch test、Preview、文档、HTTP 200 或监听端口冒充 `main` 的合并后验收。

### 删除已合并分支

- 只删除刚完成闭环的当前任务分支；不得使用通配符或批量删除其他分支。
- 删除前必须确认：`main` 复验通过、任务提交已被 `main` 包含、`git log main..<task-branch>` 为空、分支不被任何 worktree 使用、工作区干净，并已识别精确的本地与远端删除目标。
- 满足门禁后使用安全删除：本地使用 `git branch -d <task-branch>`；远端分支存在且不受保护时，再删除对应远端分支。不得删除 `main`、`origin/main` 或 `origin/HEAD`。
- 任一门禁失败时保留分支，报告差异、未合并提交或占用它的 worktree，不得强删。

### 启动下一个子任务

- 只有上一个子任务已经合并、`main` 复验通过、Trellis 收尾完成且旧任务分支按门禁处理后，才能从当前 `main` 创建下一条子任务分支。
- 后续所有 M0 子任务都遵循同一闭环；不得把前一个子任务尚未验收的改动带入下一条分支。
