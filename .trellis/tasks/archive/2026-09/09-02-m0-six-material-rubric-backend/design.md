# Technical Design

## Current-record model

重建一个以“当前题目”为核心的领域模型。每道题保留稳定服务端 ID、辅助 `title`、六类材料、场景归属、当前评分维度、生成状态、发布状态和内部 `content_revision`。`content_revision` 只用于 CAS、防止旧任务覆盖新内容，不形成用户可见版本历史。

建议以题目聚合保存当前内容：题目正文与标准答案使用文本列；参考样例、Bad case/反馈和记忆材料使用受严格 Schema 约束的 JSON 聚合。它们没有跨题独立生命周期，因此不建立共享可变业务记录。

## Six-material contract

- `task_prompt`：老师实际输入的任务要求。
- `reference_examples[]`：稳定客户端 ID、可选安全来源名称、老师确认的题目相关整理文本。
- `bad_cases[]`：坏结果正文，以及与该结果绑定的老师反馈原话和确认后的原因整理。
- `reference_answer`：老师认可的标准答案。
- `memory_materials[]`：稳定客户端 ID、可选安全来源标签、未经摘要或改写的原始记忆正文。由本地 Agent 从本次任务实际加载的记忆中筛选相关、安全片段，不绑定业务 Skill。

不建立独立“原始资料”字段，不保存原文件、绝对路径、聊天全文、系统提示、私有推理、工具轨迹、凭证或其他用户内容。题目合同不保存业务 Skill 身份字段。服务端不尝试重新判断业务相关性，但必须拒绝明显凭证、绝对路径和受限内部字段。

## Batch authoring and idempotency

场景凭证决定 `scene_id`，请求只携带批次 `command_id` 与 `cases[]`。每题使用稳定 `client_case_id`。服务端先验证全部题目、权限、配额和内容边界，再在一个业务事务中创建所有当前题目、评分维度生成任务和幂等回执。

相同连接、相同 `command_id`、相同 payload 返回原结果；同命令不同 payload 返回冲突。事务提交后，Worker 逐题处理 AI 任务；单题生成失败只改变该题状态，可幂等重试，不回滚已成功入库的整批题目。

## Rubric generation

每个评分维度只包含稳定内部 ID、`criterion`、`pass_score`。`criterion` 是完整可执行的评判标准字符串，同时承担原名称与说明的作用；固定满分为 10，`pass_score` 必须是 `0..10` 整数。未来评分采用逐项 AND：任一维度低于自身门槛，整题不通过；M0 只保存合同，不实现评分执行。

AI Adapter 只读取当前题目的六类材料，返回严格结构化的 `1..N` 个维度。`criterion` 必须写明判断对象、合格表现和主要问题，拒绝“准确性”“创新性”等无法直接评分的空泛标签以及不安全文本。场景名称、title 和内部状态不参与生成。

## Edit, generation, and publication state

新题创建后进入 `generating`；成功后为 `pending_review`，失败为 `generation_failed`。管理员可以增删改维度并发布。

材料修改只有“保存并重新生成”：事务内覆盖当前材料、递增 `content_revision`、使旧维度失效并创建新任务。Worker 最终写入必须校验题目 revision 与任务所有权，旧任务不得覆盖新材料。修改已发布题目后直接回到待处理；不保留历史版本、旧发布内容、发布快照或派生草稿。

## Destructive migration

新增破坏式 Alembic migration，删除旧手动建题、文件 ingestion、task package/co-creation、Working Set/coverage/version package、submission/human scoring 专属表与合同，并创建新题库结构。不迁移旧业务数据，不双写，不兼容旧 JSON 或旧 API。

迁移必须同时验证旧 head 升级和 fresh DB 建库。downgrade 只要求恢复 schema 可执行性，不承诺恢复已删除业务数据。

## Verification

覆盖六类材料校验、场景权限、批量原子性、幂等冲突、生成失败/重试、revision 竞态、泄漏拒绝、两字段结构、空泛 criterion 拒绝、逐项及格语义、直接覆盖发布内容、旧路由消失、旧 head 升级和 fresh DB。
