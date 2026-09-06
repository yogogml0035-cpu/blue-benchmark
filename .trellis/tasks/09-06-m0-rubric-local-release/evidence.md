# C5 完成证据（本地数据切换与最终交付）

日期：2026-09-06。执行 worktree：/Users/hsikey/Company/skill-eval-platform-wt/m0-rubric-local-release（分支 codex/m0-rubric-local-release，基线 main@7b59736，合入 2aef270）。

## 交付物

- `backend/scripts/reset_local_data.py`：一次性安全重置工具（本任务为当前项目两库处置的唯一执行所有者）。
  - 固定白名单 skill_eval / skill_eval_checkpoint @ 127.0.0.1:5432；非白名单库名/远端主机/缺凭证/非 PG DSN 全部拒绝（8 个参数化拒绝测试）。
  - 默认 dry-run 输出脱敏计划（逐表行数、掩码 DSN）；`--execute` 需精确 `--confirm-targets skill_eval,skill_eval_checkpoint`。
  - 目标库存在第三方活动连接即拒绝（不杀任何进程）；容器与 TCP 端点 system_identifier 核验同一实例；pg_dump（容器内）双库备份并 sha256 校验后才允许破坏性语句；备份/记录写入非 Git 持久目录 `_artifacts/m0-rubric-anchors-evidence/c5/<UTC>/`。
  - 只重建两库 public schema；随后 Alembic 到 head、加密 checkpointer setup、后核验（空题库、schema 就绪、checkpoint_migrations 非空且 checkpoints=0）；输出机器可读 reset-record.json。
  - `make reset-local` 仅为 dry-run 入口；工具不接入 make test/应用启动/普通迁移。
- `backend/tests/test_reset_local_data.py`：15 个定向测试（隔离库 skill_eval_c5_reset_test）：白名单拒绝矩阵、确认串门禁、只读计划、schema 重建、活动连接拒绝、容器备份回环。
- README「本地数据一次性重置」runbook + Makefile reset-local + 规格脚本清单同步。

## SDK 交付前复查

- PyPI 实时核查（2026-09-06）：deepagents 最新正式版仍为 0.7.13、langgraph-checkpoint-postgres 仍为 3.1.2，与锁定版本一致，无需升级重验。

## 质量门与 main 复验

- 分支：`git diff --check`=0；`RUNTIME_PG_REQUIRED=1 pytest` 182 passed / 0 skip（167+15 新增）；`make build`=0；`make frontend-e2e` 44 passed（E2E_PORT=3135）。
- 合并：主工作区 ff 至 main@2aef270，`git log main..branch` 为空。
- main 复验（切换前最终验证，日志 /tmp/c5-main-*.log）：待填（pytest/build/e2e/ai-smoke/API 验收/Web 验收）。

## 一次性切换执行记录（授权范围内）

- 前置状态（dry-run 实测）：skill_eval 4 题/1 场景/1 管理员/4 凭证/4 作业；skill_eval_checkpoint 4,415 checkpoints（blobs 1,573 / writes 6,845 / migrations 10）。
- 停止的自有进程：待填（PID 清单，均为 2026-09-04 启动的 make start-all 树）。
- 备份位置与 sha256：待填。
- 执行输出与后核验：待填。
- 源文件保护：待填（切换前后 6 个业务源文件 sha256 复核）。

## 交付的运行环境

- 待填：API/Worker/前端进程身份、端口、代码 SHA、本地 URL、首次注册与上传指引、失败诊断入口。

## 对抗式审查

- 待填。

## 边界声明

- 本次授权为一次性旧测试数据处置，不延伸至切换后新上传数据；未动 Docker volume、角色、`.env` 密钥、其他库与 `.local-samples`；未部署公网。
