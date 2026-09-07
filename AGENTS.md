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

## 命名口径

本工程名统一为 `blue-benchmark`（数据库/角色/Cookie/Python 标识用 snake_case `blue_benchmark`），UI 与品牌语境统一为「蓝标汽车事业 BenchMark 平台」，禁止使用任何第三形态称呼（包括任何历史旧名及其变体）。

## 新旧语义切换与遗留删除

### 适用范围

- 当已批准任务明确以新语义替代旧语义时，采用一次性切换；除非任务文档明确要求，否则不保留旧语义兼容层。
- 删除范围必须以当前任务已批准的 PRD、design 和 implement 为边界，不得借“清理旧逻辑”删除任务范围外或尚未确认用途的代码。

### 规划要求

- 在实施前识别被替代的旧语义及其影响面，并同步修改相关任务文档：
  - `prd.md` 明确旧行为、旧数据和旧操作不再受支持，并写入验收标准。
  - `design.md` 明确一次性切换边界、需要删除的接口和数据结构，以及回滚方式。
  - `implement.md` 列出具体删除项、执行顺序、检索范围和验证命令。
- 相关父子任务、当前维护的规格文档和用户文档存在旧口径时必须同步更新；已归档 Trellis 任务作为历史记录保留，不因新语义批量改写。
- 运行时回滚依赖 Git、数据库备份或部署回退，不得通过长期保留旧代码路径、双写或兼容开关实现。

### 实施要求

- 新语义实现完成后，必须在同一任务内删除已被替代且不再使用的旧实现，不得把清理工作无依据地延期到后续任务。
- 删除对象包括适用范围内的旧接口、路由、服务、DTO、状态、字段、表结构、配置项、环境变量、功能开关、读写分支、转换逻辑、操作入口、脚本、测试、fixture、文档和生成文件。
- 不得保留旧新双轨读取、双写、旧 DTO 转换、旧状态兜底、隐藏入口、废弃变量占位或仅为兼容历史调用和历史数据存在的代码。
- 测试应改写为当前语义；已经失效的旧行为测试必须删除。可以保留证明旧入口不可用的否定性回归测试，但不得恢复旧行为。
- 对旧数据不提供运行时读取、转换、回填或兼容能力。需要删除或重建本地测试数据时按任务计划执行；生产或共享环境的数据删除仍须获得针对目标环境和数据范围的明确批准，本规则不构成该授权。

### 完成门禁

- “新功能可用”不等于任务完成。只有旧语义删除、相关计划和维护文档同步、质量门通过后，任务才可验收。
- 完成前必须对仓库执行旧标识符、旧字段、旧路由、旧状态和旧文案的定向检索，并逐项确认剩余命中不存在可执行的旧路径。
- 必须运行任务规定的测试与构建检查，并至少执行 `git diff --check`、`make test`，适用时执行 `make build`。
- 无法确认是否仍被使用的代码不得主观删除；应先追踪调用、数据流和运行入口。确认仍有当前依赖时，必须修正计划或完成依赖迁移后再删除，不得用兼容分支掩盖未完成迁移。

## 所有仓库变更任务的 worktree 闭环

### 基本原则

- `main` 只保存已经集成并验证通过的状态，不直接承载日常业务开发。
- 任何会新增、修改、删除、移动或生成仓库文件的任务，都必须先创建独立分支和专属 git worktree，再开始实施。该要求不因任务很小、只改一个文件、只改文档或配置、属于紧急修复、未创建 Trellis 任务、用户要求“直接修改”而豁免。
- 纯读取、搜索、分析、解释或评审且不会改动仓库文件的任务不需要创建 worktree；一旦准备产生文件变更，必须先停止当前操作并完成 worktree 创建与校验。
- Trellis 决定是否需要建档、规划和运行 `task.py start`；本节只决定代码和文档在哪里修改。若其他项目内工作流允许“小任务直接做”或“不创建 Trellis 任务”，只能解释为可跳过 Trellis 建档，不得解释为可跳过 worktree。遇到其他表述冲突时，AI 必须按此边界自行判断并优先保证所有仓库变更发生在专属 worktree。
- 每个变更任务使用一条短生命周期分支，默认命名为 `codex/<task-slug>`，并配套一个专属 git worktree；分支从已经验证且干净的 `main` 创建，实施全程只在该 worktree 内进行。
- 多个任务允许并行开发，各自占用独立 worktree；任何任务都不得改动主工作区的检出分支、其他 worktree 的工作区，或触碰不属于自己的未提交改动。
- 合并回 `main` 是串行门禁：同一时刻只允许一个任务执行“合并 → `main` 复验”，复验通过后才能合并下一个任务。
- 一个变更任务必须完成“worktree 开发 → 质量检查 → 提交 → 合并回 `main` → `main` 复验 → 适用时完成 Trellis 收尾 → 删除 worktree 与分支”的完整闭环。

### 首次写入前的强制门禁

1. 在执行任何文件写入工具或会改变仓库状态的 shell 命令前，先运行 `git worktree list`、`git status --short`，确认主工作区、所有现有 worktree、`main` 与 `origin/main` 的关系；不得覆盖、stash、reset 或混入不属于当前任务的改动。若发现他人的未提交改动，保持原样，不得用 `git stash -u` 抓取。
2. 确认当前任务已获实施批准；若任务已有 PRD、design、implement 或适用 `.trellis/spec/`，先读取这些材料。没有 Trellis 任务不构成跳过 worktree 的理由。
3. 从最新且验证通过的 `main` 创建任务分支，并在主工作区之外创建专属 worktree，例如 `git worktree add ../blue-benchmark-wt/<task-slug> -b codex/<task-slug> main`；worktree 不得建在主工作区目录内部。禁止在主工作区使用 `git switch -c`、`git checkout -b` 或等价操作直接开始任务。
4. 创建后必须在专属 worktree 中再次运行 `pwd`、`git branch --show-current`、`git status --short` 和 `git worktree list`，确认当前目录是本任务 worktree、当前分支是本任务分支且未混入其他改动。完成这些校验之前，禁止调用写入、编辑、删除、移动、生成文件的工具或命令。
5. 新 worktree 不含主工作区的 `.env`（gitignored）。运行任何测试前必须先从主工作区复制 `.env` 到新 worktree，否则后端测试会因 `SESSION_COOKIE_SECURE` 默认值批量失败。
6. 只有当前任务使用 Trellis 时，才在任务 worktree 内运行 `task.py start`，并确保 `task.json.branch` 为任务分支、`base_branch` 为 `main`；未使用 Trellis 时直接在已校验的 worktree 内实施。
7. 若发现已经在主工作区或错误 worktree 产生了本任务改动，必须立即停止继续修改，保留现场并报告违规状态；先核对改动归属，再将本任务迁移到专属 worktree。不得以“已经开始”为理由继续在错误位置实施。
8. 若 `main` 在开发期间前进，先把最新 `main` 集成回任务分支，解决冲突并在任务 worktree 内重新运行完整质量检查；禁止用 force、hard reset 或跳过验证来制造可合并状态。

### worktree 内开发与提交纪律

- 所有改动、提交、质量检查都只发生在任务 worktree 内；提交前必须 `git status --short` 复查，防止混入与本任务无关的文件。
- 按一个稳定职责一个提交批次组织 commit；不得提交已知失败、半完成迁移、未同步生成文件或无回滚边界的改动。
- 需要临时起服务或跑 E2E 时，用 `E2E_PORT` 等机制避开其他 worktree 与主工作区占用的端口；不得强杀来源不明的监听进程。

### 合并门禁

- 先在任务 worktree 内完成验收标准和 Trellis `trellis-check`。最低验证为 `git diff --check` 与 `make test`；涉及前端、生产构建或跨层运行路径时同时运行 `make build`，任务文档规定的其他命令也必须通过。
- 任务 worktree 工作区干净后，在一个临时 merge worktree 中检出 `main` 执行合并（主工作区可能被其他会话占用，不得直接切换它的分支）：例如 `git worktree add ../blue-benchmark-wt/merge-main main`，在其中执行 `git merge --ff-only codex/<task-slug>`。
- 若不能 fast-forward，返回任务 worktree 集成最新 `main`、重新跑完整质量检查后再合并，不得强行改写 `main` 历史。
- `git branch -d` 等依赖 `main` 作为参照的命令必须在 `main` 被检出的 worktree（如上述临时 merge worktree）中执行，否则会按当前 HEAD 误判合并状态。
- 若远端保护、团队评审或发布流程要求 PR，必须通过 PR 合并，不得绕过保护规则；本地结论不能替代远端合并状态。

### `main` 合并后复验

合并命令成功不等于任务完成。必须在 `main` 上再次确认：

1. `main` 包含本任务的全部提交，且 `git log main..<task-branch>` 为空。
2. 在合并后的 `main`（临时 merge worktree 即可）重新运行该任务的完整质量门；至少执行 `git diff --check`、`make test`，适用时执行 `make build`。
3. 若改动需要进入远端，确认本地 `main` 与 `origin/main` 指向同一已验证提交，并确认 PR/远端分支状态与本地结论一致。
4. 质量门通过后再执行 Trellis 归档和会话记录；不得用 branch test、Preview、文档、HTTP 200 或监听端口冒充 `main` 的合并后验收。

### 删除 worktree 与分支

- 只清理刚完成闭环的当前任务的 worktree 和分支；不得使用通配符或批量删除其他任务的 worktree、分支。
- 删除前必须确认：`main` 复验通过、任务提交已被 `main` 包含、`git log main..<task-branch>` 为空、该 worktree 工作区干净且没有残留的未推送内容。
- 执行顺序：先 `git worktree remove <path>`，再在检出 `main` 的 worktree 中 `git branch -d <task-branch>`；远端分支存在且不受保护时，再删除对应远端分支。不得删除 `main`、`origin/main` 或 `origin/HEAD`。
- 任一门禁失败时保留 worktree 和分支，报告差异、未合并提交或残留改动，不得强删（不得随意使用 `git worktree remove --force` 或 `git branch -D`）。

### 并行任务规则

- 多个子任务可以同时处于“开发中”，每个任务独占一个 worktree 与一条分支，互不干扰。
- 并行任务之间不得互相修改对方 worktree、不得共享未提交改动；若两个任务改动同一片代码产生冲突，后合并者负责在自己的任务分支内集成最新 `main` 并重新验证。
- 启动新任务只要求存在已验证的 `main` 基线，不要求其他任务已完成；但合并与复验必须逐个串行执行。
- 不得把某个任务尚未验收的改动带入另一个任务的 worktree 或提交。
