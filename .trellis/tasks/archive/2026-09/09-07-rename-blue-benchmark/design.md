# Design: 项目全局重命名为 blue-benchmark

## 1. 命名映射表(唯一权威口径)

| 旧标识 | 新标识 | 形态 | 涉及位置 |
|---|---|---|---|
| `skill-eval-platform`(GitHub 仓库) | `blue-benchmark` | kebab | GitHub 设置 + `git remote set-url`(用户执行) |
| `/Users/hsikey/Company/skill-eval-platform` | `/Users/hsikey/Company/blue-benchmark` | kebab | 本地目录(用户最后手动 mv,见 §5 checklist) |
| `skill-eval-web` / `skill-eval-api`(镜像) | `blue-benchmark-web` / `blue-benchmark-api` | kebab | deploy/push-images.sh、deploy/compose.yaml、frontend/Dockerfile 注释、backend/Dockerfile、deploy 文档 |
| `/opt/skill-eval/`(服务器目录) | `/opt/blue-benchmark/` | kebab | deploy/compose.yaml 注释、deploy/README.md、server-setup.md、restore.md |
| `skill_eval`(Postgres 角色/库) | `blue_benchmark` | snake | .env.example、deploy/.env.production.example、compose.yaml 默认值、backup.sh、restore.md、server-setup.md、脚本/测试 |
| `skill_eval_checkpoint`(库) | `blue_benchmark_checkpoint` | snake | 同上 |
| `skill_eval_session`(Cookie) | `blue_benchmark_session` | snake | backend/app/lib/settings.py、deploy/server-setup.md |
| `Skill Eval Platform API`(app_name) | `Blue Benchmark API` | 品牌例外见 §2 | backend/app/lib/settings.py |
| `storage/skill-eval.db`(sqlite 默认) | `storage/blue-benchmark.db` | kebab | backend/app/lib/settings.py |
| `skill-eval-frontend`(npm 包) | `blue-benchmark-frontend` | kebab | frontend/package.json(pnpm-lock 无自名引用,验证后确定是否需重生成) |
| `skill-eval-platform-backend`(Python 发行名) | `blue-benchmark-backend` | kebab | backend/pyproject.toml + `uv lock` 重生成 uv.lock |
| `skill-eval-platform-postgres`(本地容器) | `blue-benchmark-postgres` | kebab | docker rename(本地操作)+ 文档/测试注释同步 |
| `skill_eval_c5_reset_test` 等测试/验收库名 | `blue_benchmark_c5_reset_test` 等 | snake | backend/tests/*、backend/scripts/accept_*.py、frontend/scripts/real-acceptance.mjs |
| `FORBIDDEN_DB_NAMES` 中 `skill_eval*` | `blue_benchmark*` | snake | accept_skill_push.py:42、accept_real_ai_rubric.py:50、real-acceptance.mjs:45 |
| 硬编码 `/Users/hsikey/Company/skill-eval-platform/...` | 相对仓库根解析,不写死绝对路径 | — | frontend/scripts/real-acceptance.mjs:26,47 及 backend 脚本中同类路径 |
| `skill-eval-platform:operation-worker`(advisory lock salt) | `blue-benchmark:operation-worker` | kebab | backend/app/lib/operations/guard.py(仅运行时互斥键,无持久语义;停机切换下无新旧并发窗口) |
| UI「汽车事业 BenchMark 平台」 | 「蓝标汽车事业 BenchMark 平台」 | 品牌 | frontend/src/app/layout.tsx、app-shell.tsx、(auth)/layout.tsx、globals.css 注释、相关 e2e/vitest 断言 |

文档称呼口径(D9):工程语境 `blue-benchmark`,品牌语境「蓝标汽车事业 BenchMark 平台」,禁止第三形态。

## 2. 一次性切换边界(遵循 AGENTS.md 新旧语义切换规则)

- **删除项**:所有旧命名标识符、默认值、注释、文档口径、硬编码路径,替换即删除,不保留任何 `skill_eval` 读取分支、别名、兼容开关或占位变量。
- **不保留兼容**:Cookie 改名后旧会话自然失效(重新登录即可,本地单管理员,无生产用户);`.env` 旧连接串直接改新值;旧镜像名不存在已推送资产,无需清理 ACR。
- **测试改写**:测试/验收脚本中的旧库名、旧容器名、旧断言全部改写为新语义;不新增"旧名不可用"的否定性回归测试(旧名从未上线,无回归风险面)。
- **git 历史与归档**:不改写 git 历史;`.trellis/tasks/archive/` 保留原样(项目规则);`.trellis/workspace/` 日志为历史记录,保留原样。
- **`sep_` 凭证前缀豁免**:凭证明文前缀 `sep_`(旧英文名首字母缩写)是发行点/机密检测正则/skill/e2e 多方消费的跨层运行时合同,不在本映射表内;因已绑定在途凭证资产且属安全合同,本任务显式豁免不改,决策与后续路径记录在 followups.md 第 9 条。
- **app_name 例外说明**:`Blue Benchmark API` 属工程语境的技术标识(FastAPI docs 标题),不是用户品牌文案,不违反 D9"禁止第三形态"(D9 约束的是中文行文称呼)。

## 3. 数据流与不受影响的合同

- 数据库 schema、迁移文件(0001–0021)、API 路由、DTO、业务逻辑**零改动**——本次只改标识符与文案,不改结构。BUSINESS_SCHEMA_HEAD 不变。
- `alembic.ini` 中如含旧名(script_location、日志名等)按映射表替换;迁移版本号与内容不动。
- OpenAPI 生成链(tools/api-gen)如引用 app_name/包名,重新生成并核对 diff 仅为名称变化。
- deepagents checkpoint 库改名仅影响连接串,checkpoint 表结构与读写逻辑不动。

## 4. 本地数据处置(D6,唯一碰真实数据环节)

顺序(停服务 → 备份 → 改名 → 验证):

1. 停止后端/worker/前端(`make stop` 或杀对应进程),确认无连接占用。
2. 备份:`docker exec skill-eval-platform-postgres pg_dump -U skill_eval skill_eval` 与 `skill_eval_checkpoint` 各导出一份,存 `.trellis/tasks/09-07-rename-blue-benchmark/backups/`(gitignored 或任务外目录,文件入 checklist 记录)。
3. 改名(在容器内 psql 以超级用户执行):
   - `ALTER ROLE skill_eval RENAME TO blue_benchmark;`
   - `ALTER DATABASE skill_eval RENAME TO blue_benchmark;`
   - `ALTER DATABASE skill_eval_checkpoint RENAME TO blue_benchmark_checkpoint;`
4. 容器改名:`docker rename skill-eval-platform-postgres blue-benchmark-postgres`。
5. 更新本地 `.env`(gitignored):DATABASE_URL、CHECKPOINT_DATABASE_URL 中角色/库名替换。
6. 验证:起后端,管理员登录成功,题目/凭证数据可见;`pg_isready -U blue_benchmark -d blue_benchmark` 通过。

回滚:改名失败或验证不过 → 用备份 dump 恢复,或逆向 `ALTER ... RENAME` 回旧名;Git 侧回滚 = revert 任务分支,不合并即无影响。

## 5. 任务后用户手动 checklist(D4/D5,写入任务目录 `cutover-checklist.md`)

验收合并到 main 之后,由用户执行:

1. **GitHub 仓库改名**:仓库 Settings → Rename 为 `blue-benchmark`;本地 `git remote set-url origin https://github.com/yogogml0035-cpu/blue-benchmark.git`;`git fetch` 验证。
2. **关闭所有 ZCode/编辑器会话与终端**(cwd 不得停留在项目目录内)。
3. **mv 目录**:`mv /Users/hsikey/Company/skill-eval-platform /Users/hsikey/Company/blue-benchmark`;同步处理 worktree 根 `../skill-eval-platform-wt/`(如存在残留 worktree,先 `git worktree list` 确认已清理)。
4. **迁移 ZCode 记忆目录**:将 `~/.zcode/cli/memories/projects/skill-eval-platform-712f74b96f571042/` 复制到新项目哈希目录(在新目录打开一次会话生成新哈希后迁入),并更新 MEMORY.md 中涉及旧路径/旧名的行。
5. **重建 .env**:确认 `.env` 随目录迁移仍在(gitignored 文件随 mv 保留),核对连接串已是 `blue_benchmark*`。
6. **Docker 卷/容器核查**:`docker ps -a` 确认 `blue-benchmark-postgres` 正常;compose 项目名如有 `skill-eval` 残留(`docker compose ls`)按新目录名重启。
7. **AGENTS.md worktree 示例路径**:已在任务内改为 `../blue-benchmark-wt/`,无需再动。

## 6. 实施环境(AGENTS.md worktree 闭环)

- 任务分支 `codex/rename-blue-benchmark`,worktree `../skill-eval-platform-wt/rename-blue-benchmark`(注意:worktree 根目录名此刻仍是旧的,目录改名是任务后动作)。
- 新 worktree 必须先从主工作区复制 `.env`(否则后端测试批量失败);但本任务会改 `.env` 连接串口径——**测试用 .env 按新名先行更新**,且本地库改名(§4)必须在跑 `make test` 之前完成,否则涉库测试连不上。实施顺序见 implement.md。
- 合并走临时 merge worktree + `--ff-only`,main 复验 `git diff --check`、`make test`、`make build`。

## 7. 风险

| 风险 | 缓解 |
|---|---|
| 本地库改名瞬间有服务连接 → ALTER DATABASE 失败 | 先停全部服务并 `pg_terminate_backend` 兜底 |
| uv.lock/pnpm-lock 改名后不一致 | `uv lock` 重生成;pnpm 锁文件核验自名引用,必要时 `pnpm install` 重生成 |
| 全仓批量替换误伤归档/历史记录 | 替换范围显式排除 `.trellis/tasks/archive/`、`.trellis/workspace/`、`.git`;逐文件 review diff |
| Cookie 改名导致会话失效 | 预期行为(D8 一次性切换),重新登录即可 |
| 硬编码绝对路径改为相对解析后行为变化 | real-acceptance.mjs 默认值改为基于 `import.meta.dirname`/repo 根解析,跑一次脚本 dry 验证 |
| 主工作区被其他会话占用 | 全程在专属 worktree 实施,合并用临时 merge worktree |
