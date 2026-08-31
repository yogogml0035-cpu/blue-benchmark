# 修复共创阶段连续性与 AI 运行模式隔离

## Goal

修复 M0 共创从场景标准到单题判定依据的阶段连续性，让业务老师能够看到“已确认的场景标准被本题继承，只补充本题判定依据”，而不是回答完一套问题后再次看到同一套问题。与此同时，阻止 Fake 与 Production Worker 在同一个业务队列中混合消费，避免测试替身伪装成真实 AI 结果。

## First-principles diagnosis

- 目标不是让所有内容都由 AI 生成。业务事实、确认、状态、版本和权限必须由 FastAPI/业务数据库/确定性规则拥有；DeepAgent 只负责理解已授权证据、提出一个最高价值问题和生成结构化候选。
- “场景标准”和“单题判定依据”是两个必要层级，但第二层必须继承第一层，不能重新询问同一个共享任务边界。
- 当前截图对应的固定文案可以在 FakeStandardCoCreator._question 找到；当前运行数据库也已证明最近的共创操作由 runtime=fake Worker 完成。真实 adapter 存在，但两个 Worker 同时在线时，队列没有运行模式隔离。

## Requirements

- 保留归档 M0 需求中的两层形成过程：先确认场景标准，再逐题形成判定依据；不把两个层级合并成一个失去追溯的字段。
- task_judgment 的每次 start/resume/reproject 必须接收当前已确认且与 TaskPackage 一致的场景合同；模型提示必须明确该合同是继承标准，不再要求老师重新陈述共享边界。
- Fake adapter 只能服务自动化测试和显式本地 Fake 运行；它必须在测试中模拟“继承合同、提出题级补充问题”，不得对两个 kind 复用同一套场景级硬编码提问。
- 长驻 Worker 在同一个业务数据库上必须是单消费者；第二个 Worker 不能领取任务，更不能让 Fake/Production 交替产生结果。无法取得运行锁时必须在领取任务前明确失败。
- 不新增第二套业务状态机，不让前端猜测阶段，不把 thread/checkpoint/raw model message 暴露给浏览器。
- 已经由错误模式产生的历史会话不做静默改写；修复后通过显式重置/重新开始或新的业务会话恢复，历史形成记录仍可审计。

## Acceptance Criteria

- [ ] 真实代码路径能说明 Fake、DeepAgent、业务 Service、Worker 各自负责什么；最近操作能区分 Worker 运行模式且不把 Fake 结果称为真实 AI。
- [ ] 场景合同确认后启动题级共创时，题级 Agent 收到已确认合同；Fake 回归路径出现题级问题，不再返回“这组真实任务共同要判断的最终交付结果是什么？”。
- [ ] 题级 resume/reproject 继续使用同一合同快照和 accepted Checkpoint，不重复要求老师回答共享场景边界。
- [ ] 同一 Postgres 业务库的第二个长驻 Worker 在 claim 前无法取得运行锁；释放锁后单个 Worker 可正常处理队列；测试环境不因新增锁破坏既有 run_once() 合同。
- [ ] 覆盖重复 start、重复 answer、过期 session、合同更新、旧 Fake 会话和 Worker 退出/重启等边界；不产生第二个业务答案或越过老师确认。
- [ ] cd backend && uv run pytest -q、make test、适用的 make build 和 git diff --check 通过。
- [ ] 完成一轮针对权限、并发、幂等、恢复、证据泄漏、旧数据和存储完整性的对抗式审查；发现的可安全修正问题已修复并有回归证据。

## Constraints and out of scope

- 只修改当前实现真正需要的后端 runtime/Service/Worker、必要的前端阶段提示、测试和项目说明；不重写 M0 产品模型。
- 不引入 M1 知识库、M2 被测 Skill/Agent 执行、评测运行、多人权限或新的持久化业务实体。
- 不把当前正在规划的 08-30-server-deployment-planning 任务当成本任务的父任务，也不改写归档任务的历史文件。
- 不在测试或日志中输出 API key、Session Cookie、原始凭证、私有 reasoning、Checkpoint 内容或用户上传正文。

## Notes

- 该任务引用 .trellis/tasks/archive/2026-08/08-29-m0-evaluation-set-planning 作为已批准的产品边界和验收依据；实现事实以当前源码、测试和运行数据库为准。
