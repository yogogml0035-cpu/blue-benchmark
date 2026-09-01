# 技术设计：按新题目修订重评旧待评结果

## 1. Boundary

保留 `EvaluationSubmission` 作为不可变待评结果正文和原始修订的事实源；把“本次按哪套规则评分”下沉到每条 `HumanScore`。不复制正文，不改变题目发布和评测集生命周期。

## 2. Data Model

- `EvaluationSubmission.question_revision_id`：原始提交修订，保持不变。
- `HumanScore.question_revision_id`：本次评分修订；首次等于原始修订，后续只可变更为同一 `question_draft_id` 的已发布修订。
- 移除“score 修订必须等于 submission 原修订”的复合外键，改为分别保证：
  - score 属于 submission；
  - score 修订是存在的已发布修订；
  - Service 校验目标修订属于同一 Workspace 且与原修订拥有相同 `question_draft_id`。
- `HumanScoreItem` 继续只存 criterion ID、分数、理由和关键项结论；不可变题目修订提供名称、满分和锚点。

## 3. Service Contract

- `ScoreCreateRequest` 增加可选 `question_revision_id`。
- 首次评分固定使用 submission 原修订；若显式传入不同修订则拒绝。
- 后续重评缺省使用最新 score 的修订；显式目标必须通过 Workspace、published 和同一 `question_draft_id` 检查。
- 评分摘要 hash 包含目标修订，避免相同 command 在不同规则下复用。
- parent 校验继续要求当前最新 score，允许父子 score 使用不同修订。

## 4. Read Model

- `GET submission` 返回不可变待评结果、原始题目修订、评分历史，以及历史实际引用的修订视图集合。
- 每条 score 返回自己的 `question_revision_id`；前端按该 ID 解析历史评分项。
- 不把题目修订全文重复嵌入每条 score，避免响应膨胀；使用按 ID 去重的修订映射。

## 5. Frontend

- 首次评分不显示修订选择器。
- 已有评分后，“重新评分”默认沿用最新 score 的修订，并只列出同一 `question_draft_id` 下的已发布修订。
- 切换目标修订时重新创建空评分草稿；不复用不同 criterion 集合的分数。
- 历史卡片显示题目修订号，并使用各自修订的 criterion 元数据。

## 6. Compatibility and Rollback

- 新请求字段可选，旧客户端继续同修订重评。
- 迁移只调整约束和读取模型，不改写待评结果正文、旧 score 或 item。
- 若前端选择器失败，可关闭跨修订入口，旧同修订评分仍可用。

## 7. Security and Concurrency

- 所有目标修订先经过 Workspace owner、published 与同题身份检查；同一 Workspace 的其他题也必须拒绝。
- command 幂等、最新 parent 和事务内 append 继续生效。
- 两个并发重评只能有一个基于当前 latest parent 成功，另一请求返回冲突。
