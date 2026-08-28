# ADR-0001：业务状态与 LangGraph Checkpoint 分离

状态：提议，待审核

日期：2026-08-28

## 背景

Case Builder 必须跨请求暂停并恢复 AI 流程，同时让页面在刷新、失败和服务重启后仍能稳定看到“解析失败、等待回答、等待确认、AI 失败、已确认”等业务状态。

LangGraph Checkpointer 能保存图状态和执行游标，但它的数据结构服务于执行恢复，不等于长期业务模型。如果页面直接把 Checkpoint 当业务数据库，将出现三个问题：

1. API 和页面会耦合 LangGraph 内部结构；
2. Graph 升级、重放或清理 Checkpoint 可能静默改变业务结果；
3. 很难保证“已确认”状态和候选用例记录原子一致。

反过来，如果只保存业务表而不保存 Checkpoint，人工追问和确认后就无法按原执行位置可靠恢复。

## 决策

采用两个职责明确的持久化层：

- 业务 PostgreSQL 表是对外业务事实源，保存源案例、页面可见状态、当前问题/草案投影和最终候选用例。
- LangGraph PostgreSQL Checkpoint 是执行事实源，只保存图状态、暂停值和恢复游标。

具体约束：

1. 每个 `CaseBuilderSession` 由服务端生成一个稳定 UUID `thread_id`；浏览器不读取、不提交、不选择它。
2. 所有 Graph 调用都从业务会话查出同一个 `thread_id`，并把它放入 `configurable.thread_id`。
3. 首次执行传普通 Graph 输入；回答和确认只使用 `Command(resume=...)`；AI 失败重试从同一 thread 的最后可靠 Checkpoint 继续。
4. Graph 返回问题或草案中断后，Case Builder Service 将该边界状态投影到业务会话，GET 接口只读业务投影。
5. `interrupt()` 之前不做不可幂等新增。候选用例只在确认中断恢复后创建。
6. 创建候选用例、写入确认人/时间并把 `CaseBuilderSession.state` 置为 `confirmed` 必须处于同一业务事务。
7. `candidate_cases.source_case_id` 使用唯一约束；确认重试读取并返回现有记录。
8. Checkpoint 不能被当作候选用例、回归集或审计记录。即使清理 Checkpoint，已确认候选用例仍然存在。
9. 本阶段不启用 LangGraph Store；跨 thread 的长期事实仍进入业务表。

## 一致性边界

```text
Graph 执行中
  → Checkpoint 保存执行位置
  → Graph 暂停/失败/结束
  → Service 将可见边界投影到 CaseBuilderSession

人工确认恢复
  → persist_confirmed_case
  → 单事务：upsert CandidateCase + CaseBuilderSession.state=confirmed
  → Graph END
```

如果进程在 Graph 执行中终止，业务会话可能暂时停留在 `generating`。服务启动或下一次执行命令前，根据配置的执行时限把陈旧运行归一为 `ai_failed/AI_RUN_INTERRUPTED`，随后允许使用同一 `thread_id` 重试。GET 接口本身不修改状态，系统也不能因为业务状态是 `generating` 就创建新 thread。

## 结果

正向结果：

- 页面和 OpenAPI 不依赖 LangGraph 私有表结构；
- 人工确认和候选用例具备清晰事务边界；
- Graph 可以跨请求、失败和服务重启恢复；
- 将来升级 Graph 不会自动改写已确认业务资产。

成本：

- 当前问题和草案在 Checkpoint 与业务投影中会有受控重复；
- Service 必须负责投影和陈旧运行归一；
- 测试必须覆盖“Checkpoint 已推进但业务投影失败”的恢复路径。

这些成本小于让执行引擎成为业务数据库所带来的耦合和数据风险。

## 未采用方案

### 只使用 LangGraph Checkpoint

未采用。无法提供稳定的业务查询合同，也无法把确认状态和候选用例放在同一业务事务中。

### 只使用业务表，收到回答后从头重跑

未采用。会重复模型调用，无法精确恢复中断点，也违背已经确认的同一 `thread_id` 恢复要求。

### 引入 Worker 或外部任务队列

本阶段未采用。Walking Skeleton 的单空间单用户、低并发链路可以用同步 HTTP 命令完成；出现真实的长耗时、并发或取消需求后再单独决策。
