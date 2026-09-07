# Evidence: 阶段 1 本地数据库/容器改名(2026-09-07)

## 前置状态

- 8000/3000 端口无监听,无 uvicorn/next/celery 进程,`pg_stat_activity` 中目标库零活动连接。

## 备份

- `backups/skill_eval_20260907.dump` — 业务库 `skill_eval`(pg_dump -Fc)。
- `backups/skill_eval_checkpoint_20260907.dump` — checkpoint 库。
- `backups/legacy-test-dbs/*.dump` — 21 个旧名测试/验收遗留库(删除前逐一 dump 存档)。

## 改名操作

- 容器内仅有两个登录角色:`skill_eval`(superuser)、`skill_eval_checkpoint`。因"session user cannot be renamed",创建临时超级用户 `tmp_rename_admin` 执行改名,完成后已 `DROP ROLE`(零残留)。
- `ALTER ROLE skill_eval RENAME TO blue_benchmark;`
- `ALTER ROLE skill_eval_checkpoint RENAME TO blue_benchmark_checkpoint;`
- `ALTER DATABASE skill_eval RENAME TO blue_benchmark;`
- `ALTER DATABASE skill_eval_checkpoint RENAME TO blue_benchmark_checkpoint;`
- `docker rename skill-eval-platform-postgres blue-benchmark-postgres`

## 重要事实修正:业务库并无真实数据

design.md §4 假设"本地 dev 库含真实数据",执行时实测为空:改名前后 `blue_benchmark` 库所有业务表(users/sessions/scenes/scene_credentials/eval_questions/operation_jobs/agent_run_attempts/batch_upload_commands/question_run_threads/question_run_events)均为 0 行,仅 alembic_version=0021_m0_runtime_messages_threads(schema 最新)。推断为此前 C5 重置类任务清空所致。

因此:
- AC4"既有数据完整"以"改名前后行数一致(0/0)、schema 完整、连接可用"为准,数据零丢失成立(原本无数据)。
- AC4"管理员可登录、凭证与题目数据仍在"无法以既有数据验证;阶段 3.6 冒烟改为:新 Cookie 名生效 + 注册首个管理员登录(符合记忆 local-admin-account-reset 的 0 用户路径)。

## 旧名遗留库处置(D8 一次性切换)

- 实测存在 21 个 `skill_eval_*` 测试/验收遗留库(c2/c3/c4/c5/pf 系列,各含 1 个一次性验收账号,均非真实数据)。
- 全部先 dump 至 `backups/legacy-test-dbs/` 再 `DROP DATABASE`,执行后 `pg_database` 仅剩 `postgres`、`blue_benchmark`、`blue_benchmark_checkpoint`。

## 验证

- `pg_isready -U blue_benchmark -d blue_benchmark` → accepting connections。
- `pg_isready -U blue_benchmark_checkpoint -d blue_benchmark_checkpoint` → accepting connections。
- TCP 密码连接(`postgresql://blue_benchmark:***@127.0.0.1:5432/blue_benchmark` 与 checkpoint 同款)均返回正确 current_user/current_database;角色密码未变(`.env` 中口令沿用)。

## .env 更新

- 主工作区与 worktree 两份 `.env` 的 `DATABASE_URL`/`CHECKPOINT_DATABASE_URL` 已替换为 `blue_benchmark*`(gitignored,不入库)。

## 修正与补充(同日后续)

- 阶段 1 删除的 21 个旧名库中有两个实为**测试前置库**(非纯遗留):`skill_eval_c2_runtime_test`(deep-runtime/C4 门控测试)与 `skill_eval_c5_reset_test`(reset 工具门控测试)。已按测试 docstring 以新名重建:
  - `CREATE DATABASE blue_benchmark_c2_runtime_test OWNER blue_benchmark_checkpoint;`
  - `CREATE DATABASE blue_benchmark_c5_reset_test OWNER blue_benchmark;`
  - 重建后后端全量套件:**263 passed, 5 skipped**(剩余 5 个 skip 全部是 `DEPLOY_INTEGRATION_REQUIRED=1` 显式选择加入的部署集成层,与命名无关;改名相关门控测试 0 skip)。
- `make test`(全量,重建前)exit 0:后端 240 passed/28 skipped、前端 vitest 75 passed、contract-check/check-api/typecheck 通过;`make build` exit 0(backend import ok、前端 Compiled successfully)。
- `git diff --check` 通过;全仓 `rg -i 'skill.?eval'`(排除 .git/node_modules/.next/.trellis/tasks/.trellis/workspace/.env/.venv,含 uv.lock)**零命中**(AC1)。
- 品牌检索:`frontend` 内所有「汽车事业 BenchMark 平台」均带「蓝标」前缀(AC2)。
- 锁文件/生成物:`uv lock` 重生成 uv.lock(diff 仅包名区块 55+/55-,无版本漂移);`make openapi` 重生成 openapi.json(diff 仅 title 行);`pnpm generate:api`+`check:api` 通过(generated.ts 无 diff);pnpm-lock.yaml 无自名引用,未重生成。
- 冒烟(AC4 替代路径):worktree 起后端(端口 8000)→ `/healthz` 返回 `"service":"Blue Benchmark API"` → `/api/auth/bootstrap` `registration_available:true` → 注册临时管理员 201 且 `set-cookie: blue_benchmark_session=...`(新 Cookie 名生效)→ 登录 200 → `/api/auth/me` 正常 → `/api/questions` 通过鉴权(返回 scene_id 参数校验错误,证明业务库新名连接与会话链路可用)→ 冒烟后停服并删除临时管理员与 sessions,库恢复 0 用户干净状态。
