# Implementation Plan

## Child 1: Backend domain and API

- [x] 建立单一当前题目模型，保存 `title`、六类材料、当前评分维度、场景归属和生成/发布状态。
- [x] 实现 `0..N` 道题的原子批量收题、场景凭证隔离、`command_id`/`client_case_id` 幂等合同。
- [x] 将评分维度替换为 `criterion + pass_score`，固定 10 分并预留逐项必须及格语义；校验 criterion 必须可执行而非孤立标签。
- [x] 实现上传后自动生成、逐题失败/重试，以及“保存并重新生成”的 revision/CAS 防并发流程。
- [x] 更新 AI adapter、Prompt、Fake fixture 与生产结构化输出，只使用六类材料生成维度。
- [x] 以破坏式 Alembic migration 删除旧业务表并创建新题库结构；不迁移旧业务数据。
- [x] 删除旧手动建题、文件处理、分组/共创、Working Set、版本包、提交和人工评分后端链。
- [x] 更新 API、单元/集成/并发/迁移测试和 `backend/openapi.json`。
- [x] 运行后端测试、编译、OpenAPI、迁移与权限/幂等/泄漏对抗检查。
- [x] 提交、fast-forward 合并回 `main`，在 `main` 复验、归档子任务并安全删除分支。

## Child 2: Backend-only repository

- [x] Delete `frontend/` and root Node/pnpm artifacts that only serve it.
- [x] Remove `FRONTEND_URL`, `draft_url`, frontend CORS assumptions and stale browser routes/documentation.
- [x] Refactor Makefile to backend/API/Worker/OpenAPI/test commands only.
- [x] Move contract drift verification fully to backend artifacts.
- [x] Remove obsolete frontend Trellis specs; update backend/shared specs and README.
- [x] Add an administrator CLI for scene creation and scene credential issue/rotate/revoke/status without exposing stored plaintext tokens.
- [x] Run complete backend tests, OpenAPI verification, compile/import checks and `git diff --check`.
- [x] Commit, fast-forward merge to `main`, rerun gates on `main`, archive child and safely delete branch.

## Child 3: Repository upload Skill

- [x] Create `skills/ai-eval-push` with `SKILL.md`, UI metadata, scripts and focused API reference.
- [x] Implement private config loading, connection status, payload validation and idempotent upload.
- [x] 从当前可见上下文识别 `0..N` 道题，生成辅助 `title`，逐题补齐标准答案并展示老师需要确认的整批预览。
- [x] 对参考样例只整理实际读取的老师材料；由本地 Agent 自动筛选相关、安全的记忆原始片段，不展示记忆逐条预览，并执行路径/秘密泄漏检查。
- [x] Require a teacher-confirmed preview before mutation and enforce six-material privacy boundaries.
- [x] Add script/unit tests with a local fake HTTP server and validate the Skill package.
- [x] Run a real local API HTTP acceptance with a temporary scene-bound credential and approved EvalData input without printing secrets or source bodies.
- [x] Run full repository checks and final adversarial review across permissions, idempotency, recovery, leakage, migration and storage.
- [x] Commit, fast-forward merge to `main`, rerun gates on `main`, archive child and safely delete branch.

## Final parent acceptance

- [x] On `main`, verify clean worktree, no child-only commits, backend test suite, OpenAPI drift, migration head, Skill validation/tests and real HTTP flow.
- [x] Confirm no Node/Next.js dependency, old Rubric field, version-package, human-scoring or legacy authoring entry remains.
- [x] Update specs, archive parent, record journal and safely delete any remaining completed task branch.
