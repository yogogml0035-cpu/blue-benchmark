# 对抗审查 Round 1：运行时与真实 Provider

审查对象：当前 checkout 的 production AI runtime、Worker、Filesystem、Checkpointer 和 EvalData 真实链路。

## 发现与修复

| 发现 | 复现证据 | 最小修复 | 回归 |
|---|---|---|---|
| Filesystem 目录权限挡住 `/evidence` 列举 | deepagents 0.7.11 首匹配权限 probe：目录原规则为 deny | 允许 `/evidence` 与当前虚拟文件，其他 read deny、所有 write deny | `test_filesystem_permissions...`、真实 batch E2E |
| 模型虚拟路径/未知 file ID 可进入业务候选 | 结构化候选包含非当前 scope 的引用/文件字段 | 仅规范化精确 `/evidence/<known-id>`；所有字段做整批 scope 检查，未知仍拒绝 | `test_virtual_evidence_paths...`、`test_batch_output_scope...` |
| group 级引用跨组 | adapter 整批校验通过，Service 按 group 缩小 documents 后抛 scope error | 要求 `group.evidence_refs.source_id` 属于同一 group 文件集合；保留 Service 二次检查 | `test_batch_output_scope_rejects_cross_group...`、真实 E2E |
| completion union/function-calling 请求超时或 locator 形状非法 | 真实 probe：`OpenAITimeoutError`；随后 strict model validation 指向 locator | 按当前 kind 使用单一 completion wire schema，fallback 只发 source-only refs | `test_cocreation_resume_adds_completion_guard...`、真实两题 E2E |
| 提问预算可能无限追问 | 真实预算边界运行持续产生问题 | context 传入已回答计数；预算到达改为完成式候选，老师仍需确认 | 预算单测、真实 E2E `AI_MAX...=1` |
| long AI call 可能失租约 | Worker/lease probe | Worker 心跳续租，最终 ownership/CAS 仍权威 | Worker 回归测试、真实 Worker |

## 结论

Provider 配置存在不是成功证据；最终通过同时证明了真实结构化响应、真实受限工具面、业务投影和 Checkpoint 连续性。未把 M0 包冻结升级成 M2 Agent 评测通过。
