# M0 真实 AI E2E 验证与加固

## Goal

在新增真实 AI 凭证与本地持久化环境下，按 M0 归档需求和五个子任务重跑冒烟、后端/前端 E2E，修复已证实缺口，并保留多轮对抗审查与回归证据。

## Requirements

- R1. 以 `.trellis/tasks/archive/2026-08/08-29-m0-evaluation-set-planning/` 的 PRD、design、implement 和五个已归档子任务为验收基线；先区分当前源码事实、真实执行证据和未验证声明。
- R2. 在不输出或提交任何凭证、业务正文、private reasoning、thread/checkpoint 内部标识的前提下，使用当前环境的真实 AI 配置完成 Provider smoke；必须验证模型确实返回目标结构化结果，而不是只验证配置存在。
- R3. 使用隔离的本地 PostgreSQL 业务库和独立 PostgreSQL Checkpointer，分别完成业务迁移、schema readiness、加密 Checkpointer setup 和真实 Worker 启动前 fail-closed 检查；不得使用远端数据库，不得把 SQLite 结果当作本地生产路径结果。
- R4. 用用户指定的 `/Users/hsikey/BenchMark/EvalData` 下恰好三份本地资料完成 M0 真实样本闭环：上传批次、资料角色与可见性、两组任务与 attempts、场景标准共创、两道题判定依据共创、定稿、同一场景下一版、覆盖审查、冻结 v1、下载并机械验证 Manifest、三分区哈希及 runtime/judge/provenance 隔离。
- R5. 真实 Worker 必须推进上述业务状态；长操作使用 `202` 和服务端投影，刷新/重启/重试/重复命令不丢回答、不重复业务结果、不采用 stale/latest Checkpoint 覆盖新 revision。
- R6. 真实浏览器至少覆盖桌面主路径、窄屏导航/焦点、旧路由重定向、后台轮询、错误恢复和第二账号私有资源拒绝；Preview、HTTP 200、静态截图不能作为闭环证据。
- R7. 完成至少两轮独立对抗审查：第一轮针对数据流、运行时边界、Checkpoint/业务状态一致性和安全泄漏；第二轮针对边界条件、重复/并发/迟到分支、浏览器恢复和配置漂移。每个发现必须有复现证据、最小修正和回归验证；设计判断不能被静默改写。
- R8. 若发现缺口，修复行为实际所在层并补回归测试或可复核验证脚本；保持当前 M0 单用户、主观文案/新闻稿范围，不扩展到 M1/M2。

## Acceptance Criteria

- [ ] `make ai-smoke` 通过，输出只含阶段标记、Provider 和模型标识，不含 key、prompt、正文或内部状态。
- [ ] 业务 PostgreSQL 与 Checkpointer PostgreSQL 均为独立、可连接、schema ready；迁移/setup 可重复执行且不会把应用启动变成隐式建表。
- [ ] 真实 AI + 真实 Worker 将三份样本从输入推进至同一场景 v1；版本下载仅含四个预期文件，Manifest/API/下载整体哈希一致，runtime 不泄漏 judge/provenance。
- [ ] 真实浏览器桌面/窄屏主流程和第二账号隔离通过；刷新、进程重启、答案已保存未恢复、projection pending、freeze 中至少各有一条可复核证据。
- [ ] 对重复命令、同 session 并发 resume、陈旧 revision、错误/缺失 Checkpoint、迟到分支、不可读/恶意 ZIP、私有资源访问均有通过或明确阻塞证据。
- [ ] `make test`、`make build`、`git diff --check` 通过；若前端依赖策略阻塞，必须修复为可重复项目级配置或给出隔离后的等价验证，不把环境错误标成代码通过。
- [ ] 任务文档记录真实/假实现边界、每轮对抗发现与修正、剩余风险；不宣称 M2 Skill/Agent 评测已通过。

## Notes

- 真实样本仅从用户指定的 `/Users/hsikey/BenchMark/EvalData` 读取，禁止复制进 Git、日志、报告或 worker context artifact；测试过程中产生的临时数据库、存储和输出必须在收尾时清理或明确保留原因。
- 真实 AI 运行可能产生外部模型调用成本；本任务已获用户明确授权使用当前环境凭证，但不扩大到其他平台、远端发布或业务写操作。
