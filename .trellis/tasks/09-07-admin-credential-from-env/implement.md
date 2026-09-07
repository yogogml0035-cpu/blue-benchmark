# Implement：管理员账号环境变量化 + 首注流程删除

分支 `codex/admin-credential-from-env`，专属 worktree `../blue-benchmark-wt/admin-credential-from-env`。所有命令在 worktree 根执行（后端命令用 `make -C` / `cd backend` 形式，注意不要 cd 出 worktree 根后不归位）。

## 0. 准备

- [ ] 0.1 主工作区确认干净、`main` 基线已验证；创建 worktree + 分支并校验（pwd / branch / status / worktree list）。
- [ ] 0.2 从主工作区复制 `.env` 到 worktree（否则后端测试批量失败）。
- [ ] 0.3 worktree 内 `task.py start`，确认 `task.json.branch=codex/admin-credential-from-env`、`base_branch=main`。
- [ ] 0.4 `uv sync --project backend --dev`、`pnpm -C frontend install`（worktree 依赖要真装）。

## 1. 后端：env 配置 + 启动 seed

- [ ] 1.1 `app/lib/settings.py`：新增 `admin_username: str = ""`、`admin_password: SecretStr = SecretStr("")`（validation_alias `ADMIN_USERNAME`/`ADMIN_PASSWORD`，before-validator strip）。
- [ ] 1.2 `app/features/auth/repository.py`：`reset_admin_password` 扩展为 `update_admin_credentials(user_id, username, password_hash, *, bump_generation: bool)`（username 更新 + 可选 generation bump + 会话清扫，单事务）。
- [ ] 1.3 `app/features/auth/service.py`：新增 `ensure_admin_from_env()`（空配置 RuntimeError 指明键名；空库插入；username 不同只改名；密码不同覆盖 + bump + 清会话；一致零写入）。
- [ ] 1.4 `app/main.py` lifespan：schema 门禁后调用 `ensure_admin_from_env()`。
- [ ] 1.5 验证：`cd backend && uv run python -c "import app.main"`；临时空 SQLite 起 uvicorn 确认 seed 与登录（手工冒烟，不留文件）。

## 2. 后端：删除旧路径

- [ ] 2.1 `router.py` 删 `GET /auth/bootstrap`、`POST /auth/register`。
- [ ] 2.2 `service.py` 删 `register`、`bootstrap`、`assert_valid_password`、`reset_admin_password`。
- [ ] 2.3 `repository.py` 删 `count_users`（先 grep 确认无他用）。
- [ ] 2.4 `schemas.py` 删 `BootstrapResponse`、`RegisterRequest`、`PASSWORD_MIN_LENGTH`、`PASSWORD_MAX_LENGTH`（先 grep）。
- [ ] 2.5 `scripts/admin_cli.py` 删 `account` 命令组与相关 docstring。
- [ ] 2.6 `scripts/accept_skill_push.py`、`scripts/accept_real_ai_rubric.py`：`auth_service.register(...)` → `ensure_admin_from_env()` + login（env 凭据）。

## 3. 合同再生成

- [ ] 3.1 `make openapi`、`make contract-check`。
- [ ] 3.2 `make frontend-generate-api`（generated.ts 中 register/bootstrap 类型消失）。

## 4. 前端

- [ ] 4.1 删 `src/app/(auth)/register/` 整目录；`(auth)/layout.tsx` 注释同步。
- [ ] 4.2 `src/lib/api/auth.ts` 删 `getBootstrap`、`registerAdmin`。
- [ ] 4.3 `src/app/page.tsx`：去掉 bootstrap 分流，未登录一律 `/login`。
- [ ] 4.4 `login/page.tsx`：删 `registrationOpen`/bootstrap effect/`ADMIN_EXISTS` 跳转/注册链接；账号输入改「用户名」`type="text"`。
- [ ] 4.5 `src/lib/redirect.ts`：`buildAuthUrl` 收窄为 `/login`。
- [ ] 4.6 Vitest：`client.test.ts`（bootstrap/register 用例删除或改写）、`redirect.test.ts` L62 改写。
- [ ] 4.7 `pnpm -C frontend typecheck && pnpm -C frontend test && pnpm -C frontend check:api`。

## 5. 后端测试改写

- [ ] 5.1 `tests/conftest.py`：`pytest_configure` setdefault `ADMIN_USERNAME=admin`、`ADMIN_PASSWORD=platform-admin-password`。
- [ ] 5.2 `tests/helpers.py`：`register_admin` → `login_admin(client)`（`ensure_admin_from_env()` + POST login，返回 user dict）。
- [ ] 5.3 全仓批量改调用点（约 47 处，10 个测试文件）。
- [ ] 5.4 `test_auth_web_contracts.py` 重写：否定回归（register/bootstrap 404）+ seed 三行为（首启建号 / env 覆盖 + 旧会话失效 / 缺 env RuntimeError）+ admin_cli account 组不存在。
- [ ] 5.5 `test_adversarial_hardening.py` 原子注册测试 → seed 幂等/单管理员测试。
- [ ] 5.6 `cd backend && uv run pytest -q` 全绿。

## 6. E2E 与验收脚本

- [ ] 6.1 `e2e/global-setup.ts`：childEnv 注入 `ADMIN_USERNAME=e2e-admin`、`ADMIN_PASSWORD=e2e-admin-password`（或沿用现值，二选一并与 spec 常量一致）。
- [ ] 6.2 删 `e2e/01-auth-register.spec.ts`；`02~04` spec 的 register 分支改为 env 凭据登录；新增/保留「/register 404」断言。
- [ ] 6.3 `frontend/scripts/real-acceptance.mjs`：首注步骤 → env 注入 + 登录。
- [ ] 6.4 `make frontend-e2e`（生产构建路径，注意本机 next dev headless 不水合的既有结论）。

## 7. 配置模板

- [ ] 7.1 `.env.example`：删 `username = *****` / `password = *****`，加 `ADMIN_USERNAME=change-me` / `ADMIN_PASSWORD=change-me`。
- [ ] 7.2 `deploy/.env.production.example`：加同名两键 + 注释。
- [ ] 7.3 主工作区 `.env`（worktree 副本同样改）：`username = admin` / `password = admin` → `ADMIN_USERNAME=admin` / `ADMIN_PASSWORD=admin`。

## 8. 文档

- [ ] 8.1 `README.md`：L17 单管理员、L27 env 说明、L64 成功标记、L73 首次注册/登录、L102 reset-password、L194 Web 级验收 → env 账号口径。
- [ ] 8.2 `deploy/server-setup.md` §9「注册管理员」→「配置 ADMIN_USERNAME/ADMIN_PASSWORD」。
- [ ] 8.3 `deploy/README.md`、`deploy/restore.md` 检索「注册」相关口径并同步。

## 9. 质量门与收尾

- [ ] 9.1 `git diff --check`、`make test`、`make build`。
- [ ] 9.2 定向检索：`register_admin|registration_available|/auth/register|/auth/bootstrap|reset-password|ADMIN_EXISTS|BootstrapResponse|RegisterRequest|assert_valid_password|PASSWORD_MIN_LENGTH`（排除 `.trellis/` 归档与否定回归测试），逐项确认无可执行旧路径。
- [ ] 9.3 真实密码检索：确认提交内容无 `admin/admin` 实值（`.env` 不进 Git；测试/e2e 用专用测试凭据）。
- [ ] 9.4 按批次提交（后端 seed+删除 / 合同再生成 / 前端 / 测试 / e2e / 配置+文档）。
- [ ] 9.5 临时 merge worktree 检出 main → `git merge --ff-only` → main 复验（diff --check + make test + make build）→ Trellis 收尾归档 → 删 worktree 与分支。

## 回滚点

- 每批次独立提交，任一门禁失败 `git revert` 到上一批次；无 schema 变更，数据库无需回滚。
