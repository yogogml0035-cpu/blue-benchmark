# Evidence: 修复部署 followups 缺陷(8 条)

## followups 逐条闭环(来源:归档 09-07-rename-blue-benchmark/followups.md 第 1-8 条)

| # | 缺陷 | 修复 | 验证 |
|---|---|---|---|
| 1 | restore.md 抽查假表名 `questions` | 改为 `eval_questions`(restore.md:208) | 与 models.py:101 `__tablename__` 一致;`rg 'FROM questions' deploy/` 零命中(AC1) |
| 2 | volume rm 被 exited 容器阻挡 + down -v 歧路 | 第 7 步插入 `docker compose rm -f api worker`(restore.md:179,先于 :183 volume rm);引用块补 down -v 禁令与直接后果(第 6 步导入数据随 pgdata 丢失→回第 5 步重做→第 8 步报错语义失真) | R1 文档代理走查 0-12 步无断点;postgres 无 depends_on,第 5 步不会重建 api/worker;第 9 步 `up -d` 全图自动重建被 rm 容器 |
| 3 | backup.py schema 版本探测路径恒失败 | 删除 `_discover_schema_version` 与 `DeployConfig.business_schema_version`;新增 `query_business_schema_version`(backup.py:887,停写窗口内 compose-exec psql 查 alembic_version,check=False,非零/空/多行→None);run 路径 :1360 调用、:1399 入 manifest | 测试 66 passed(新增成功断言 :644=注入值、失败断言 :670=None 且不中止);spec 同步;R1 代码代理 7 项全 PASS |
| 4 | "等待全部 healthy"不可达 | README:54、push-images.sh:61 改为逐服务口径(api/postgres/web healthy;worker/nginx Up 无 healthcheck) | 与 server-setup.md:158 一致;`rg '全部 healthy|全部健康'` 零命中 |
| 5 | acr-guide 假验证段 | 删除 hello-world+`|| true` 段,替换为真实 push nginx:test → 控制台确认 → 控制台删除流程(acr-guide.md:54-62) | nginx 仓库在第二步创建清单内;`rg hello-world deploy/` 零命中 |
| 6 | REGISTRY 留空叙述半真半假 | 改为:仅 nginx/postgres 有 compose 默认值可退回;web/api/worker 裸 `${REGISTRY}/...` 留空即非法引用直接失败,REGISTRY 必须配置(acr-guide.md:85-88) | 与 compose.yaml:12/35/48/67/79 逐项一致 |
| 7 | compose 注释 2.17 vs 文档 2.20+ | compose.yaml:20-22 注明 restart:true 硬下限 2.17、项目统一基线 2.20+ | 五处版本数字核对一致(compose/README:61/server-setup:35,42/restore:51/spec:29) |
| 8 | alembic.ini 死配置误导 | sqlalchemy.url 上方加注释:占位值,恒被 migrations/env.py 以 ALEMBIC_DATABASE_URL 或 settings.database_url 覆盖(online/offline 均如此) | env.py:17-19 模块加载时无条件 set_main_option,offline(get_main_option)/online(engine_from_config) 均读覆盖后值;不改 env.py 行为 |

第 9 条(sep_ 凭证前缀)按改名任务既定豁免不在本任务范围(见 prd.md Out of Scope)。

## 质量门

- `git diff --check`:通过(worktree 与 main...HEAD 均无空白错误)。
- `make test`:exit 0——后端 **264 passed, 5 skipped**(新增 1 个 schema 版本失败路径用例;5 skip 均为 DEPLOY_INTEGRATION_REQUIRED 显式选择加入型)、前端 vitest **75 passed**、contract-check/check-api/typecheck 通过。
- `make build`:exit 0(backend import ok、前端 Compiled successfully)。
- 专项:`uv run pytest tests/test_deploy_backup.py tests/test_deploy_runtime.py` → 70 passed, 5 skipped(R1 代码代理独立复跑)。
- AC 检索:AC1/AC4/AC5 零命中;AC4 补扫中文变体时发现 README:177「确认全部健康」残留(见下)已修。

## 对抗式审查

- **R1(2 并行代理:文档可执行性走查 + backup.py 重构一致性)**:代码侧 7 项全 PASS、判定"可合并"(含 run_cmd check=False 语义、redact/stderr 无泄漏、多 head/空表/NOTICE 边界、EVENTS 顺序断言不受新查询事件影响、无漏删引用、spec 逐词一致);文档侧 1 FAIL——**README.md:177「确认全部健康」中文变体躲过了 `全部 healthy` 检索式**(main 既有残留,属 AC4 口径),另指出 restore.md down -v 警告时序措辞小瑕疵。
- **修正(f27e21f)**:README:177 改逐服务口径;down -v 警告改为"直接后果优先"表述(第 6 步导入数据丢失→回第 5 步重做);AC4 检索式补 `全部健康` 变体后零命中(restore.md:224 的 `等待.*healthy` 命中经 R2 判定为目标口径本身,误报)。
- **R2(收敛验证代理)**:f27e21f 逐行核对 PASS;deploy/ 全部"健康/healthy"命中逐个判定均为正确口径;AC1-AC7 全 PASS;`git diff main...HEAD --stat` 仅 9 个范围内文件+任务目录,无任务外改动;**零新发现,收敛,可合并**。

## 提交

| Hash | 内容 |
|---|---|
| e0d017a | fix(deploy): 文档修复(F1/F2/F4/F5/F6/F7/F8 文档侧) |
| 5aee8b7 | fix(deploy): backup.py schema 版本改库内查询 + 测试 + spec(F3) |
| 2d7ae40 | docs(task): 任务规划工件 |
| f27e21f | fix(deploy): R1 修正(README 中文变体 + down -v 措辞) |
