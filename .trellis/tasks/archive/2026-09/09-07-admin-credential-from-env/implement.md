# Implement：管理员账号环境变量化 + 首注流程删除

分支 `codex/admin-credential-from-env`，专属 worktree `../blue-benchmark-wt/admin-credential-from-env`。所有命令在 worktree 根执行（后端命令用 `make -C` / `cd backend` 形式，注意不要 cd 出 worktree 根后不归位）。

## 0. 准备

- [x] 0.1 主工作区确认干净、`main` 基线已验证；创建 worktree + 分支并校验（pwd / branch / status / worktree list）。
- [x] 0.2 从主工作区复制 `.env` 到 worktree（否则后端测试批量失败）。
- [x] 0.3 worktree 内 `task.py start`，确认 `task.json.branch=codex/admin-credential-from-env`、`base_branch=main`。
- [x] 0.4 `uv sync --project backend --dev`、`pnpm -C frontend install`（worktree 依赖要真装）。

## 1. 后端：env 配置 + 启动 seed

- [x] 1.1 `app/lib/settings.py`：新增 `admin_username: str = ""`、`admin_password: SecretStr = SecretStr("")`（validation_alias `ADMIN_USERNAME`/`ADMIN_PASSWORD`，before-validator strip）。
- [x] 1.2 `app/features/auth/repository.py`：`reset_admin_password` 扩展为 `update_admin_credentials(user_id, username, password_hash, *, bump_generation: bool)`（username 更新 + 可选 generation bump + 会话清扫，单事务）。
- [x] 1.3 `app/features/auth/service.py`：新增 `ensure_admin_from_env()`（空配置 RuntimeError 指明键名；空库插入；username 不同只改名；密码不同覆盖 + bump + 清会话；一致零写入）。
- [x] 1.4 `app/main.py` lifespan：schema 门禁后调用 `ensure_admin_from_env()`。
- [x] 1.5 验证：`cd backend && uv run python -c "import app.main"`；临时空 SQLite 起 uvicorn 确认 seed 与登录（手工冒烟，不留文件）。

## 2. 后端：删除旧路径

- [x] 2.1 `router.py` 删 `GET /auth/bootstrap`、`POST /auth/register`。
- [x] 2.2 `service.py` 删 `register`、`bootstrap`、`assert_valid_password`、`reset_admin_password`。
- [x] 2.3 `repository.py` 删 `count_users`（先 grep 确认无他用）。
- [x] 2.4 `schemas.py` 删 `BootstrapResponse`、`RegisterRequest`、`PASSWORD_MIN_LENGTH`、`PASSWORD_MAX_LENGTH`（先 grep）。
- [x] 2.5 `scripts/admin_cli.py` 删 `account` 命令组与相关 docstring。
- [x] 2.6 `scripts/accept_skill_push.py`、`scripts/accept_real_ai_rubric.py`：`auth_service.register(...)` → `ensure_admin_from_env()` + login（env 凭据）。

## 3. 合同再生成

- [x] 3.1 `make openapi`、`make contract-check`。
- [x] 3.2 `make frontend-generate-api`（generated.ts 中 register/bootstrap 类型消失）。

## 4. 前端

- [x] 4.1 删 `src/app/(auth)/register/` 整目录；`(auth)/layout.tsx` 注释同步。
- [x] 4.2 `src/lib/api/auth.ts` 删 `getBootstrap`、`registerAdmin`。
- [x] 4.3 `src/app/page.tsx`：去掉 bootstrap 分流，未登录一律 `/login`。
- [x] 4.4 `login/page.tsx`：删 `registrationOpen`/bootstrap effect/`ADMIN_EXISTS` 跳转/注册链接；账号输入改「用户名」`type="text"`。
- [x] 4.5 `src/lib/redirect.ts`：`buildAuthUrl` 收窄为 `/login`。
- [x] 4.6 Vitest：`client.test.ts`（bootstrap/register 用例删除或改写）、`redirect.test.ts` L62 改写。
- [x] 4.7 `pnpm -C frontend typecheck && pnpm -C frontend test && pnpm -C frontend check:api`。

## 5. 后端测试改写

- [x] 5.1 `tests/conftest.py`：`pytest_configure` setdefault `ADMIN_USERNAME=admin`、`ADMIN_PASSWORD=platform-admin-password`。
- [x] 5.2 `tests/helpers.py`：`register_admin` → `login_admin(client)`（`ensure_admin_from_env()` + POST login，返回 user dict）。
- [x] 5.3 全仓批量改调用点（约 47 处，10 个测试文件）。
- [x] 5.4 `test_auth_web_contracts.py` 重写：否定回归（register/bootstrap 404）+ seed 三行为（首启建号 / env 覆盖 + 旧会话失效 / 缺 env RuntimeError）+ admin_cli account 组不存在。
- [x] 5.5 `test_adversarial_hardening.py` 原子注册测试 → seed 幂等/单管理员测试。
- [x] 5.6 `cd backend && uv run pytest -q` 全绿。

## 6. E2E 与验收脚本

- [x] 6.1 `e2e/global-setup.ts`：childEnv 注入 `ADMIN_USERNAME=e2e-admin`、`ADMIN_PASSWORD=e2e-admin-password`（或沿用现值，二选一并与 spec 常量一致）。
- [x] 6.2 删 `e2e/01-auth-register.spec.ts`；`02~04` spec 的 register 分支改为 env 凭据登录；新增/保留「/register 404」断言。
- [x] 6.3 `frontend/scripts/real-acceptance.mjs`：首注步骤 → env 注入 + 登录。
- [x] 6.4 `make frontend-e2e`（生产构建路径，注意本机 next dev headless 不水合的既有结论）。

## 7. 配置模板

- [x] 7.1 `.env.example`：删 `username = *****` / `password = *****`，加 `ADMIN_USERNAME=change-me` / `ADMIN_PASSWORD=change-me`。
- [x] 7.2 `deploy/.env.production.example`：加同名两键 + 注释。
- [x] 7.3 主工作区 `.env`（worktree 副本同样改）：手写 `username` / `password` 行 → 规范键 `ADMIN_USERNAME` / `ADMIN_PASSWORD`（保留本地实值，不进提交）。

## 8. 文档

- [x] 8.1 `README.md`：L17 单管理员、L27 env 说明、L64 成功标记、L73 首次注册/登录、L102 reset-password、L194 Web 级验收 → env 账号口径。
- [x] 8.2 `deploy/server-setup.md` §9「注册管理员」→「配置 ADMIN_USERNAME/ADMIN_PASSWORD」。
- [x] 8.3 `deploy/README.md`、`deploy/restore.md` 检索「注册」相关口径并同步。

## 9. 质量门与收尾

- [x] 9.1 `git diff --check`、`make test`、`make build`。
- [x] 9.2 定向检索：`register_admin|registration_available|/auth/register|/auth/bootstrap|reset-password|ADMIN_EXISTS|BootstrapResponse|RegisterRequest|assert_valid_password|PASSWORD_MIN_LENGTH`（排除 `.trellis/` 归档与否定回归测试），逐项确认无可执行旧路径。
- [x] 9.3 真实密码检索：确认提交内容无 `admin/admin` 实值（`.env` 不进 Git；测试/e2e 用专用测试凭据）。
- [x] 9.4 按批次提交（后端 seed+删除 / 合同再生成 / 前端 / 测试 / e2e / 配置+文档）。
- [x] 9.5 临时 merge worktree 检出 main → `git merge --ff-only` → main 复验（diff --check + make test + make build）→ Trellis 收尾归档 → 删 worktree 与分支。

## 回滚点

- 每批次独立提交，任一门禁失败 `git revert` 到上一批次；无 schema 变更，数据库无需回滚。

## 证据记录（2026-09-07）

- 分支终轮门禁（worktree，f781db9 前）：backend pytest 267 passed / 5 skipped；contract-check current；frontend typecheck+75 vitest+check:api 全过；make build 过（路由表无 /register）；make frontend-e2e 38 passed。
- 对抗审查（trellis-check 子代理）：7 项核查，2 必修（screenshot-auth.mjs 残留 /register 截图路由；server-setup.md §5 清单缺 ADMIN_*）+ 1 建议（128 上限 seed 测试）→ 全部修复于 f781db9。
- main 合并后复验（ff 至 f781db9，main..branch 为空）：git diff --check 干净；make test 全绿（267 passed）；make build 通过（需先清一次陈旧 .next 缓存，属构建产物非代码问题）；make frontend-e2e 38 passed。
- 真实密码检索：提交内容无本地实值；任务文档中的字面凭据已脱敏；.env 不入库（git check-ignore 验证）。
- origin/main 为旧备份，按既有约定不推送。
