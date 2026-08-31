# 对抗式审查记录

## 已确认的原始问题

1. 运行数据库最近的共创操作同时出现 runtime=fake 和 runtime=production。进程检查确认同一台机器曾同时存在两个 Worker，其中 Fake Worker 的环境变量覆盖了仓库 .env 中的 production。
2. FakeStandardCoCreator 对 scenario_contract 和 task_judgment 复用同一套固定问题，因此场景合同确认后，题级页面会再次出现共享任务边界问题。
3. task_judgment 新 session 只接收当前任务文件，没有接收已确认的 ContractRevision；即使使用真实 DeepAgent，也缺少“继承场景标准”的可信输入。

## 本轮修正

- Service 在每次 task_judgment start/resume/reproject 前校验 TaskPackage 与 session 的合同 revision，并把 confirmed contract 快照传给 StandardCoCreator。
- 真实 DeepAgent 在 system prompt、首轮任务说明和完成式 fallback 中接收同一份合同，并被要求逐字保留共享 hard gate。
- Fake 只作为测试替身，题级问题改为本题特有判定依据；Fake 完成结果继承场景 hard gate。
- Repository 在题级结果投影和老师确认两处防止题级 hard gate 删除或改写场景 hard gate。
- PostgreSQL 使用 session-level advisory lock，SQLite 使用本地文件锁；长驻 Worker 和 CLI --once 在 claim 前取得锁。Fake Worker 禁止连接 PostgreSQL 业务库。
- 前端只增加业务解释，不复制后端状态机或暴露内部 Agent/Checkpoint 信息。

## 攻击矩阵

| 攻击 | 结果 |
| --- | --- |
| 题级 start 不带合同 | Adapter 直接失败；Service 不会为缺失/未确认合同调用模型 |
| 题级模型删除共享 hard gate | 候选投影和确认均拒绝 |
| 旧合同操作迟到 | session 合同 ID 与当前 TaskPackage 不一致时 supersede |
| 第二个 PostgreSQL Worker | advisory lock 拒绝，未执行 claim_next |
| 第二个 SQLite Worker | fcntl 锁拒绝 |
| Fake Worker 连接 PostgreSQL | 启动失败，不领取任务 |
| 重复 start/answer | 沿用现有 command/revision 幂等与冲突规则 |
| Checkpoint 已产生但业务投影失败 | 沿用 projection_pending/reproject，不重新调用模型 |
| 旧 Fake checkpoint 被生产 Worker 继续使用 | 不猜测迁移；按 continuity_reset 重新建立会话，旧记录保留 |
| 合同、回答进入公开 DTO/版本包 | 本次只扩展内部 adapter 参数，未新增 HTTP 字段；已有 runtime/judge/provenance 门继续生效 |

## 验证证据

- 目标后端回归：53 passed。
- 完整质量门：114 passed；前端 typecheck、OpenAPI contract-check、Next production build 通过。
- 真实业务数据库锁测试：运行中的生产 Worker 持锁时，第二个本地 lock 尝试得到 WorkerAlreadyRunning。
- 显式 AI_RUNTIME_MODE=fake 在当前 PostgreSQL 业务库上返回 fake Worker requires a SQLite business database，未 claim 任务。

## 未伪造的证据

- 本轮没有把旧 Fake session 自动改成真实 AI session，也没有修改其历史结果。
- 本轮没有重新执行完整真实 Provider E2E；真实模型请求仍需在清理旧会话后由浏览器路径或显式真实 runner 单独验收。
