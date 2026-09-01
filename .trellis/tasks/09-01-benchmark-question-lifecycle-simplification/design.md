# 技术设计：简化 Benchmark 场景与题目生命周期

## 1. Target Flow

```text
场景（名称 + 问题描述）
  -> 题目草稿
  -> 任务要求 + 输入文件内容 + 标准答案 + 可选坏样本
  -> rubric 审阅
  -> 发布
  -> 原子生成题目修订 + 当前评测集版本
```

老师不再操作 `WorkingSetDraft`、覆盖确认或 freeze；系统仍保留不可变版本包作为审计和未来执行合同。

## 2. Compatibility Strategy

- 保留 `ScenarioContractRevision`、旧 `WorkingSetDraft`、旧 `EvaluationSetVersion` 和 v1/v2 reader，历史记录只读。
- 新建题路径不再要求 contract；现有 `contract_revision_id` 允许为空，不删除旧外键或历史行。
- 旧版本包不重新生成；新自动版本使用递增 Schema 或兼容 reader 明确区分。
- 已发布用例、待评结果和评分继续按不可变 revision ID 读取。

## 3. Question Model

- 在用例草稿与发布修订中增加 `bad_samples`：稳定 ID、真实执行 source ref、逐字 `content_text`、逐字 `teacher_feedback_texts[]`、老师确认的 `reason_summary`；没有真实坏样本时为空。
- 标准答案仍为单一 `reference_answer_text`。
- 用例输入收敛为 `title + task_requirement + input_files[]`；`task_requirement` 逐字保存原始提示词，`input_files` 区分完整原文和老师确认节选，文件内容只允许 UTF-8 text/markdown，版本包 runtime 使用 allowlist 输出。
- 外部与网站创建的草稿复用同一可编辑模型；外部上传 receipt/hash 只作形成记录，网站修改推进 draft revision。
- content hash 覆盖题目标题、任务要求、输入文件内容、标准答案、坏样本、rubric 与阈值，确保修改产生新修订。

### Confirm and generate command

- 新增服务端组合命令“确认题目并生成打分规则”，输入包含 draft revision、command id 和 payload hash。
- 同一业务事务确认当前题目 revision 并持久化 rubric OperationJob 意图；前端不能串联两个独立请求冒充原子业务动作。
- Worker/排队失败后题目确认保留，业务 `next_action` 为重试生成；同 command 重放不能产生第二个 job。
- 已确认后再次编辑题目会推进 draft revision、清除确认并使任何未发布 rubric/失败 job 过期。

## 4. Automatic Evaluation Set

- rubric review 通过服务端组合命令直接进入 `published(active)`；新主流程不落可见 `rubric_confirmed` 中间状态，旧 confirmed 记录只读兼容。
- 每个 Workspace 保存当前正式集合指针；当前集合由所有 active 逻辑题的最新已发布修订组成。
- 发布/修改/停用/恢复/删除命令读取当前集合、应用一个确定性 delta、生成下一个连续版本号和 staging 包。
- 文件包先写 staging、校验各分区/hash/ready marker，再在数据库事务中发布题目状态与版本记录；失败不暴露部分结果。
- 并发命令通过 Workspace 当前集合 revision/CAS 或行锁串行化；冲突方重读后重试。

## 5. Lifecycle

```text
draft -> rubric_review -> published(active)
published(active) -> derive next_revision_draft -> rubric_review -> publish(new active)
published(active) -> disabled -> active
published(active|disabled) -> deleted
```

- `published(active)` 本身不可编辑；修改只能派生一个 next-revision draft，draft 保存和 rubric 流程不改变当前 active 指针。
- 新 revision 与自动评测集版本完整发布后，当前 active 指针才从旧 revision 切换到新 revision。
- 数据库以逻辑用例 ID 唯一约束一个 open next-revision draft；M0 不支持分支/合并。
- `disabled` 与 `deleted` 都不进入当前集合。
- `deleted` 是业务墓碑，不物理删除发布修订或被历史引用的草稿身份。
- disabled 保留 open draft 但禁止 publish；restore 后恢复。deleted 将 open draft 标为不可恢复的 discarded/deleted，不物理删除形成记录。
- 新待评结果、首次评分和重评统一调用 evaluation-set Service 的 `assert_accepts_evaluation_write(question_draft_id, action)`；disabled/deleted 均拒绝。
- 历史 GET 不调用写门禁，只校验不可变 revision、submission 与 Workspace，因此停用/删除不破坏回查。
- restore 把 disabled 改回 active 并重新开放写门禁；deleted 没有 restore 转换。

## 6. Rubric Generation

- rubric Agent 输入包含题目标题、任务要求、输入文件内容、标准答案、坏样本、老师反馈原话和确认摘要；提示词必须区分原始证据与结构化解释。
- 输出仍为稳定 criterion、给分点、扣分点、critical 模式、参考答案锚点和阈值。
- 坏样本仅作为判断证据；提示词和 Pydantic 校验禁止生成默认相似度规则。

## 7. Frontend

- 场景创建/设置只显示名称和问题描述。
- 评测用例审阅固定展示题目标题、任务要求、输入文件内容、标准答案，并提供可选坏样本区逐份显示原文与否定原因。
- 草稿页只有一个主按钮“确认题目并生成打分规则”；处理、失败重试和重新编辑使用服务端 `next_action`。
- rubric 审阅页只有一个主按钮“确认规则并发布到评测集”；保存草稿不是第二个确认动作。
- 发布确认清楚说明“发布后立即进入当前评测集并留下历史版本”，只有一次高后果确认。
- 题目列表提供停用、恢复和删除；删除确认说明不可恢复但历史保留。
- active 用例的“修改”进入下一修订草稿；列表持续标识“当前已发布版本”和“修改草稿”，避免把草稿冒充生效版本。
- disabled/deleted 的待评结果与评分页面保持只读并说明原因；disabled 提供返回用例恢复的路径，deleted 不提供继续评分动作。
- 版本页退为只读历史，不承担日常组集和冻结操作。

## 8. Rollback

- 新自动发布入口可通过 Feature Gate 暂停；历史读取与已完成人工评分保持可用。
- 不通过回滚迁移删除新数据；恢复旧 UI 时只隐藏新写入口。
