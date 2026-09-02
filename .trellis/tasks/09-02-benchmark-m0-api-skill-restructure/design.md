# Technical Design

## Architecture

保留 FastAPI、SQLAlchemy/Alembic、OperationJob 和 AI Provider 接入，重建为围绕“当前题目”的后端。业务数据库是题目六类材料、当前评分维度和发布状态的事实源；Checkpointer 只在新评分维度生成确实需要连续性时使用。

删除现有 Next.js 前端。未来前端只使用 OpenAPI/API，不直接读取数据库。

## Current question model

每道题只有一份当前记录：

- `id`：服务端稳定 ID；
- `title`：本地 Agent 生成、管理员可修改的用例标题，用于列表检索；不属于六类材料，也不参与评分维度生成；
- `task_prompt`：老师实际输入的题目；
- `reference_examples[]`：老师本次提供且 Agent 实际读取过的内容，经 Agent 整理并由老师确认；
- `bad_cases[]`：真实坏结果，每项绑定老师反馈原话和确认后的原因整理；
- `reference_answer`：老师认可的标准答案；
- `memory_materials[]`：本地 Agent 从本次任务实际加载记忆中筛选出的相关、安全原始片段，不绑定某个 Skill；
- `criteria[]`：当前评分维度；
- `status`、内部 `revision`、生成任务与错误状态；
- `scene_id`：场景文件夹归属。

发布只更新当前 `status`。修改已发布题目直接覆盖当前内容并回到待处理；不创建历史版本或派生草稿。内部 revision/CAS 仅防并发覆盖。

## External batch API

请求包含批次 `command_id` 和 `cases[]`；每题包含稳定 `client_case_id` 与六类材料。凭证决定场景，payload 不接受 `scene_id`。

服务端先校验整批，再在一个事务中创建全部题目、材料、维度生成任务和幂等回执。任一题失败则全部回滚。相同 command 与相同 payload 返回原结果，不同 payload 冲突。

上传提交后，每题的 AI 任务独立执行。单题失败只改变该题状态，可安全重试，不删除题目或影响同批其他题。

## Material representation

- `reference_examples[]`：稳定客户端 ID、可选安全来源名称、经老师确认的整理文本。
- `memory_materials[]`：稳定客户端 ID、可选安全来源标签、未经改写的原始记忆文本；来源可以是业务 Skill、用户或本地项目记忆，不建立 Skill 外键。相关性与敏感性由本地 Agent 先筛选，服务端再对凭证、路径和明显秘密做兜底拒绝。
- `bad_cases[]`：坏结果正文、老师反馈原话列表和确认后的原因整理。

不保存原始文件、本地主机路径、完整聊天、系统提示、私有推理、工具轨迹或凭证。同一内容用于多题时各题独立保存；不建共享可变材料。

## Rubric

每个 criterion 只包含稳定内部 ID、`name`、`description`、`pass_score`。固定满分 10；所有维度分别达到门槛才通过。M0 不实现评分执行，只保存未来评分所需合同。

外部批量上传后自动排队生成。管理员修改材料时调用“保存并重新生成”，在一个事务中更新题目、使旧维度失效并创建新任务。管理员可以增删改维度并发布。

## Authentication and administration

M0 只有一个管理员账号。管理员 CLI 通过 Service 创建场景、生成/轮换/撤销场景凭证和查询安全状态。明文凭证只显示一次。

场景凭证仅允许查看自身连接状态与批量上传，不能读取、修改、删除或发布题目。

## Question library

题库是包含全部题目的统一入口。后端按题目返回当前六类材料、评分维度状态、发布状态和下一步动作，并支持状态与场景文件夹筛选。不提供历史版本查询。

## Deletion boundary

彻底删除旧 `cases`、文件 ingestion、task package、co-creation、working set、coverage、version package、submission 和 human scoring 业务链，以及其专属数据表、API、AI adapter、脚本、测试和文档。

可保留新流程使用的通用 DB session、OperationJob 租约/重试和 Provider 模型构造，但不保留旧 DTO、状态、路由或兼容分支。

## Migration

使用破坏式 Alembic migration 删除旧业务表并创建新题库表。不迁移旧业务数据，不提供双写或旧格式读取。迁移需验证从旧 head 升级和 fresh DB 建库；downgrade 只恢复 schema，不保证恢复已删除数据。

## Verification

- 后端单元、API、并发、迁移和 OpenAPI 测试；
- Fake AI 用于确定性状态与失败测试；
- 真实 Provider 验证评分维度生成；
- `/Users/hsikey/BenchMark/EvalData` 用于模拟本地上下文、多题切分和真实批量 HTTP 验收；
- 验收日志只输出阶段、计数、ID 和错误码，不输出正文、记忆或秘密。
