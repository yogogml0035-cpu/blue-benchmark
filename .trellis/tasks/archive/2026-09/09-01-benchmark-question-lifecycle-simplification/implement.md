# 实施计划：简化 Benchmark 场景与题目生命周期

## Before Start

- [ ] `benchmark-cross-revision-rescoring` 已完成分支闭环，或用户明确调整顺序。
- [ ] 最终规划摘要获得单独实施批准。
- [ ] 从验证干净的 `main` 创建 `codex/benchmark-question-lifecycle-simplification`。
- [ ] 读取 backend/frontend authoring、evaluation-set、human-scoring、storage 和跨层规范。

## Backend

- [ ] 增加评测用例 lifecycle、当前集合 revision 和坏样本结构的前向迁移；保留旧合同/版本表。
- [ ] 移除新建题、发布和自动版本路径对场景合同的强制前置。
- [ ] 扩展 authoring/rubric Schema、Repository、Service 和 AI adapter，坏样本进入 judge/provenance，不进入 runtime。
- [ ] 实现服务端“确认题目并生成打分规则”组合命令、幂等 receipt、OperationJob 意图和失败重试；删除前端两步串联。
- [ ] 实现发布/修改/停用/恢复/删除到自动版本包的原子状态机、幂等和并发控制。
- [ ] 实现 active revision -> 唯一 next-revision draft -> 新 revision publish 的派生链；保存/AI/rubric 过程不得移动 active 指针。
- [ ] 实现 disabled 保留草稿但禁止 publish、restore 后继续、deleted 作废 open draft 的状态与并发约束。
- [ ] 实现服务端“确认规则并发布到评测集”组合命令；校验失败/打包失败保持 rubric review，旧 confirmed API 仅做兼容。
- [ ] 增加统一 `assert_accepts_evaluation_write`，阻止停用/删除后的新待评结果、首次评分和重评，不影响历史读取；restore 后重新开放。
- [ ] 保留旧版本 reader 与旧 hash/bytes；新增迁移和兼容测试。

## Frontend

- [ ] 收敛场景表单为名称和问题描述，移除强制场景合同主流程。
- [ ] 按题目标题、任务要求、输入文件内容、坏样本及原因、标准答案组织审阅/编辑，并保持一次一个用例和文本-only 提示。
- [ ] 所有草稿统一使用“确认题目并生成打分规则”主动作；覆盖处理中、生成失败、只重试生成和编辑后失效状态。
- [ ] 发布完成后直接展示“已进入当前评测集”，删除组集/冻结下一步。
- [ ] rubric 页移除独立“确认规则”和“发布”两步，统一为高后果主按钮并显示准确失败状态。
- [ ] 增加停用、恢复、删除和只读历史状态；历史版本页不再承担写流程。
- [ ] 用例列表和编辑页同时清楚展示当前 active revision 与下一修订草稿；不提供并行修改分支。
- [ ] 待评结果/评分页在 disabled/deleted 时移除写动作并展示只读原因；不得依赖按钮禁用代替服务端门禁。
- [ ] 更新 Preview、E2E、可访问性和 `.interface-design/system.md`。

## Validation

```bash
make openapi
make test
make build
git diff --check
```

- [ ] 用真实文本/Markdown 走通发布、修改、停用、恢复、删除和历史回查。
- [ ] 对 runtime 泄漏、并发发布、幂等重试、版本包失败、删除后旧 URL 和跨账号访问做对抗检查。
- [ ] 对停用/删除后的直连 POST、已有待评结果首次评分、同修订/跨修订重评、恢复后重试和纯历史 GET 做回归检查。
- [ ] 对组合命令中途失败、重复提交、陈旧 draft revision、生成失败后重试和确认后重新编辑做对抗检查。
- [ ] 对 rubric 校验通过但打包/事务失败、并发发布、旧 confirmed 状态和重复 publish command 做对抗检查。
- [ ] 对修改草稿中途放弃、重复派生、并行编辑、停用期间 publish、删除 open draft 和新发布替换 active 的原子性做对抗检查。
- [ ] 合并后在 `main` 重跑完整质量门，归档任务并安全删除精确任务分支。

## Rollback

- Feature Gate 可关闭新写入口；不删除旧版本、题目修订、待评结果和评分历史。
