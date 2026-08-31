# 实施清单：打分规则共创与题目发布

## Before start

- [ ] 子任务一已完整闭环；从最新 main 创建 `codex/benchmark-rubric-publishing`。
- [ ] 读取父任务/本任务规划与 evaluation-set/backend/frontend specs。

## Backend and Agent

- [ ] Rubric/QuestionRevision 迁移、Repository、Schema、Service、Router。
- [ ] 100 分、阈值、双层判定、锚点、稳定 criterion ID 的确定性校验。
- [ ] rubric co-creator 中文 Prompt、ToolStrategy、HITL、证据隔离和兼容性版本。
- [ ] 上游变化失效、publish/derive 幂等 CAS、不可变历史。
- [ ] 版本包 schema 升级与 v1 reader/runtime leakage 回归。

## Frontend

- [ ] OpenAPI 生成类型与 Feature Service。
- [ ] rubric processing/waiting/review/failed/published/stale Preview 和真实 UI。
- [ ] criterion 编辑、100 分汇总、关键项、锚点、阈值和发布确认。
- [ ] 修订历史只读与 derive-next-draft。

## Gates

```bash
make openapi
make test
make build
git diff --check
```

- [ ] 对分值绕过、关键项补偿、参考答案失败、stale upstream、并发发布、包失败/篡改和旧数据做对抗审查。
- [ ] commit -> fast-forward main -> main 全量复验 -> archive -> 安全删支。

