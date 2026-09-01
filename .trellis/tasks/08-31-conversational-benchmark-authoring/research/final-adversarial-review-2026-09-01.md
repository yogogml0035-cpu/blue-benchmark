# 最终对抗审查：评测用例收录、发布与 ai-eval-push

## Scope

审查父任务与三个剩余子任务，覆盖业务对象、权限、租户隔离、凭证、幂等、并发、恢复、文本保真、坏样本证据、组合命令、版本、停用/删除、人工评分、迁移、存储和 Skill 分发。只审查规划，不宣称未实现能力已存在。

## Findings and Corrections

### 1. 把收题链和评分链混成同一个对象

- Failure：用人工评分侧的旧词解释收题，进一步追问 ai-eval-push 如何使用旧修订。
- Correction：M0 核心对象是“评测用例”；人工评分输入叫“待评结果”。ai-eval-push 只创建新用例草稿，与旧修订无关。
- Status：已同步父 PRD/design/implement 和跨修订任务词表。

### 2. 评测用例结构被过度工程化

- Failure：把 must_include、prohibited、background、role/priority 等全部变成外部 Skill 必传字段。
- Correction：外部最小合同只保留题目标题、逐字任务要求、输入文件内容、坏样本及两层否定依据、逐字标准答案。平台后续生成 rubric。
- Status：已修正 Schema 方向和验收。

### 3. Agent 改写原始任务与证据

- Failure：摘要提示词、截断文件或润色标准答案会改变被测任务。
- Correction：任务要求、完整选中文件、坏样本正文、老师反馈原话和标准答案逐字保存。节选必须显式标注来源并确认；超限时阻止，不静默截断。
- Status：已加入 canonical hash、测试和 UI 预览合同。

### 4. AI 合成坏样本或冒充老师判断

- Failure：为了丰富 rubric 自动造反例，或用 Agent 摘要替代老师反馈。
- Correction：坏样本必须来自真实执行并被老师明确否定；保存逐字 `teacher_feedback_texts`，Agent `reason_summary` 必须确认且不能替代原话。反馈过于笼统时继续追问或放弃该样本。
- Status：已修正。

### 5. 外部 Skill 权限持续膨胀

- Failure：让 ai-eval-push 读取、修改、生成 rubric、确认或发布草稿。
- Correction：外部 token 仅绑定一个 Workspace，scope 为绑定信息读取 + draft:create。上传同步返回精确草稿 URL 并结束；草稿编辑、AI、rubric、发布只在 Web Session 中完成。
- Status：已修正。

### 6. 外部凭证导致跨租户错投

- Failure：客户端提交或缓存错误 account/workspace ID。
- Correction：服务端 principal 固定 user/workspace/scope，不信任租户字段；每次预览读取当前场景名。场景改名保留稳定 ID，重新绑定撤销旧 token，删除场景或账号失效立即拒绝。
- Status：已修正。

### 7. 长效凭证泄漏

- Failure：token 进入 URL、日志、命令回显、源码、`.env` 或 Git，或被用于无限刷草稿。
- Correction：高熵 token、数据库只存 hash、长期有效至主动撤销/重新绑定/场景删除/账号失效；客户端 OS keychain 或 0600 用户配置；per-token 频率/并发/payload 限制；安全 413/429。
- Status：已修正。

### 8. 上传链接不能恢复到精确草稿

- Failure：未登录点击链接后丢失目标，落到场景首页或其他账号资源。
- Correction：返回精确可编辑草稿 URL；匿名用户经受校验的同源 return-to 登录后回到同一草稿。URL 不携带 token。
- Status：已修正。

### 9. 题目确认与规则生成形成半状态

- Failure：前端先确认，再单独生成；网络失败留下老师无法理解的中间状态。
- Correction：服务端“确认题目并生成打分规则”组合命令，持久化确认和 OperationJob 意图。生成失败保留确认，只重试生成；再次编辑才使确认失效。
- Status：已修正。

### 10. 规则确认与发布重复确认

- Failure：规则确认后还要再次发布，且可能形成 confirmed-but-unpublished。
- Correction：服务端“确认规则并发布到评测集”组合命令；完整成功才创建不可变用例修订、当前集合和版本。失败保持 rubric review。
- Status：已修正。

### 11. 修改草稿污染当前正式版本

- Failure：保存已发布用例的修改就替换 active revision，半成品进入评测集。
- Correction：active revision 不可编辑；修改派生唯一 next-revision draft。旧版持续有效到新版完整发布。放弃草稿不影响旧版；M0 不支持并行分支。
- Status：已修正。

### 12. 发布与版本包跨介质半成功

- Failure：题已发布但未入集，或 manifest/ZIP 失败后留下可见版本。
- Correction：staging、分区 hash、ready marker、数据库 CAS/行锁和 reconciliation；读取只认 ready。发布/修改/停用/恢复/删除均使用 command id 和当前集合 revision。
- Status：已修正为设计与验收门，实施仍需故障注入证明。

### 13. 停用/删除后仍可继续评分

- Failure：旧直链继续创建待评结果、首次评分或重评。
- Correction：历史 GET 与 evaluation write 分流。disabled/deleted 拒绝新待评结果和所有新增评分；历史可读。restore 后开放，deleted 永久只读。
- Status：已修正。

### 14. 跨题目重评导致错误结论

- Failure：同一待评结果可以选择同一场景的任意题目规则。
- Correction：只允许相同 `question_draft_id` 的已发布修订；每条 score 自带 revision，历史按各自 revision 渲染。另一个用例必须新建待评结果。
- Status：已修正。

### 15. 新版本包泄漏评分侧内容

- Failure：runtime 包含标准答案、坏样本、rubric、老师反馈或凭证。
- Correction：runtime allowlist 只含逐字任务要求和允许输入文件内容；标准答案、坏样本和 rubric 在 judge，形成记录在 provenance。旧 v1/v2 bytes/hash 不重写。
- Status：已修正。

### 16. Skill 分发与命名漂移

- Failure：平台 API 未稳定先造 Mock Skill，或自动改名为 `ai-eval-push-skill`，源码/安装双副本漂移。
- Correction：平台生命周期与 API完成后才在独立目录构建；名称固定 `ai-eval-push`；全局安装指向源码；真实 E2E、安全扫描后创建私有 GitHub 仓库。
- Status：已修正。

## Residual Implementation Risks

- 文件系统与数据库无法真原子，必须用故障注入证明 staging/ready/reconciliation，不以设计文档代替。
- 旧 ScenarioContract、WorkingSetDraft、版本包和人工评分数据的前向迁移需要 SQLite/PostgreSQL 双路径测试。
- 跨平台 keychain 可用性不同，0600 fallback 的路径、权限和不回显行为需要真实宿主验证。
- payload 数量与 bytes 上限应在实施时依据当前存储/HTTP 配置固定并在 Skill 端预检，不能静默截断。
- 旧用户文案到“评测用例/待评结果”的迁移必须覆盖 OpenAPI、前端、README、spec、Preview 和 E2E；数据库内部类名可兼容保留。

## Conclusion

结论维持当前三子任务顺序与外部 Skill 交付。未发现仍需用户决策的产品分叉。剩余项均是实施验证和兼容门，不改变已确认的 M0 行为。
