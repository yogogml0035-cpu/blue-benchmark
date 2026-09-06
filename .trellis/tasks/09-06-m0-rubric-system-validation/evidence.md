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

- `git diff --check` / `RUNTIME_PG_REQUIRED=1 pytest`（0 skip）/ `make build` / `make frontend-e2e`：待填。
- `make ai-smoke`（真实 Provider + C1 真实 F case + 隔离检查点库 skill_eval_c4_smoke_ckpt）：待填。
- API 真实验收（skill_eval_c4_accept{,_ckpt}）：待填。
- Web 真实验收含 Worker 重启恢复（skill_eval_c4_web{,_ckpt}）：待填。
- 源文件 hash 复核：待填。

## 对抗式审查

- 待填。

## 提交与合并

- 分支提交：2d2616e（故障注入+验收扩展）。
- main 合并与复验：待填。

## 边界声明

- 未清理项目两库（归 C5）、未部署、未改原始语料、未启用 M1/跨题检索；故障注入全部限定在本次独占测试库与本次启动的进程。
