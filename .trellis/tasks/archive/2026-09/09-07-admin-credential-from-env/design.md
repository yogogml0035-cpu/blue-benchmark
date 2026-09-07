# Design：管理员账号环境变量化 + 首注流程一次性删除

## 决策记录（来自用户访谈 2026-09-07）

| 决策点 | 结论 |
|---|---|
| `.env.example` 密码 | 只放占位符（`change-me`），真实密码只在不进 Git 的 `.env` / 服务器 `.env.production` |
| 改密后数据库同步 | 每次启动以 env 为准自动覆盖（env 是唯一权威） |
| 首注流程 | 整个删除，不留备用入口（符合 AGENTS.md 一次性切换规约） |
| `admin_cli account reset-password` | 一并删除：env 权威下 CLI 改密会被下次启动覆盖，属双源冲突 |

## 边界与合同

### 新增：env → DB 的启动同步（唯一权威方向：env ⇒ users 表）

- `backend/app/lib/settings.py` 新增字段：
  - `admin_username: str = ""`（env `ADMIN_USERNAME`，before-validator strip）
  - `admin_password: SecretStr = ""`（env `ADMIN_PASSWORD`，strip；SecretStr 防日志/repr 泄漏）
  - **不设 pydantic 必填**：settings 模块被 `admin_cli`、`export_openapi` 等脚本导入，导入期硬失败会连累与账号无关的运维命令。缺失校验放在启动 seed 时。
- 新函数 `ensure_admin_from_env()`（放 `app/features/auth/service.py`）：
  1. username/password 任一 strip 后为空 → `RuntimeError("ADMIN_USERNAME / ADMIN_PASSWORD 未配置…")`，API 启动失败（fail fast，错误指明缺失键）。
  2. `repository.get_sole_admin()` 为 None → 用现有 `add_first_user` 原子插入（username=env、email=None、admin_slot="primary"、password_generation=1、pbkdf2 哈希沿用 `_hash_password`）。IntegrityError 竞态返回 False 时回落到更新路径。
  3. 已存在：
     - username 相同且 `_verify_password(env_password, hash)` 通过 → 零写入（每次启动都跑，必须幂等且不做无谓写）。
     - username 不同 → 只改 username（不动 generation，会话按 user_id 绑定不受影响）。
     - 密码验证失败 → 覆盖 hash 且 `password_generation+1` + 同事务删除全部 SessionRow（复用现有 `reset_admin_password` 的原子语义，扩展为 `update_admin_credentials(user_id, username, password_hash, *, bump_generation)`）。
  4. 密码长度：不适用 8–128 交互强度规则（本地开发即用短弱密码）；上限沿用 `LoginRequest.password` 的 128 约束，超长在 seed 时报错而不是静默截断。
- `app/main.py` lifespan：`check_schema_ready` 门禁之后、`yield` 之前调用 `ensure_admin_from_env()`。注意 seed 不受 `database_schema_check_on_startup` 开关影响——schema 缺失时 seed 自然抛错（e2e/测试均先迁移）。
- **不新增迁移**：users 表结构不变（username/email nullable/password_hash/generation/admin_slot 均已存在），只写数据。`BUSINESS_SCHEMA_HEAD` 不动。

### 删除清单（后端）

| 对象 | 位置 | 处置 |
|---|---|---|
| `GET /auth/bootstrap` 路由 | `app/features/auth/router.py` L12-14 | 删除 |
| `POST /auth/register` 路由 | 同上 L17-28 | 删除 |
| `service.register` / `service.bootstrap` | `service.py` L70-84 / L105-112 | 删除 |
| `service.assert_valid_password` / `service.reset_admin_password` | `service.py` L115-139 | 删除（唯一调用方 admin_cli 同删） |
| `repository.count_users` | `repository.py` L84-88 | 删除（仅 bootstrap 使用） |
| `repository.reset_admin_password` | L159-174 | 改造为 `update_admin_credentials`（seed 复用） |
| `BootstrapResponse` / `RegisterRequest` / `PASSWORD_MIN_LENGTH` / `PASSWORD_MAX_LENGTH` | `schemas.py` | 删除（先全仓检索确认无其他引用） |
| `admin_cli account reset-password` | `scripts/admin_cli.py` L122-130、L185-192 | 删除整个 `account` 命令组（组内仅此一条命令） |
| 验收脚本 `auth_service.register(...)` | `accept_skill_push.py` L183-185、`accept_real_ai_rubric.py` L214-217 | 改为 `ensure_admin_from_env()` + `POST /auth/login`（env 凭据） |

`repository.add_first_user` 保留（seed 的插入路径）；`find_by_email` 保留（LoginRequest 仍接受邮箱标识，历史账号 email 为 NULL 时按用户名命中）。

### 删除清单（前端）

| 对象 | 位置 | 处置 |
|---|---|---|
| `/register` 页 | `src/app/(auth)/register/page.tsx` | 删除整目录 |
| `getBootstrap` / `registerAdmin` | `src/lib/api/auth.ts` L12、L21-25 | 删除 |
| 根路由 bootstrap 分流 | `src/app/page.tsx` L13-44 | 简化：`/auth/me` 已登录 → 控制台，否则 → `/login` |
| 登录页注册链接 + `registrationOpen` 状态 + `ADMIN_EXISTS` 跳转 | `login/page.tsx` L25-34、L49-53、L135-141 | 删除 |
| 登录页账号输入 `type="email"`/「邮箱地址」 | `login/page.tsx` L70-88 | 改 `type="text"`/「用户名」（env 账号无邮箱） |
| `buildAuthUrl("/register")` 支持 | `src/lib/redirect.ts` L54-55 | 收窄为仅 `/login` |
| `(auth)/layout.tsx` 注释、Vitest（client.test.ts L26-29/L52、redirect.test.ts L62） | — | 同步改写/删除 |
| `e2e/01-auth-register.spec.ts` | — | 删除整文件 |
| `e2e/02~04` 的 register 分支前置 | L21-22 / L15-16 / L18-19 | 统一改为 env 凭据登录（凭据常量与 global-setup 注入值一致） |
| `e2e/global-setup.ts` childEnv | L91 附近 | 注入 `ADMIN_USERNAME` / `ADMIN_PASSWORD`（测试专用值） |
| `scripts/real-acceptance.mjs` 首注步骤 | — | 改为注入 env + 登录 |

`generated.ts` 不手改：后端合同删除后 `make openapi` + `make frontend-generate-api` 再生成。

### 配置模板

- `.env.example`：删除尾部 `username = *****` / `password = *****` 两行（非 pydantic 兼容格式），新增：
  ```
  ADMIN_USERNAME=change-me
  ADMIN_PASSWORD=change-me
  ```
- `deploy/.env.production.example`：同名两键 + 注释「容器启动时自动写入/覆盖管理员；改密 = 改此处并重启 api」。compose 的 api/worker 均 `env_file: .env`，编排零改动；web 服务不需要（凭据只在后端消费）。
- 主工作区 `.env`（gitignored）：用户手写的 `username` / `password` 两行 → 规范键 `ADMIN_USERNAME` / `ADMIN_PASSWORD`（保留用户选定实值，不进提交）。

### 测试策略

- `backend/tests/conftest.py` `pytest_configure` 增加 `os.environ.setdefault("ADMIN_USERNAME", "admin")` / `("ADMIN_PASSWORD", "platform-admin-password")`（与 helpers 旧密码一致，减小 diff）。
- `helpers.register_admin(client)` → `login_admin(client)`：直接调 `service.ensure_admin_from_env()`（幂等，不依赖 TestClient 是否走 lifespan）+ `POST /auth/login`，返回 user dict。约 47 处调用点批量改名。
- `test_auth_web_contracts.py` 重写：bootstrap/register 正向契约删除，新增否定回归（两路由 404）+ seed 行为测试（空库首启建号、改 env 重启覆盖密码且旧 session 失效、缺 env 启动 RuntimeError）。
- `test_adversarial_hardening.py::test_single_admin_registration_is_atomic` → 改为 seed 幂等/单管理员约束测试（并发 seed 不产生第二账号，admin_slot 唯一约束仍在）。
- admin_cli reset-password 相关测试（L37-129、L153-198）删除，补 `account` 命令组不存在的断言。
- OpenAPI 合同测试 `test_openapi_contract.py`：随 `make openapi` 再生成自然通过。

## 兼容与回滚

- 一次性切换：无兼容层、无双轨读取。旧数据无迁移需求（users 表现有行在首次启动时被 env 值覆盖为唯一权威账号；本地库当前 0 用户，生产库发版时同样被 seed 覆盖——这正是用户要求的语义）。
- 回滚 = Git revert 本任务合并提交 + 重启（数据库无 schema 变更，无需恢复备份）。
- 风险：生产 `.env.production` 忘配 ADMIN_* → api 容器启动失败（fail fast，compose 日志可见），不会静默无管理员运行。server-setup.md 与 deploy/README 写明该前置。

## 执行顺序依赖

settings → seed/删除（后端） → openapi 再生成 → 前端删除 + 类型再生成 → 测试改写 → e2e/验收脚本 → 配置模板 → 文档 → 质量门。后端合同未再生成前不要动前端 `generated.ts` 相关检查。
