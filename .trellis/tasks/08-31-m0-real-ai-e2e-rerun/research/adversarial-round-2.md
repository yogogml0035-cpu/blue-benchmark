# 对抗审查 Round 2：验收真实性、前端状态与边界

## 发现与修复

| 反例 | 证据 | 修复与回归 |
|---|---|---|
| API production 但 Worker 使用 `--fake`，业务 runner 仍可能给绿灯 | 侧审构造了 production API + Fake Worker 的完整业务路径 | operation 私有结果记录 Worker 模式；真实 runner 对 batch/共创/coverage/freeze 全部 job 做 production attestation；Fake Worker 反例实际被拒绝为 `non_production_worker` |
| workspace/batch 切换后的题、版本、草稿请求回写旧快照 | `QuestionsSection`、`VersionsSection`、`DraftPanel` 和 `MemberLabel` 原请求缺少一致 generation/卸载保护 | 各加载器加 generation guard，切换时清空旧集合，分组组件按 workspace+batch 重置，成员标题请求加 active guard；typecheck/build 通过 |
| 验收日志扫描把 `task-groups` 的 `sk-` 子串误判成密钥 | 首轮外层扫描命中 12 次，但逐行脱敏后均为 URL 路径 | 收窄扫描模式并对实际 `.env` key 做不输出值的精确匹配；最终 forbidden pattern 0、两把真实密钥均未命中 |

## 未宣称/剩余边界

- 本轮真实 runner 的任务分组和老师回答是受控验收输入；它证明真实模型能完成 batch/cocreation/coverage 的结构化运行，但不证明模型逐行依赖三份材料，也不做内容质量主观评分。
- 共创预算为 1，默认 12 轮的长轮成本、延迟、租约压力和质量分布未做跑量。
- 本轮使用临时 PostgreSQL 映射端口，不把用户 `.env` 指向的本机 5432 说成已就绪；真实数据、凭证和内部 Checkpoint 未进入 Git 或报告。
- 仓库没有 Playwright CI suite；浏览器结论来自真实运行中的 API/Worker/Next 和 Playwright CLI 交互，不能升级为自动化回归覆盖。
- M0 仍不包括被测 Skill/Agent 执行、Judge、评测报告或 M1 知识库检索。
