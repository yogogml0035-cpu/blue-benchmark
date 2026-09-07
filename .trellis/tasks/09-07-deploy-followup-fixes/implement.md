# Implement: 修复部署 followups 缺陷(8 条)

执行前提:prd.md Key Decisions 为唯一方案口径;followups.md(归档)第 1-8 条为缺陷证据来源。

## 阶段 0:worktree 准备

- [ ] 0.1 主工作区门禁:`git worktree list`、`git status --short`,确认 main 干净无他人改动。
- [ ] 0.2 `git worktree add ../blue-benchmark-wt/deploy-followup-fixes -b codex/deploy-followup-fixes main`。
- [ ] 0.3 worktree 内复验 pwd/branch/status/worktree list。
- [ ] 0.4 从主工作区复制 `.env` 到 worktree。
- [ ] 0.5 `task.py start`(确认 branch/base_branch)。

## 阶段 1:文档修复(F1/F2/F4/F5/F6/F7)

- [ ] 1.1 restore.md 第 8 步:`FROM questions` → `FROM eval_questions`。
- [ ] 1.2 restore.md 第 7 步:`docker volume rm -f` 前插入 `docker compose rm -f api worker`;引用块补"禁止 `docker compose down -v`"警告及后果说明(pgdata 一并删除 → 第 5 步在全新空实例重建 → 第 8 步 alembic check 报错语义失真)。
- [ ] 1.3 deploy/README.md:定位"等待全部 healthy"/"healthy"类发版观察句,改为 api/postgres/web 应 healthy、worker/nginx 为 Up(与 server-setup.md 口径逐字对齐)。
- [ ] 1.4 push-images.sh 第 5 步 echo:`等待全部 healthy` → `确认 api/postgres/web 为 healthy(worker/nginx 为 Up,无 healthcheck)`。
- [ ] 1.5 acr-guide.md 第四步:删除 `docker tag hello-world ... || true` 假验证,替换为真实验证流程(push 已转存的 nginx 标签为 :test → ACR 控制台确认 → `docker push` 无法删远端标签时在控制台删除 test 标签的提示)。
- [ ] 1.6 acr-guide.md 第四步末尾引用块:REGISTRY 留空叙述改为"仅 nginx/postgres 退回 Docker Hub;web/api 镜像引用会非法直接失败,REGISTRY 必须配置"。
- [ ] 1.7 compose.yaml `restart: true` 注释:改为"硬下限 Compose 2.17;项目统一基线 2.20+(见 README/server-setup/restore)"。

## 阶段 2:代码修复(F3/F8)

- [ ] 2.1 backup.py:删除 `_discover_schema_version` 函数与 `load_deploy_config` 中的调用;删除 `DeployConfig.business_schema_version` 字段及 `__repr__`/日志中的占位;新增 `query_business_schema_version(compose_dir, user, dbname) -> str | None`(`docker compose exec -T postgres psql -U <user> -d <dbname> -Atc "SELECT version_num FROM alembic_version"`,`check=False`,失败/空输出/多行均返回 None);`_run_locked` 在停写确认后(check_write_connections 之后、导出之前)调用并传入 `build_manifest`。
- [ ] 2.2 test_deploy_backup.py:fake docker 脚本支持 `exec -T postgres psql ... alembic_version` 分支(返回可控版本串,支持经环境变量注入失败);新增断言:成功路径 manifest `business_schema_version` == 注入值;失败路径为 None 且备份仍成功完成;删除/改写任何依赖 `DeployConfig.business_schema_version` 或 `_discover_schema_version` 的既有用例。
- [ ] 2.3 alembic.ini:`sqlalchemy.url` 行上方加注释(恒被 migrations/env.py 以 ALEMBIC_DATABASE_URL 或应用 settings 覆盖,仅占位);`make db-migrate` dry 验证行为不变。
- [ ] 2.4 spec 同步:`.trellis/spec/deploy/backup-and-runtime.md` 中 manifest/核对项表述与 F3 新行为一致(schema 版本来源=停写窗口内库内 alembic_version 查询,失败记"未知")。

## 阶段 3:验证门禁

- [ ] 3.1 `git diff --check`。
- [ ] 3.2 `cd backend && uv run pytest -q tests/test_deploy_backup.py tests/test_deploy_runtime.py`(默认层全绿)。
- [ ] 3.3 `make test` + `make build` 全绿。
- [ ] 3.4 AC 检索:`rg -n 'FROM questions' deploy/` 零命中;`rg -n '全部 healthy' deploy/` 零命中;`rg -n 'hello-world' deploy/` 零命中;`rg -n '_discover_schema_version|business_schema_version' deploy/backup.py` 仅剩 manifest 键与 run 路径新函数。
- [ ] 3.5 trellis-check 通过后分批提交(建议:docs 修复 / backup.py+测试+spec 两个批次)。

## 阶段 4:对抗审查与合并

- [ ] 4.1 多智能体对抗审查(至少:文档可执行性走查 + backup.py 代码/测试一致性)至零新发现。
- [ ] 4.2 ff 合并回 main(主工作区检出 main 且干净时直接 `git merge --ff-only`),main 复验 `git diff --check`、`make test`、`make build`。
- [ ] 4.3 evidence.md 记录 followups 1-8 逐条闭环;Trellis 归档、会话记录;删除 worktree 与分支。

## 高危文件/回滚点

- 高危:deploy/backup.py(生产备份工具,manifest 构建链路)、test_deploy_backup.py(fake docker 脚本改动易破坏既有用例)。
- 回滚:任务分支不合并即零影响;backup.py 改动以单提交为回滚边界。
