# C4 完成证据（真实集成、冒烟与故障恢复验收）

日期：2026-09-06。执行 worktree：/Users/hsikey/Company/skill-eval-platform-wt/m0-rubric-system-validation（分支 codex/m0-rubric-system-validation，基线 main@dcc1a64）。

## 交付内容

- `backend/tests/test_c4_fault_injection.py`：4 个矩阵故障注入回归——失租晚到写者不得提交/不得发完成事件；跨题生成输入与 thread 隔离（业务层）；SSE 晚订阅完整回放+游标语义+终态帧；双 thread 删除历史 + 持续性部分清理崩溃（预算耗尽→终态 failed→冻结可见→教师重试幂等续删→双 thread 零残留）。
- `frontend/scripts/real-acceptance.mjs` 扩展：真实 Worker 进程击杀→租约过期→新 Worker 重启→`thread_state_incomplete` 恢复证明（且 `run_started` 不多于一次=初始输入不重复）；生成中晚订阅快照回放；页面刷新时间线恢复且不触发第二次生成；OPERATION_LEASE_SECONDS=20 加速失租。
- C3 归档证据补记 main 复验结果（dcc1a64）。

## 矩阵覆盖映射（design.md 测试矩阵 → 证据）

| 类别 | 覆盖 |
| --- | --- |
| 合同与审改（建议分锚点/任意整数/依据保留/取消确认重生成） | test_question_runtime_contract.py（编辑合同、stale 提示、手工空辅助）、E2E 04 spec（取消零请求/确认一次）、accept_real_ai_rubric（5 分保存+依据不改写） |
| 真实传输（生成中订阅/晚订阅/刷新/终态） | accept-web 5a/5b（live 增量、晚订阅回放、刷新恢复）、test_c4 晚订阅 SSE 全回放+done 帧 |
| 持久恢复（Worker 中断/图完成未提交/重复输入） | accept-web 真实击杀重启恢复、test_question_runtime_postgres（崩溃续跑、complete 补提交）、accept_real_ai_rubric（预算截断→重试恢复） |
| 并发与权限（同线程双写/失租/过期 revision/跨题） | test_deep_runtime_postgres（advisory lock 双写拒绝、连接崩溃锁释放）、test_c4（失租晚到写、跨题隔离）、C3 sabotage 测试（运行中改材料 superseded） |
| 完整删除（多次重生成/部分清理崩溃/checkpoint 不可用） | test_c4（双 thread+持续崩溃+重试续删）、test_question_runtime_contract（DSN 不可达失败可见可重试）、accept_real/accept-web（真实删除+双库零残留） |
| 无模型清理（Provider 不可用） | test_question_runtime_postgres（cleanup_never_needs_model）、test_deep_runtime_postgres（monkeypatch 建模爆炸）、worker 惰性建模 |
| 真实样本语义（时点/要求分类/引用/独立预期） | C1 expectations.json（先于生成器固定）、accept_real_ai_rubric 引用逐字核验+分类断言、test_rubric_generation 引用可核查测试 |

## 质量门与真实验收（本次运行证据）

- `git diff --check`=0；`RUNTIME_PG_REQUIRED=1 pytest`：166 passed / 0 skip（含新增 4 个故障注入）；`make build`=0；`make frontend-e2e`（E2E_PORT=3131，生产构建）：44 passed。日志：/tmp/c4-{pytest,build,e2e}.log。
- `make ai-smoke`（真实 Provider gpt-5.6-luna + C1 真实 F case + skill_eval_c4_smoke_ckpt）：`AI_SMOKE=OK criteria=4 pass_scores=[8,8,7,7] events={run_started:1, stage:18, tool_started:10, tool_finished:10, message_delta:2967, run_completed:1} elapsed=75.3s`；引用逐字核验通过、冒烟线程清理零残留。首跑暴露 smoke 脚本把上传合同字段（client_ref_id）直接喂生成合同 → 修复于 b8df472。
- API 真实验收（skill_eval_c4_accept{,_ckpt}）：`ACCEPT_REAL_AI=PASS`（/tmp/c4-accept-api.log）。两组 case 各 4 维度；F 组预算截断→重试→thread_state_incomplete 恢复；受理式删除 threads=1 双库零残留、兄弟题完好。
- Web 真实验收（skill_eval_c4_web{,_ckpt}）：`M0_WEB_ACCEPTANCE=PASS`（/tmp/c4-accept-web.log）。新增阶段全部通过：`late_join_replayed events=4`（生成中晚订阅读到已持久化事件）、`refresh_restored_timeline`（刷新恢复且不触发第二次生成）、`worker_killed_midrun → worker_restarted → worker_restart_recovery_verified events=180`（真实 Worker 进程 SIGKILL、租约过期、新 Worker 从检查点恢复、thread_state_incomplete 且 run_started≤1 证明初始输入未重复）。
- 源文件 hash 复核：六个业务源文件 sha256 与 C1 登记一致（验收链每次运行经 m0_samples.run_extraction 前后双重校验，任何不一致会直接 FAIL）。

## 对抗式审查

单审查代理（矩阵覆盖映射 + 突变体强度 + 运行身份）结论：无 Critical；矩阵 7 类场景全部有强覆盖入口（映射表见上），4 个新故障注入测试对生产守卫逐一 mental-revert 均变红（除 Major-3）。发现并已修复：

- Major-1：真实 Provider 链路"恢复不重复初始输入"只有间接事件证明 → 新增 PG 测试直接驱动真实 DeepAgentRubricGenerator：预算截断留下 incomplete 线程 → 真 adapter 恢复 → 检查点内 HumanMessage 恰为 1 条（直接证据，revert adapters 的 inputs=None 分支即红）。
- Major-2：验收证据缺运行身份 → accept-evidence.json 增加 run_identity（git SHA、时间戳、模型 provider/model/fingerprint、SDK 四件套版本、业务/检查点库名、worker 标记），满足"不以配置 production 冒充运行身份"。
- Major-3：跨题测试的 thread 隔离断言恒真（非 durable 生成器不登记线程）→ RecordingGenerator 改走 durable 登记路径，断言两题线程均非空、互斥、且包含各自题目 ID。
- Minor 修复：mjs 删除残留核验改为删除前捕获 thread 清单再逐项核验（成功路径不再退化为空检查）；smoke 清理失败输出 AI_SMOKE_WARN 而非静默；失租测试补 job 归属与 fail 拒绝断言；task.json 行尾换行。
- 记录为已知限制（不阻塞，如实单列）：① 隐藏/恢复页签无自动化覆盖（重连游标逻辑有测试，visibilitychange 行为未自动化）；② 摘要压缩后回放原文逐字一致性仅由"事件合并非丢弃"实现与计数断言弱覆盖，无逐字比对测试；③ SQLite 晚订阅测试同进程，跨进程读库证明由 mjs 5a 承担（late_join_replayed 日志）；④ mjs 刷新/击杀断言存在生成恰好完成的竞态窗口，失败方向诚实（误报 FAIL 而非假 PASS）；⑤ 26s 等待对 20s 租约的余量在最坏心跳时点略紧，无正确性影响。
- 程序断言与业务语义审阅分栏：本文件全部为程序化/自动化证据；老师（用户）对生成维度业务质量的实际认可未发生，不在此声称。

修复后：backend 全量 RUNTIME_PG_REQUIRED=1 167 passed / 0 skip（166+新增真实 adapter 直接恢复证据，另含既有套件），test_c4 三连跑无 flake。

## 提交与合并

- 分支提交：2d2616e（故障注入+验收扩展+C3 证据补记）、b8df472（smoke 合同映射修复，含真实冒烟证据）。
- main 合并与复验：待填。

## 边界声明

- 未清理项目两库（归 C5）、未部署、未改原始语料、未启用 M1/跨题检索；故障注入全部限定在本次独占测试库与本次启动的进程。
