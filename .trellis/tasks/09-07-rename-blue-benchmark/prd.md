# PRD: 项目全局重命名为 blue-benchmark

## Goal

将项目中一切与 skill-eval / skill-eval-platform 相关的命名一次性切换为 blue-benchmark 体系,并把 UI 品牌统一为「蓝标汽车事业 BenchMark 平台」。动机:"skill-eval" 过于狭隘,无法承载平台长期定位;"blue" 语义来源为蓝标。

用户价值:工程命名与产品定位一致;服务器从首次发版起只有 blue-benchmark 命名,永不产生旧名资产;消除命名口径漂移。

## Background(仓库证据,2026-09-07 摸底)

旧命名影响面约 60 个文件,分五层:

1. **仓库与目录**:GitHub remote `yogogml0035-cpu/skill-eval-platform`;本地目录 `/Users/hsikey/Company/skill-eval-platform`。
2. **Docker 镜像与部署**:镜像 `skill-eval-web` / `skill-eval-api`(`deploy/push-images.sh:42-49`、`deploy/compose.yaml:30,43,62`);服务器目录 `/opt/skill-eval/`(`deploy/compose.yaml:8` 及 deploy 文档);本地 dev 容器 `skill-eval-platform-postgres`。
3. **数据库与运行时标识**:Postgres 角色/库 `skill_eval`、`skill_eval_checkpoint`(`.env.example:27,33`、`deploy/.env.production.example:17-27`、`deploy/compose.yaml:76-82`、`deploy/backup.sh:31`、restore/server-setup 文档);Cookie `skill_eval_session`、`app_name = "Skill Eval Platform API"`、sqlite 默认 `skill-eval.db`(`backend/app/lib/settings.py:12-17`);验收脚本 `FORBIDDEN_DB_NAMES` 硬编码(`backend/scripts/accept_skill_push.py:42`、`backend/scripts/accept_real_ai_rubric.py:50`、`frontend/scripts/real-acceptance.mjs:45`)。
4. **包名**:前端 `skill-eval-frontend`(package.json);后端 `skill-eval-platform-backend`(pyproject.toml + uv.lock:1236;代码以 `app` 包名 import,发行名可安全改)。
5. **文档**:README.md、AGENTS.md、deploy/*.md、`.trellis/spec/guides/cross-layer-contracts.md`、backend 脚本/测试注释、硬编码绝对路径(`frontend/scripts/real-acceptance.mjs:26,47`)。

前端用户可见品牌已是「汽车事业 BenchMark 平台」(`frontend/src/app/layout.tsx:7`、`app-shell.tsx:31-32`、globals.css),不含 skill-eval 字样。

服务器状态(用户 2026-09-07 确认):镜像未推送 ACR、服务器未建库无数据、`/opt/skill-eval/` 未创建——**零已部署资产,干净切换,无需迁移方案**。本地 dev 库(Docker 容器 `skill-eval-platform-postgres`)含真实数据,是唯一需要保数据的环节。

## Key Decisions

- D1:命名两层分离——**blue-benchmark 为统一工程名**(仓库、镜像、数据库、文档);**UI 品牌**为「蓝标汽车事业 BenchMark 平台」。
- D2:UI 品牌文案修改纳入本任务(layout.tsx、app-shell.tsx wordmark/aria-label 等)。
- D3:服务器零落地,干净切换;发版顺序 = 先完成本重命名,再继续服务器发版实操。
- D4:GitHub 仓库名改为 `blue-benchmark`,改后 `git remote set-url`。
- D5:本地目录改为 `/Users/hsikey/Company/blue-benchmark`,**作为任务最后一步**由用户关闭所有会话后手动执行(mv 目录 + 迁移 ZCode 记忆目录 + 重建 .env);本任务产出该 checklist,并清理仓库内硬编码绝对路径。
- D6:本地 dev 库保数据原地改名:pg_dump 备份 → `ALTER ROLE skill_eval RENAME TO blue_benchmark` → `ALTER DATABASE skill_eval RENAME TO blue_benchmark`(checkpoint 库同理)→ `docker rename` 容器 → 更新本地 `.env`。
- D7:拼写双形态——kebab-case `blue-benchmark` 用于仓库/镜像/目录/文档;snake_case `blue_benchmark` 用于数据库/角色/Cookie/Python 标识。
- D8:一次性彻底切换。不留兼容分支、不兼容历史数据/变量/操作;完成前全仓定向检索零可执行旧命名残留(归档除外)。
- D9:文档中文称呼口径——工程语境直呼 `blue-benchmark`,品牌语境用「蓝标汽车事业 BenchMark 平台」,**禁止第三形态**;该规则一句话写入 AGENTS.md。

## Requirements

- R1 工程命名切换:按 D7 口径将仓库内全部 skill-eval/skill_eval 标识替换为 blue-benchmark/blue_benchmark,覆盖镜像名、Postgres 角色/库名、Cookie 名、app_name、sqlite 默认路径、前后端包名、验收脚本 FORBIDDEN_DB_NAMES、测试库名、Makefile/compose/deploy 脚本与文档。
- R2 UI 品牌切换:用户可见品牌统一为「蓝标汽车事业 BenchMark 平台」(页面 title/description、wordmark、aria-label、相关 e2e 断言)。
- R3 文档口径切换:README、AGENTS.md、deploy 全套文档、`.trellis/spec/guides/cross-layer-contracts.md` 按 D9 口径改写;AGENTS.md 增补 D9 命名规则;worktree 示例路径随 D5 更新。
- R4 本地数据处置:按 D6 执行本地 dev 库与容器改名,数据零丢失;本地 `.env`(gitignored)连接串同步更新。
- R5 仓库外壳改名:GitHub 仓库改名 + remote set-url(D4);本地目录改名 checklist 写入任务文档(D5),含 ZCode 记忆目录迁移与 `.env` 重建步骤。
- R6 旧语义删除(D8):同一任务内删除/改写所有旧命名标识、死配置、硬编码旧路径;测试改写为新语义;不保留任何旧命名读取分支或兼容开关;不改写 git 历史。

## Acceptance Criteria

- [ ] AC1:全仓定向检索 `skill.?eval`(含 `skill_eval`、`skill-eval`,大小写不敏感,排除 `.git`/`node_modules`/`.next`/`.trellis/tasks/archive/` 与本任务文档)零命中。
- [ ] AC2:UI 可见品牌全部为「蓝标汽车事业 BenchMark 平台」;检索旧文案「汽车事业 BenchMark 平台」(不带"蓝标"前缀)零命中。
- [ ] AC3:`git diff --check`、`make test`、`make build` 全部通过。
- [ ] AC4:本地 dev 库以新名 `blue_benchmark`/`blue_benchmark_checkpoint` 可用,既有数据完整(管理员可登录、凭证与题目数据仍在);备份 dump 文件存在。
- [ ] AC5:deploy 文档按新命名可直接执行发版(镜像 `blue-benchmark-web/api`、服务器目录 `/opt/blue-benchmark/`、库 `blue_benchmark*`),且文档中无任何旧名步骤。
- [ ] AC6:GitHub 仓库已改名且 `git remote -v` 指向新 URL;本地目录改名 checklist(含记忆迁移、.env 重建)已写入任务文档。
- [ ] AC7:AGENTS.md 含 D9 命名口径规则一句话。

## Out of Scope

- `.trellis/tasks/archive/` 历史归档文档(按项目规则保留原样,不改写)。
- git 历史改写(filter-repo 等)。
- 本地目录改名、GitHub 仓库改名的**执行动作**本身(由用户在任务验收后按 checklist 手动执行;本任务只改仓库内容并产出 checklist)。
- ZCode 记忆文件内容的口径更新(目录迁移后由助手会话另行处理)。
- 与命名无关的功能改动;服务器发版实操(改名完成后按新文档继续)。

## Open Questions

无(全部决策已由用户确认,D1–D9)。
