# 技术设计：打分规则共创与题目发布

## Dependency and ownership

严格依赖 `benchmark-input-answer-cocreation` 已合并、main 复验、归档和删支。独占 RubricDraft、BenchmarkQuestionRevision、rubric co-creator 和规则审阅/发布 UI；顺序扩展 TaskPackage、QuestionDraft、evaluation_sets 和版本包。不得实现人工评分。

## Rubric schema

```text
RubricDraft
  threshold: int = 60
  criteria[]:
    id, name, purpose, max_score
    award_points[], deduction_points[]
    critical: bool
    critical_mode: none | minimum | hard_fail
    critical_min_score? / hard_fail_conditions[]
    reference_expected_score
    reference_score_reason
```

Service 不变量：criterion ID 唯一；max 合计 100；分数/阈值范围合法；参考答案总分和关键项通过；文本长度有界；无内部 ID/路径/凭证字段。

## Agent

- rubric co-creator 使用独立稳定 Checkpointer thread 和独立 graph schema/version。
- 输入只含上游确认快照、相关 feedback 和 scoped evidence。
- 工具只读 evidence + ask_teacher + structured ToolStrategy；所有用户可见文字中文。
- Prompt 明确禁止 similarity scoring、越级发布和从其他题迁移规则。

## Publication

- mutable QuestionDraft 持有 rubric 候选和 CAS revision。
- publish 先 canonical serialize/hash，再在同一事务校验 draft/upstream revision 并创建 immutable BenchmarkQuestionRevision。
- derive next draft 从指定 published revision 复制，不从 mutable live rows 重拼历史。
- criterion ID 在新修订中可保留未变项；修改语义/满分的项产生新 ID 或记录 replaced-from，避免历史评分误绑定。

## Version package

- 新 package schema 明确 published question revision identity/hash。
- runtime 只含被测输入；judge 含 reference/rubric/threshold；provenance 含老师确认与来源。
- v1 文件和 ready marker 只读；新 builder 写新 key/schema，不覆盖。

## Frontend

- 同一会话从上游确认进入 rubric 处理中/追问/审阅。
- 规则审阅采用连续 criterion 列表或聚焦分页，不用 JSON 编辑器。
- 显示 max、给/扣分点、关键项配置、标准答案锚点/理由和总分/阈值；发布为唯一主动作。
- 上游失效时明确返回第一阶段，不渲染旧 rubric 为当前。

## Rollback

- 失败保留已确认上游和 rubric draft，不创建发布修订。
- 版本包升级失败不改变现有 v1 读取；可关闭新 publish 入口而不回滚历史。

