# 实施清单：打分规则共创与题目发布

## Before start

- [x] 子任务一已完整闭环；从最新 main 创建 `codex/benchmark-rubric-publishing`。
- [x] 读取父任务/本任务规划与 evaluation-set/backend/frontend specs。

## Backend and Agent

- [x] Rubric/QuestionRevision 迁移、Repository、Schema、Service、Router。
- [x] 100 分、阈值、双层判定、锚点、稳定 criterion ID 的确定性校验。
- [x] rubric co-creator 中文 Prompt、ToolStrategy、证据隔离和兼容性版本；真实输出失败有一次受限修复。
- [x] 上游变化失效、publish/derive 幂等 CAS、不可变历史；projection pending 只走无模型 reproject。
- [x] 版本包 schema 新增 v2 与 reader，Working Set 支持 legacy/authored mixed，v1 reader/runtime leakage 回归。

## Frontend

- [x] OpenAPI 生成类型与 Feature Service。
- [x] rubric not_started/processing/waiting/review/failed/published/stale/projection_pending Preview 和真实 UI。
- [x] criterion 编辑、100 分汇总、关键项、锚点、阈值和发布确认。
- [x] 修订历史只读、derive-next-draft，以及已发布题目加入版本组集。

## Gates

```bash
make openapi
make test
make build
git diff --check
```

- [x] 对分值绕过、关键项补偿、参考答案失败、stale upstream、并发/幂等发布、投影恢复、包篡改、v1/v2 泄漏和旧数据做对抗审查。
- [ ] commit -> fast-forward main -> main 全量复验 -> archive -> 安全删支。

真实验证记录：`make ai-smoke`、独立 Checkpointer setup、生产 API + 单 Worker + `next start` + `/Users/hsikey/BenchMark/EvalData` 已跑通；Playwright 真实 Provider 闭环含多题确认、rubric 生成/确认/发布和 console error 检查，最终 `1 passed`。
