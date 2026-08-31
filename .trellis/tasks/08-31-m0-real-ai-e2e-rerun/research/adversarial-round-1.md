# 对抗审查 Round 1：数据流、并发与证据

## 发现与修复

| 反例 | 复现/证据 | 修复与回归 |
|---|---|---|
| 同一任务分组命令返回同一任务的不同顺序 | 首次真实 runner 在 `task_grouping_idempotency` 失败；Repository 已确认回读无排序 | 保存教师提交的 `grouping_order`，批次列表和幂等回读按同一顺序；新增 HTTP 回归，promotion/全后端回归通过 |
| projection 恢复后旧 job 抢占下一步 | 旧 `projection_pending` job 仍被会话视图选中，恢复会话可能显示 `retry_processing` | 仅当会话仍处于 `projection_pending`/`failed` 才把对应历史 job 作为当前动作；回归断言恢复后 `next_action=answer_question` |
| 共创 lease reclaim 后旧 Worker 写入新 attempt | 旧 job 对象可在新 Worker reclaim 后继续执行；原提交只校验 session revision，且使用 `runs[-1]` | 共创投影事务锁定并校验 operation owner/attempt，按 `job.attempts` 写 attempt；旧 Worker 只能被视为 stale，不改变业务投影 |
| coverage lease reclaim 后旧结果写同一 draft revision | `save_coverage` 原来只检查 draft revision | coverage 保存增加同一 operation/attempt CAS；旧 attempt 无法落库，新增回归 |
| 合同变化期间的旧 judgment ready 后仍可确认 | judgment session 原来没有记录来源合同修订 | session 保存合同修订，当前 session 查询过滤旧合同，确认前比较 task 合同；新增旧 session 拒绝/新 session 可启动回归 |
| event ID 有预计算索引时错误 quote 被接受 | `event_ids` 分支只检查 ID、不回读 JSONL 行 | 无论是否有索引都回读命中行并校验 quote；新增带 `event_ids` 的负例 |

## 通过的质量证据

针对性负例、后端全套测试、前端 typecheck/build、OpenAPI contract-check 和 `git diff --check` 均通过。没有修改 M0 业务模型、队列系统或 M2 能力。
