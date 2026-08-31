# M0 真实 AI E2E 重跑与缺陷修复实施计划

1. 在独立分支激活本任务，核对归档 M0 需求、当前 `main`、三份 EvalData、凭证存在性和工作区洁净状态。
2. 复现并记录真实 runner 首次失败；完成分组回读稳定排序和 API 回归测试。
3. 重新执行 `make ai-smoke`、后端自动化、隔离 PostgreSQL migration/schema、独立 Checkpointer setup，以及真实 API/单 Worker/runner 完整链路。
4. 对成功链路做两轮对抗审查：第一轮检查 Runtime/Worker/证据 scope/Checkpoint 与业务投影；第二轮检查命令幂等、迟到结果、版本 lineage、ZIP/三分区泄漏、权限、浏览器/构建边界。复现的边界问题先修复再回归。
5. 运行 `make test`、`make build`、`git diff --check`，扫描差异和临时日志中的凭证、正文及内部执行数据。
6. 提交后切回 `main` fast-forward 合并，在 `main` 重跑质量门和目标回归；完成 Trellis 归档、会话记录和安全删除本任务分支。

## 运行证据

- 真实 runner：`cd backend && uv run python scripts/accept_real_ai_e2e.py --samples-dir /Users/hsikey/BenchMark/EvalData --base-url http://127.0.0.1:8000`。
- 隔离环境覆盖 `DATABASE_URL`、`CHECKPOINT_DATABASE_URL`、`STORAGE_ROOT` 和 `AI_MAX_COCREATION_QUESTIONS=1`，不改写用户 `.env`。
- 报告只记录阶段、计数、hash 是否一致、错误类型和剩余边界；不记录样本正文、凭证、raw model output、thread/checkpoint 标识。

## 已执行结果

- 首次真实重跑在任务分组命令重放处复现不稳定顺序；修复后分组回归、projection 恢复、lease reclaim、合同变更和证据 quote 负例均通过。
- 最终真实 runner：`AI_PROVIDER_SMOKE=PASS`；隔离 PostgreSQL 17 双库、production Worker、三份 EvalData、5 份展开证据、2 个任务/3 个 attempts、合同与两道题判定依据、覆盖确认、v1 包 hash/隔离全部通过，`M0_REAL_AI_E2E_STAGE=complete` 且 runner exit 0。
- Fake Worker 反例仍能把业务流程跑到冻结前，但 runner 以 `worker_attestation/non_production_worker` 拒绝；真实浏览器完成注册、建场景、上传三份文件、202/后台处理/刷新恢复、390px Dialog 焦点、旧路由和第二账号 403。
