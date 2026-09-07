# Implement: 项目全局重命名为 blue-benchmark

执行前提:design.md §1 映射表为唯一权威口径;所有替换排除 `.git`、`node_modules`、`.next`、`.trellis/tasks/archive/`、`.trellis/workspace/`、`.trellis/tasks/09-07-rename-blue-benchmark/`(本任务文档自身引用旧名属正常)。

## 阶段 0:worktree 准备

- [ ] 0.1 主工作区门禁:`git worktree list`、`git status --short`,确认 main 干净、无他人未提交改动。
- [ ] 0.2 `git worktree add ../skill-eval-platform-wt/rename-blue-benchmark -b codex/rename-blue-benchmark main`。
- [ ] 0.3 进入 worktree 复验:`pwd`、`git branch --show-current`、`git status --short`、`git worktree list`。
- [ ] 0.4 从主工作区复制 `.env` 到 worktree(AGENTS.md 强制步骤)。
- [ ] 0.5 `task.py start`(确认 task.json.branch=codex/rename-blue-benchmark、base_branch=main)。

## 阶段 1:本地数据库/容器改名(design §4,必须在涉库测试之前)

- [ ] 1.1 停止本地后端/worker/前端服务,确认 8000/3000 无监听。
- [ ] 1.2 pg_dump 备份 `skill_eval` 与 `skill_eval_checkpoint`,备份文件路径记录到 evidence.md。
- [ ] 1.3 容器内执行 `ALTER ROLE`/`ALTER DATABASE` × 2(失败则 `pg_terminate_backend` 后重试)。
- [ ] 1.4 `docker rename skill-eval-platform-postgres blue-benchmark-postgres`。
- [ ] 1.5 更新主工作区与 worktree 两份 `.env` 连接串为 `blue_benchmark*`。
- [ ] 1.6 验证:`docker exec blue-benchmark-postgres pg_isready -U blue_benchmark -d blue_benchmark`。

## 阶段 2:仓库内标识替换(按映射表逐层)

- [ ] 2.1 后端核心:`backend/app/lib/settings.py`(cookie/app_name/sqlite 默认)、`backend/app/lib/operations/guard.py`、`backend/alembic.ini`、`backend/pyproject.toml`(name=blue-benchmark-backend)→ `cd backend && uv lock` 重生成 uv.lock。
- [ ] 2.2 后端脚本/测试:accept_skill_push.py、accept_real_ai_rubric.py、reset_local_data.py、m0_samples.py、smoke_ai_provider.py、probe_deep_runtime.py、conftest.py、test_reset_local_data.py、test_question_runtime_postgres.py、test_deep_runtime_postgres.py——库名/容器名/FORBIDDEN_DB_NAMES/注释全替换;硬编码绝对路径改为仓库根相对解析。
- [ ] 2.3 前端:`package.json`(name=blue-benchmark-frontend)、`Dockerfile` 注释、`scripts/real-acceptance.mjs`(DSN 示例、FORBIDDEN_DB_NAMES、ACCEPT_CORPUS_ROOT 默认值去绝对路径);核验 pnpm-lock.yaml 是否含自名引用,含则 `pnpm install` 重生成。
- [ ] 2.4 UI 品牌:layout.tsx(title/description)、app-shell.tsx(wordmark+aria-label)、(auth)/layout.tsx、globals.css 注释 →「蓝标汽车事业 BenchMark 平台」;检索并同步 e2e/vitest 中对旧品牌文案的断言。
- [ ] 2.5 deploy 全套:compose.yaml(镜像/POSTGRES 默认值/healthcheck/注释)、push-images.sh、backup.sh、server-setup.md、restore.md、acr-guide.md、README.md、.env.production.example → 新镜像名/新库名/`/opt/blue-benchmark/`。
- [ ] 2.6 根目录与仓库级:.env.example、README.md、Makefile(如有命中)、AGENTS.md(worktree 示例路径改 `../blue-benchmark-wt/`,并增补 D9 命名口径一句话)、backend/Dockerfile。
- [ ] 2.7 spec 文档:`.trellis/spec/guides/cross-layer-contracts.md` 及其他 spec 命中处。
- [ ] 2.8 OpenAPI 生成链:若 app_name/包名进入 openapi.json/生成类型,重跑生成并核对 diff 仅名称变化。

## 阶段 3:验证与旧语义检索门禁

- [ ] 3.1 `git diff --check`。
- [ ] 3.2 `make test`(全绿;关注涉库测试走 `blue_benchmark*`)。
- [ ] 3.3 `make build`(前端生产构建 + 后端 import 检查)。
- [ ] 3.4 定向检索:`rg -in 'skill.?eval' --hidden -g '!.git' -g '!node_modules' -g '!.next' -g '!.trellis/tasks/archive' -g '!.trellis/workspace' -g '!.trellis/tasks/09-07-rename-blue-benchmark'` → 零命中(AC1)。
- [ ] 3.5 品牌检索:`rg -n '汽车事业' frontend/src` 命中均带「蓝标」前缀(AC2)。
- [ ] 3.6 手工冒烟:起本地服务,管理员登录(新 Cookie 名生效)、题目列表可见、DBeaver 确认库名 `blue_benchmark`(AC4)。
- [ ] 3.7 trellis-check 流程通过后按批次提交(建议:backend / frontend / deploy+docs / 品牌文案 四个提交批次)。

## 阶段 4:合并与 main 复验

- [ ] 4.1 `git worktree add ../skill-eval-platform-wt/merge-main main` → `git merge --ff-only codex/rename-blue-benchmark`。
- [ ] 4.2 main 复验:`git diff --check`、`make test`、`make build`;`git log main..codex/rename-blue-benchmark` 为空。
- [ ] 4.3 Trellis 归档、会话记录;删除任务 worktree 与分支(AGENTS.md 顺序)。

## 阶段 5:任务后用户手动动作(产出 `cutover-checklist.md` 交付)

- [ ] 5.1 编写 `cutover-checklist.md`(design §5 全部内容:GitHub 改名+remote set-url、关会话、mv 目录、记忆目录迁移、.env 核验、Docker/compose 项目名核查)。
- [ ] 5.2 提醒用户:服务器发版实操在目录切换后按新版 deploy 文档继续(AC5)。

## 高危文件/回滚点

- 高危:`backend/app/lib/settings.py`(运行时默认值)、`deploy/compose.yaml`(生产拓扑)、`backend/uv.lock`/`frontend/pnpm-lock.yaml`(锁文件重生成易混入版本漂移——diff 中只允许名称相关行变化)、`frontend/scripts/real-acceptance.mjs`(路径解析逻辑改动)。
- 回滚:阶段 1 数据库 → 备份 dump 恢复或逆向 RENAME;阶段 2-4 代码 → 任务分支不合并即零影响,已合并则 revert 合并提交;锁文件漂移 → `git checkout main -- backend/uv.lock frontend/pnpm-lock.yaml` 后仅手工改名称行。
