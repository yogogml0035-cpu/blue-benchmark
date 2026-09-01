# 技术设计：待评文本提交与人工评分

## Dependency and ownership

严格依赖 `benchmark-rubric-publishing` 已合并、main 复验、归档和删支。新增独立 `human_scoring` Feature 或在现有 evaluation ownership 下建立清楚的 Router/Service/Repository/Schema；不让 case-builder Agent 直接写评分表。

## Data model

### EvaluationSubmission

- `id, workspace_id, question_revision_id`
- `content_text, source=paste|file, original_name?, sha256`
- `submitted_by, submitted_at`

### HumanScore

- `id, submission_id, question_revision_id, parent_score_id?`
- `status=draft|submitted, total_score, critical_passed, passed`
- `scored_by, submitted_at, command_id/payload_hash`

### HumanScoreItem

- `score_id, criterion_id, score, reason?, critical_passed?`
- criterion 的名称/满分/锚点从不可变 QuestionRevision 读取，不接受客户端覆盖。

## Validation

- 题目修订必须 published 且属于当前 Workspace/账号。
- 文件只允许一份 `.md/.txt`，扩展名、MIME、UTF-8、1 MiB、hash 和 ready marker 均验证；粘贴文本使用同等字节上限。
- item 集合必须与修订 criterion ID 精确一致；分数为 0..max 整数。
- minimum 关键项由 score 机械判定；hard-fail 关键项只接受是否命中，不能与 minimum 同时配置。
- score < reference anchor、minimum 失败或 hard-fail 命中时 reason 非空；其他 reason 可空。
- total/critical/passed 服务端推导；submitted 后 Repository 拒绝 update/delete。

## API

- POST submission：JSON text 或 multipart 单文件，command 幂等。
- GET submission：返回答卷 + 已发布修订评分视图。
- POST score：只接收逐项输入和可选整体说明，返回服务端计算结果。
- GET score history：只读，重评分支通过 parent_score_id 形成 lineage。

## Frontend

- 桌面双区：主区阅读答卷，评分区按 criterion 连续推进；不并排其他答卷。
- 题目输入/标准答案可在同页 sheet 或折叠区查看，关闭后焦点返回。
- criterion 显示满分、锚点、数值输入、给/扣分点、关键项和条件式理由。
- 窄屏顺序为答卷 -> 标准 -> 逐项评分 -> 结果；提交前保留本地草稿，刷新后的服务端 draft 语义由产品实现选择，但 final 永不覆盖。
- 结果页显示总分、通过线、关键项和老师理由；不显示 Skill 版本或相对排名。

## Security and rollback

- 正文只在授权业务端点返回；日志/事件/错误只记录 submission ID、字节数、hash 前缀和状态。
- 创建文件和 DB 记录使用 staging/ready；任一步失败不留可评分半成品。
- 本 Feature 可单独关闭入口，不影响题目发布、版本读取或旧 M0。
