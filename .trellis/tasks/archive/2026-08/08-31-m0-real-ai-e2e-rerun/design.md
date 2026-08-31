# M0 真实 AI E2E 重跑与缺陷修复设计

## 已证实的行为缺口

首次本轮真实运行已经完成 Provider、隔离双库、API/Worker、三份样本上传、ZIP 展开和资料角色确认，但在同一 `command_id` 重放任务分组时发现返回任务 ID 列表不一致。`cocreation_repository.confirm_grouping` 的幂等回读查询没有 `ORDER BY`，而首次创建响应按输入顺序返回；PostgreSQL 无序查询不承诺稳定行序。

## 最小改动

- 在 `backend/app/features/case_builder/cocreation_repository.py::confirm_grouping` 的已确认回读查询中复用任务列表的确定性排序（`grouping_order`，旧数据退回 `created_at`, `id`）。
- 分组顺序以老师提交顺序为准，写入内部 `grouping_order`；历史数据没有该字段时退回 `(created_at, id)`，不按 UUID 改变业务语义。
- 共创和覆盖快照提交在业务事务内校验当前 operation owner/attempt；attempt 指针按 `job.attempts` 精确绑定，禁止旧租约结果落库。
- judgment session 记录其来源合同修订；合同变化后旧 session 不再被当作当前可用 session，确认时拒绝过期合同。
- projection 恢复完成后，历史 `projection_pending` job 不再覆盖已恢复会话的 `next_action`。
- event locator 即使有预计算 ID 也必须回读 JSONL 行校验 quote。
- 私有 operation 结果记录 Worker 模式，真实 runner 对本轮操作做 production attestation；不新增业务 API 字段。
- 在 `backend/tests/test_persistence_ingestion.py` 增加 HTTP 合同回归：上传并完成 Fake 分析、确认资料角色、首次确认分组，再用相同命令和原始 revision 重放，断言任务 ID 与顺序完全一致且数据库仍只有一组确认任务。
- 不修改 runner 的断言来适应不稳定 API，不增加第二套 DTO，不改变 M0 状态机、公开字段、OpenAPI 或版本包结构。

## 真实验证边界

生产 AI 只由单 Worker 通过 `production_worker()` 创建；业务库和 Checkpointer 库使用不同数据库名，样本输入只由显式 runner 读取。真实 runner 的 AI 提问预算设置为 1 作为成本受控的完成式 fallback 边界，报告不得把它表述为默认 12 轮压力基线。

## 对抗审查重点

确认修复后继续攻击：同命令/不同 payload、重复分组后的第二套任务、失权读取、旧 revision/迟到结果、runtime 分区泄漏、冻结包 hash/ready marker 不一致、临时环境与 `.env` 5432 的配置漂移。只有可复现且属于本任务边界的缺陷才修改；其余记录为未宣称项。
