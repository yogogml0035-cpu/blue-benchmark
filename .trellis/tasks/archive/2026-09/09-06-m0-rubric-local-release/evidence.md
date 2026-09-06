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
- main 复验（切换前最终验证 @2aef270，日志 /tmp/c5-main-*.log）：`git diff --check`=0；`RUNTIME_PG_REQUIRED=1 pytest` 182 passed（PYTEST_EXIT=0）；`make build`=0；`make frontend-e2e` 44 passed（E2E_PORT=3137）；`ai-smoke`（skill_eval_c5_smoke_ckpt）`AI_SMOKE=OK criteria=4 message_delta=3106 elapsed=74.3s`；API 真实验收（skill_eval_c5_accept{,_ckpt}）`ACCEPT_REAL_AI=PASS`；Web 真实验收（skill_eval_c5_web{,_ckpt}）`M0_WEB_ACCEPTANCE=PASS` 含 `worker_restart_recovery_verified events=161`。
- 审查修复提交 d09f13d 合入后（改动仅重置工具与其测试，不触及产品路径）：main 重跑 `git diff --check`、`RUNTIME_PG_REQUIRED=1 pytest`（194 passed）、`make build`、`make ai-smoke`；e2e/API 验收/Web 验收沿用 2aef270 的本次运行证据（增量与产品链路零交集，15→27 个工具定向测试覆盖全部增量）。

## 一次性切换执行记录（授权范围内，2026-09-06）

- 前置状态（dry-run 实测）：skill_eval 4 题/1 场景/1 管理员/2 会话/4 凭证/4 作业；skill_eval_checkpoint 12,843 行（checkpoints 4,415 / blobs 1,573 / writes 6,845 / migrations 10）。
- 停止的自有进程（先复核身份再 TERM 顶层，其 trap 清理全树；未杀任何来源不明进程）：make start-all 树 sh=23992（2026-09-04 15:22 启动）→ uvicorn=23998(:8000)、worker=23997、next dev=24012/next-server=70444(:3000)。停止后 8000/3000 端口均已释放。
- 容器核验：system_identifier=768003422693… 双目标一致（同一实例）。
- 备份（破坏性语句之前完成并校验：容器内 stat 字节比对 + pg_restore --list TOC）：
  - skill_eval：115,959 bytes，sha256=34e05f77c61bae75…
  - skill_eval_checkpoint：10,847,603 bytes，sha256=d6e60139148d63f8…
  - 位置（非 Git 持久目录，0600/0700 权限）：/Users/hsikey/Company/skill-eval-platform-wt/_artifacts/m0-rubric-anchors-evidence/c5/20260906T144505Z/（含 reset-record.json）
- 执行：schema_rebuilt ×2 → business_schema_at_head（0021）→ checkpoint_prepared → `RESET=OK`；工具后核验通过（空题库、schema 就绪、checkpoint_migrations=10 且 checkpoints=0）。
- 切换后独立复核：dry-run 显示 skill_eval 11 表共 1 行（仅 alembic_version）、skill_eval_checkpoint 4 表共 10 行（仅迁移表）；6 个业务源文件 sha256 前后 diff 为空（SOURCE_HASHES_UNCHANGED，/tmp/c5-source-hashes-{before,after}.txt）。
- 未动：Docker volume、数据库角色、`.env` 密钥、其他库（18 个 c2-c5 验收/测试库保留）、`.local-samples`。

## 交付的运行环境

- 代码身份：主工作区 /Users/hsikey/Company/skill-eval-platform @ main（C5 合并后 SHA 见下），生产构建前端（make build 产物 .next）。
- 进程（nohup 脱离会话，日志在 gitignored 的 storage/runtime/）：
  - API：uvicorn app.main:app :8000（uv 包装 72995 → python 72997），日志 storage/runtime/api.log；healthz 返回 `{"status":"ok","persistence":"business database","ai":"production"}`。
  - Worker：python -m app.lib.operations.worker（73004 → 73006），日志 storage/runtime/worker.log（空闲轮询，无错误）。
  - 前端：next-server v16.3.4 :3000（pnpm 73021 → 73032），日志 storage/runtime/frontend.log；GET /login = 200。
- 本地 URL：<http://127.0.0.1:3000>（首次进入按 `/api/auth/bootstrap` 的 registration_available=true 引导创建新的唯一管理员；旧账号/会话/凭证已随授权重置失效）。
- 上传准备：注册后创建评测集 → 「创建凭证」→ 用一次性绑定提示词在本地 Agent 配置 ai-eval-push 技能 → 按新合同批量上传（新维度合同自动生效）。
- 失败诊断：API/Worker/前端日志路径如上；`make db-check` 校验 schema；`make reset-local` 只读复查两库状态；健康检查 `curl http://127.0.0.1:8000/healthz`。
- 重启方式（如需）：杀掉上述三进程后 `make start-all`（开发形态）或按上述三条 nohup 命令（生产形态）。

## 对抗式审查

重置工具专项审查代理（最高安全标准，只读+定向测试+dry-run 实测）结论：发现 1 Critical + 3 Major + 5 Minor，全部在提交 d09f13d 修复并加回归：
- C-1（Critical）：DSN query 参数可绕过白名单（libpq 的 ?host=/?dbname=/?port= 覆盖 authority，实测可把 DROP 打到白名单外目标且备份落在另一实例）→ verify_target 拒绝任何 query/fragment；全部连接改用已验证分量重拼（connect_params/_connect）并断言 current_database() 落点；12 个新拒绝回归（query 注入、大小写、percent-encoding、多路径段、IPv6、驱动前缀、localhost）。
- M-1：容器身份核验只覆盖业务 DSN → 双目标各自核验且要求同一实例。
- M-2：重置后 `GRANT ALL TO PUBLIC` 是权限放大（原库为 PG15+ 默认形态）→ 删除；保留 owner 形态 + checkpoint 角色定向 USAGE,CREATE。
- M-3：备份成功判定弱（docker cp 截断可穿透）→ 容器内 stat 字节数与本地逐字节比对 + `pg_restore --list` TOC 可解析后才信任；备份 0600/目录 0700、PID 后缀防并发覆盖、reset-record 0600、--backup-dir 位于任何 git 工作区即拒绝。
- Minor：未预期异常也输出 RESET=FAIL+回退指引；reset 加 lock_timeout=5s + advisory lock 防并发/迟到写者；README 备份措辞与强化后实现一致；CLI 确认串检查提前到 DSN 解析之前（测试注释同步修正）。
- 审查确认通过项：白名单基础拒绝面（大小写/编码/IPv6/远端/错端口/无凭证/非 PG）、破坏范围（两库内仅项目对象，不触及角色/其他 18 个验收库/volume）、备份先于破坏的代码路径不可绕过、后核验充分（alembic/checkpointer 半程失败必被捕获，RESET=OK 不可能在库不可用时打印）、输出零凭证/零正文泄露、默认备份目录不在任何 git 仓库内、工具未被 make test/启动/迁移引用。
- 审查结论：修复后允许执行真实切换（已按此顺序执行）。

## 边界声明

- 本次授权为一次性旧测试数据处置，不延伸至切换后新上传数据；未动 Docker volume、角色、`.env` 密钥、其他库与 `.local-samples`；未部署公网。
