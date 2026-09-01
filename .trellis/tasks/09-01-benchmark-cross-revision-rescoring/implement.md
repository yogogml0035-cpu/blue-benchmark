# 实施计划：按新题目修订重评旧待评结果

## Before Start

- [ ] 在最终规划摘要之后获得单独实施批准。
- [ ] 从已验证干净的 `main` 创建 `codex/benchmark-cross-revision-rescoring`，不覆盖其他 planning 任务。
- [ ] 读取 backend/frontend human-scoring、evaluation-set、API contract 和测试规范。

## Backend

- [ ] 增加前向迁移，放宽 score/submission 原修订相等约束，同时保留 submission、revision 和 parent 完整性。
- [ ] 扩展评分请求与响应 DTO，目标修订进入幂等 hash。
- [ ] 实现首次评分、同修订重评、同题跨修订重评、latest parent 和 Workspace/`question_draft_id` 校验。
- [ ] 扩展 submission 读取模型，为每条历史评分提供可还原的修订视图。
- [ ] 增加迁移、并发、幂等、跨 Workspace、跨逻辑题、未发布修订和混用 criterion 回归测试。

## Frontend

- [ ] 用生成类型扩展 Feature Service，不手写 DTO。
- [ ] 增加只列出同一逻辑题修订的重评选择器；切换时清空不兼容评分草稿。
- [ ] 历史按每条 score 的 revision 渲染名称、满分、锚点和修订号；用户文案统一使用“待评结果”。
- [ ] 覆盖加载、无候选、同修订、跨修订、冲突、390px 和键盘/焦点状态。

## Validation

```bash
make openapi
make test
make build
git diff --check
```

- [ ] 浏览器走通原修订首次评分、同修订重评和同题新修订重评。
- [ ] 对跨逻辑题目标、错修订 criterion、陈旧 parent、并发提交、旧客户端和历史回查做对抗检查。
- [ ] 任务分支提交、fast-forward 合并、`main` 复验、Trellis 归档和安全删支全部完成后再启动下一子任务。

## Rollback

- 入口可退回只允许同修订重评；迁移不得删除旧评分或复制正文。
