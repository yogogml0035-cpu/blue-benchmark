# Implementation Plan: M0 Next.js 前后端交互

## Execution Rule

父任务只维护总合同、依赖顺序和最终集成验收，不直接运行 `task.py start`。五个子任务严格串行：前一子任务必须完成独立分支开发、检查、提交、fast-forward 合并回 `main`、`main` 复验、Trellis 归档和安全删除分支后，下一子任务才能从当前 `main` 创建分支。

每个子任务开始前：

1. 检查当前分支、工作区、所有 worktree、`main` 与 `origin/main`；
2. 确认没有用户未提交改动会与该子任务重叠；
3. 读取父任务 `prd.md`、`design.md`、目标子任务全部规划文件和适用 `.trellis/spec/`；
4. 从已验证且干净的本地 `main` 创建 `codex/<child-slug>`；
5. 只有用户明确批准本最终规划后，才对第一个子任务运行 `task.py start`。

## Dependency Order

```text
Child 1: m0-web-backend-contracts
  -> Child 2: m0-nextjs-shell-auth
    -> Child 3: m0-evaluation-set-credentials-ui
      -> Child 4: m0-question-review-ui
        -> Child 5: m0-local-integration-acceptance
          -> Parent final acceptance
```

## Acceptance Ownership

| Parent criteria | Primary owner | Final verifier |
|---|---|---|
| AC1–AC2 | Child 1 backend + Child 2 UI | Child 5 |
| AC3 | Child 1 backend + Child 3 UI | Child 5 |
| AC4 | Child 1 headers + Child 3 prompt/credential UI | Child 5 |
| AC5–AC6 | Child 3/4 | Child 5 |
| AC7–AC12 | Child 1 state gates + Child 4 workbench | Child 5 |
| AC13 | Child 2/3/4 targeted browser checks | Child 5 full browser pass |
| AC14–AC15 | Child 5 | Parent final acceptance |

每条标准只有一个最终验收者；前置子任务的局部通过不能替代 Child 5 和合并后 `main` 的完整复验。

## Child 1: Backend Web Contracts

Task: `.trellis/tasks/09-03-m0-web-backend-contracts`

Outcome: 在不改变六类材料和两字段评分语义的前提下，让后端可以诚实支撑新 Web 的认证、评测集、人工确认、重新审改和删除门禁。

Implementation batches:

1. Auth bootstrap 与本机密码重置；
2. Scene 更新、空集删除和 CLI 对齐；
3. `0019` review facts migration 与 schema-ready 清单；
4. criteria confirmed、next_action、review reopen、受保护题目删除；
5. 凭证 no-store headers、OpenAPI、README 与全量测试。

Exit gate:

- `git diff --check`
- `make db-migrate && make db-check`（配置数据库）
- `make test`
- `make build`
- `cd backend && uv run pytest tests/test_migration.py tests/test_scenes.py tests/test_question_library_api.py tests/test_adversarial_hardening.py -q`
- fresh DB、0018 upgrade、downgrade 均验证；OpenAPI 无漂移。

## Child 2: Next.js Shell And Auth

Task: `.trellis/tasks/09-03-m0-nextjs-shell-auth`

Dependency: Child 1 已合并，生成 OpenAPI 已包含 bootstrap 与新 review 字段。

Outcome: 建立可构建的 Next.js App Router、类型化 API 边界、AURA 视觉系统、桌面 AppShell 和真实首次注册/登录/会话流程。

Implementation batches:

1. 固定版本的 `frontend/` 工程、pnpm lock、Next rewrite、TypeScript/OpenAPI 生成；
2. API client、错误模型、session boundary 和受保护路由；
3. AURA tokens、共享 UI、可折叠 AppShell；
4. 确定性粒子登录面与首次注册/登录页面；
5. 将 `backend/` 与新 `frontend/` 注册为 Trellis packages，建立首版 frontend API/状态、组件/样式和质量测试规范；
6. auth 单元/组件/Playwright、`1280x720` 与 `1440x900` 视觉验证。

Exit gate:

- `pnpm --dir frontend generate:api`
- `pnpm --dir frontend typecheck`
- `pnpm --dir frontend test`
- `pnpm --dir frontend build`
- auth Chromium/WebKit E2E
- Chrome/Safari 实际登录核对
- `git diff --check`

Child 2 合并后、Child 3 启动前，必须将新建的 `.trellis/spec/frontend/` 索引与相关规范加入 Child 3、4、5 的 `implement.jsonl` / `check.jsonl`，重新运行 `task.py validate`。不得提前在本次规划中引用尚不存在的文件，也不得跳过后续刷新。

## Child 3: Evaluation Set And Credentials UI

Task: `.trellis/tasks/09-03-m0-evaluation-set-credentials-ui`

Dependency: Child 2 壳层、认证和 API client 已合并。

Outcome: 完成 AURA 文件夹式评测集 CRUD、凭证状态与生命周期，以及只显示一次的 Agent 绑定提示词。

Implementation batches:

1. Evaluation Set service、稳定颜色与连接状态派生；
2. 文件夹网格、创建、编辑、空集删除；
3. 凭证签发、轮换、撤销和状态刷新；
4. Agent 提示词模板、瞬时秘密状态、Clipboard/Safari fallback；
5. 极限卡片、凭证安全、Chrome/Safari 与 E2E 验收。

Exit gate:

- 提示词中 token 恰好出现一次；页面关闭/刷新后无法恢复；
- Web Storage、URL、服务端日志和测试 artifact 无 token；
- 20 个评测集在两个桌面视口无溢出；
- 非空删除被 API 拒绝，不能被前端绕过；
- `pnpm --dir frontend typecheck && pnpm --dir frontend test && pnpm --dir frontend build`
- `make test && make build && git diff --check`

## Child 4: Question List And Review Workbench

Task: `.trellis/tasks/09-03-m0-question-review-ui`

Dependency: Child 1 review 状态合同与 Child 2/3 页面壳层已合并。

Outcome: 完成单评测集紧凑题目列表、六类材料双栏详情、动态候选人工选择、手工维度、保存/发布、重开、重生成和安全删除。

Implementation batches:

1. 题目列表服务、搜索/筛选/排序和 200 项稳定列表；
2. 双栏详情、六类材料阅读态、记忆折叠；
3. 材料编辑草稿、离开保护、保存并重新生成和生成轮询；
4. candidate draft、默认未选、手工新增、0–10 控件、保存门禁；
5. 发布、重新打开审改、状态矩阵和题目删除；
6. 长内容、20 维度、错误/竞态与浏览器验收。

Exit gate:

- 未经 `PATCH /criteria` 的 AI 初稿从 UI 和 API 均不能发布；
- 选择/保存/发布分离，刷新后能区分未确认与已保存；
- 材料修改真实触发 production-compatible generation state，不保留旧维度；
- 200 项列表、最长标题/criterion/材料和 20 维度在桌面视口可操作；
- 生成中、失败、待选择、待发布、已发布、重新打开各状态均有测试；
- `pnpm --dir frontend typecheck && pnpm --dir frontend test && pnpm --dir frontend build`
- Chromium 完整 + WebKit 核心 E2E
- `make test && make build && git diff --check`

## Child 5: Local Integration And Acceptance

Task: `.trellis/tasks/09-03-m0-local-integration-acceptance`

Dependency: 前四个子任务均已合并并在 `main` 复验。

Outcome: 将前端、API 和唯一 production Worker 变成一个可重复启动、可安全验收的本地系统，并完成真实上传 Skill/真实 AI/真实浏览器证据。

Implementation batches:

1. 更新根 Makefile、`.gitignore`、README 与前端规范；
2. 一键 `make start-all` 管理三进程，单独调试命令保持可用；
3. 完整 OpenAPI 类型漂移、前后端测试与生产构建门；
4. 隔离数据库/端口的真实 AI Web acceptance runner；
5. Chrome/Safari 实际浏览器、截图、控制台、网络和秘密泄漏审计；
6. 更新 Trellis specs、验收记录和本地操作说明。

Exit gate:

- `make test`
- `make build`
- `make contract-check`
- `cd backend && uv run pytest ../skills/ai-eval-push/tests/ -q`
- `pnpm --dir frontend test:e2e`
- 真实 AI runner 输出 `M0_WEB_ACCEPTANCE=PASS`，且输出/trace/report 不含秘密或材料正文；
- Chrome `1440x900` 全页截图、Chrome/Safari `1280x720` 核心流程无阻断；
- `git diff --check`，工作区只含当前子任务预期改动。

## Parent Final Acceptance

五个子任务全部归档后，在合并后的 `main`：

1. 确认 `git log main..<each-child-branch>` 均为空，且无任务分支被 worktree 占用；
2. 重新运行 Child 5 完整门禁；
3. 逐条核对父 PRD 的 AC1–AC15，并写最终 acceptance record；
4. 核对 OpenAPI、生成 TypeScript、README、Skill 文档、运行时和 UI 文案没有冲突；
5. 只在全部通过后归档父任务，并按项目门禁安全删除已合并分支。

## Rollback Points

- Child 1：回退 API 与 migration；只有未写入依赖新字段的数据时才 downgrade。
- Child 2：可整体移除 `frontend/`，不影响后端业务；不能留下 Makefile 对不存在前端的依赖。
- Child 3：回退评测集 UI 不删除已创建业务数据；一次性凭证无法恢复，只能轮换。
- Child 4：回退 UI 不能回退已保存的老师维度；后端合同与前端生成类型必须同批回退。
- Child 5：启动/验收脚本可独立回退，不修改用户现有生产数据或真实凭证。

任一门禁失败时停止在当前子任务，不创建下一分支，不 force、不 hard reset、不用 Fake 或静态页面替代真实验收。
