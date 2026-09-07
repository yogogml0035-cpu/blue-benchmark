# 管理员账号改为环境变量写死并删除首注流程

## Goal

单管理员账号不再走前端首次注册：账号与密码由环境变量 `ADMIN_USERNAME` / `ADMIN_PASSWORD` 写死，后端启动时以 env 为唯一权威自动写入（upsert）users 表；彻底删除注册接口、bootstrap 探针、前端注册页与 CLI 改密入口，`deploy/.env.production.example` 同步适配。

## 背景与动机

- 平台是内部工具、单管理员，首注流程（打开页面→创建账号）对内部使用是多余步骤。
- 用户决策（2026-09-07 访谈确认）：
  1. 账号密码直接写在环境变量里，登录就用这套配置；
  2. `.env.example` 是提交进 Git 的模板，只放占位符，**真实密码只写在 `.env`（gitignored）与服务器 `.env.production`**；
  3. 每次启动以 `.env` 为准自动覆盖数据库中的账号密码（改密码 = 改 `.env` 重启）；
  4. 前端「首次注册/创建账号」流程整个删除，不保留备用入口。

## 旧语义（本任务后不再受支持）

- `POST /api/auth/register` 首次注册接口、`GET /api/auth/bootstrap` 的 `registration_available` 探针；
- 前端 `/register` 注册页、登录页「还没有账号？创建账号」链接、根路由按 bootstrap 分流注册/登录；
- `admin_cli account reset-password` 交互式改密（与「env 为唯一权威」构成双源冲突，一并删除）；
- 密码交互强度校验 `assert_valid_password`（8–128 位）作为注册/CLI 入口的校验；
- 以上入口全部不可用即验收通过，不保留任何兼容层、双轨读取或隐藏入口。

## Requirements

### R1 环境变量即账号权威

- `backend/app/lib/settings.py` 新增 `admin_username` / `admin_password`（env 键 `ADMIN_USERNAME` / `ADMIN_PASSWORD`），读取时 strip。
- 两者任一缺失或为空 → API 启动直接失败并给出明确错误（fail fast），不允许无管理员运行。
- env 密码不适用交互式强度校验（本地开发即用短弱密码），只要求非空；长度上限沿用登录请求的 128 字符约束。

### R2 启动时自动 upsert 管理员

- `app/main.py` lifespan 在 schema 检查通过后执行 `ensure_admin_from_env()`：
  - users 表为空 → 创建唯一管理员（username=env 值、email=NULL、admin_slot="primary"）；
  - 已有管理员 → 若用户名或密码与 env 不一致，覆盖用户名与密码哈希，`password_generation+1` 并撤销全部旧会话（沿用现有原子改密语义）；一致则不做任何写入。
- 不新增数据库迁移：users 表结构不变，只写数据。

### R3 删除首注与双源改密路径

- 删除后端 `register` / `bootstrap` 路由、service 函数、DTO（`RegisterRequest`、`BootstrapResponse`）及仅被它们使用的 repository 函数；保留否定性回归测试（旧接口返回 404）。
- 删除 `admin_cli` 的 `account reset-password` 命令及其 service 依赖（`reset_admin_password`、`assert_valid_password`、`PASSWORD_MIN_LENGTH/PASSWORD_MAX_LENGTH` 若不再被引用）。
- 删除前端 `/register` 页、`getBootstrap` / `registerAdmin` API 封装、登录页注册链接与 bootstrap 分流、根路由注册分支；登录页账号输入改为「用户名」（type=text）。
- `frontend/e2e/01-auth-register.spec.ts` 删除；其余 spec 的注册前置改为直接用 env 账号登录。

### R4 配置模板与部署适配

- `.env.example`：把现有 `username = *****` / `password = *****` 两行规范化为 `ADMIN_USERNAME=change-me` / `ADMIN_PASSWORD=change-me`（占位符，随仓库提交）。
- 本地 `.env`（gitignored，不进提交）：把用户手写的 `username` / `password` 两行规范化为 `ADMIN_USERNAME` / `ADMIN_PASSWORD`，保留用户选定的本地实值（实值只存在于 gitignored 的 `.env`，不出现在任何提交文件）。
- `deploy/.env.production.example`：新增 `ADMIN_USERNAME` / `ADMIN_PASSWORD` 占位符与注释；`deploy/compose.yaml` 的 api/worker 已用 `env_file: .env` 整体注入，无需改编排。
- `deploy/server-setup.md` §9「注册管理员」改写为「在 .env.production 配置 ADMIN_USERNAME/ADMIN_PASSWORD，容器启动自动写入，直接登录」。

### R5 合同、测试与文档同步

- `make openapi` 重新导出 `backend/openapi.json`；`make frontend-generate-api` 重新生成前端类型。
- 后端测试：conftest 注入测试用 `ADMIN_USERNAME/ADMIN_PASSWORD`；`helpers.register_admin` 改为 `login_admin`（幂等 seed + 登录），全部调用点同步改写；注册/bootstrap 正向契约测试删除，改为否定回归 + env 覆盖行为测试（改 env 重启后新密码生效、旧会话失效）。
- E2E：`global-setup.ts` 给隔离后端注入 ADMIN_* env；验收脚本（`accept_skill_push.py`、`accept_real_ai_rubric.py`、`frontend/scripts/real-acceptance.mjs`）从「调 register」改为「seed + env 凭据登录」。
- `README.md` 首注相关段落（领域模型「单管理员」、本地启动成功标记、管理端「首次注册/登录」、管理员 CLI、Web 级验收）全部改为 env 账号口径。

## Acceptance Criteria

- [ ] 空库 + 正确 `.env` 启动 API：users 表出现唯一管理员，`ADMIN_USERNAME/ADMIN_PASSWORD` 可登录，`/api/auth/me` 正常。
- [ ] `ADMIN_USERNAME` 或 `ADMIN_PASSWORD` 缺失/为空时 API 启动失败，错误信息指明缺失键。
- [ ] 修改 `.env` 密码后重启：新密码可登录、旧密码 401、旧 session cookie 失效。
- [ ] `POST /api/auth/register` 与 `GET /api/auth/bootstrap` 返回 404（否定回归测试存在）。
- [ ] 前端无 `/register` 路由（404），根路径未登录时直达 `/login`，登录页无注册链接、账号输入为「用户名」。
- [ ] `admin_cli account reset-password` 命令不存在（`--help` 无该命令）。
- [ ] `.env.example` 与 `deploy/.env.production.example` 含 `ADMIN_USERNAME/ADMIN_PASSWORD` 占位符；真实密码不出现在任何提交文件。
- [ ] `make test`、`make build`、`make contract-check`、`make frontend-check-api`、`git diff --check` 全部通过。
- [ ] 定向检索 `register_admin`、`registration_available`、`/auth/register`、`/auth/bootstrap`、`reset-password`、`ADMIN_EXISTS`：除否定回归测试与 `.trellis` 归档外无可执行旧路径残留。
- [ ] 文档同步：README、deploy/server-setup.md 不再描述首注流程。

## Out of Scope

- 生产服务器实际发版与 `.env.production` 实值配置（用户后续按新文档自行操作）。
- users 表结构变更、多管理员、角色权限。
- HTTPS/域名（既有后续规划，不在本任务）。
