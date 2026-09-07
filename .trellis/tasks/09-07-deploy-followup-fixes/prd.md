# PRD: 修复部署 followups 缺陷(8 条)

## Goal

修复 blue-benchmark 改名任务对抗审查登记的 8 条 main 既有部署缺陷(归档 `.trellis/tasks/archive/2026-09/09-07-rename-blue-benchmark/followups.md` 第 1-8 条),让首次服务器发版与首次真实恢复可以完全按文档执行成功。这些缺陷与命名无关,是部署文档/工具的既有正确性问题。

用户价值:第一次上服务器发版的运维不会被假表名、被阻挡的卷删除、永远"未知"的 schema 版本、等不到的"全部 healthy"卡死;备份清单恢复其"可核验恢复点"的合同价值。

## Key Decisions

- **F3 方案(schema 版本探测)**:删除 `_discover_schema_version` 的仓库路径扫描(服务器 /opt 布局无 repo 检出,恒返回 None),改为在备份 run 的停写窗口内经既有 `docker compose exec -T postgres psql` 模式(同 `list_databases`)查询业务库 `SELECT version_num FROM alembic_version`;查询失败/无表时记 None(输出"未知"),不中止备份。`load_deploy_config` 不再承担该探测(verify/download 等无 Docker 环境不发起无谓调用),`DeployConfig.business_schema_version` 字段及其在配置日志中的占位随之删除,manifest 构建处传入 run 时查询结果。
- **F2 方案(卷删除被阻挡)**:restore.md 第 7 步在 `docker volume rm -f` 之前插入 `docker compose rm -f api worker`(只删 exited 容器不动卷;nginx 不挂载 appdata),并显式警告禁止 `docker compose down -v`(会连 pgdata 一起删除,使第 5 步在全新空实例上重建、第 8 步 `alembic check` 的报错语义与文档预期完全对不上)。
- **F8 方案(alembic.ini 死配置)**:保留 URL 行(alembic API 要求),在行上方加注释说明该值恒被 `migrations/env.py` 以 `ALEMBIC_DATABASE_URL` 或应用 settings 覆盖、仅作占位;不改 env.py 行为。
- 文档口径修复(F1/F4/F5/F6/F7)以"与代码实际行为一致、首次操作者可执行"为准;不扩展任何新行为。
- `.trellis/spec/deploy/backup-and-runtime.md` 按其自身同步条款(Scope/Trigger)随 F3 更新;"业务 schema 版本"核对项保留(修复后是真实值)。

## Requirements

- R1(P1):restore.md 第 8 步业务数据抽查 `FROM questions` 改为 `FROM eval_questions`(真实表名,backend/app/lib/database/models.py)。
- R2(P1):restore.md 第 7 步按 F2 方案补容器清理步骤与 down -v 禁令警告。
- R3(P2):backup.py schema 版本探测按 F3 方案改为库内 alembic_version 查询;test_deploy_backup.py 的 fake docker 支持该查询并断言 manifest `business_schema_version` 为真实值;探测失败路径返回 None 且不中止备份(补一条失败分支断言)。
- R4(P2):deploy/README.md 与 push-images.sh 的"等待全部 healthy"口径统一为 server-setup.md 实际(api/postgres/web healthy;worker/nginx 仅 Up,无 healthcheck)。
- R5(P3):acr-guide.md "验证:推送一个测试标签"假验证段删除,替换为真实验证流程(对第四步已转存的 nginx:1.27-alpine 标签真实 push 一个 test 标签→确认 ACR 控制台可见→删除远端测试标签)。
- R6(P3):acr-guide.md "REGISTRY 留空会退回 Docker Hub"修正为仅 nginx/postgres 有 compose 默认值可退回;web/api 为裸 `${REGISTRY}/...`,留空即非法镜像引用直接失败,REGISTRY 必须配置。
- R7(P3):compose.yaml 的 `restart: true` 注释与文档版本基线统一:注明 `restart: true` 硬下限 Compose 2.17、项目统一基线 2.20+(与 README/server-setup/restore 一致)。
- R8(P3):alembic.ini 按 F8 方案加死配置注释。
- R9:spec 同步——`.trellis/spec/deploy/backup-and-runtime.md` 中与 F3/F4 相关的合同表述更新;归档 followups.md 属历史记录不改写,在本任务 evidence 中记录 8 条的逐条闭环状态。

## Acceptance Criteria

- [ ] AC1:restore.md 第 8 步抽查 SQL 使用 `eval_questions`;deploy 文档中 `FROM questions` 零命中(排除归档)。
- [ ] AC2:restore.md 第 7 步含 `docker compose rm -f api worker` 与 `down -v` 禁令,顺序在 `docker volume rm -f` 之前。
- [ ] AC3:`_discover_schema_version` 与 `DeployConfig.business_schema_version` 删除;备份 run 在停写窗口内查询 alembic_version 写入 manifest;test_deploy_backup.py 全绿且新增"manifest schema 版本=查询值"与"查询失败→未知且不中止"断言。
- [ ] AC4:deploy 文档与脚本中"等待全部 healthy"类表述零残留,统一为 api/postgres/web healthy + worker/nginx Up 口径。
- [ ] AC5:acr-guide.md 无 `hello-world`/`2>/dev/null || true` 假验证;REGISTRY 留空叙述与 compose.yaml 实际默认值一致。
- [ ] AC6:compose.yaml 注释与三份文档版本基线一致(2.17 硬下限/2.20+ 项目基线);alembic.ini 含覆盖说明注释且 `make db-migrate` 行为不变。
- [ ] AC7:`git diff --check`、`make test`、`make build` 全部通过;spec backup-and-runtime.md 与代码同步。

## Out of Scope

- followups.md 第 9 条 `sep_` 凭证前缀(已显式豁免,需独立立项)。
- 任何新功能、备份合同变更(成员/格式/OSS 布局)、迁移改动。
- 服务器实操(本任务只修仓库内文档与工具)。
- 归档任务文档改写。

## Open Questions

无(F1-F8 修复口径均已由对抗审查报告给出证据,方案见 Key Decisions)。
