# Bug Analysis: 真实 AI scope、completion 合同与跨层幂等缺口

## 1. Root Cause Category

- **Category**: B/C/D/E - 跨层合同、变更传播、集成测试缺口与隐含假设。
- **Specific Cause**: Filesystem 虚拟路径、整批证据 scope、group-local 证据 scope 和业务 file ID 被当成同一层合同；模型输出只在 adapter 的整批视角校验，Service 再按 group 缩小 scope 时才暴露越界。completion fallback 的 union wire schema 又让兼容端点超时或返回无法进入严格 locator 联合类型的字段。Operation command 的唯一回查未显式处理跨 kind，batch result 未绑定 operation attempt，终态 draft 的 create command 也未跨 draft 回查；前端轮询默认迟到响应与当前资源属于同一代。

## 2. Why Fixes Failed

1. **表面修复**：只允许单文件 `/evidence/<id>`，没有允许 `/evidence` 目录列举；真实模型在工具反馈不完整时继续生成候选。
2. **错误层修复**：只在 adapter 做整批引用校验，漏掉 Service 的 group-local scope，导致同一批的另一组文件在二次校验中被判为 scope 外。
3. **协议扩展**：用 `phase + contract/judgment 二选一` 的宽松 envelope 兼容 Provider，反而引入复杂 union/function-calling 请求，真实端点超时；按 kind 的单一 wire schema 更稳定。
4. **测试错觉**：Fake/SQLite/HTTP 合同分别绿色，但没有把 lease reclaim、同 command 跨 kind、终态 draft replay、前端迟到响应和真实 Provider 放在同一验收矩阵里。

## 3. Prevention Mechanisms

| Priority | Mechanism | Specific Action | Status |
|---|---|---|---|
| P0 | Runtime | 只读 backend、`/evidence` 目录/已知文件 allow，其余 read deny、所有 write deny；未知 ID 不猜测。 | DONE |
| P0 | Cross-layer contract | batch 先做整批 scope，再做 group-local scope；Service 保留独立二次防线。 | DONE |
| P0 | Provider contract | completion 按当前 kind 只请求一个 wire schema，随后统一归一化并进入严格业务 Schema。 | DONE |
| P0 | Concurrency | Operation command 跨 kind 显式冲突；batch proposal 提交校验当前 attempt 和分析态。 | DONE |
| P1 | Lineage | draft create command 在 active draft 终态后仍回读原 draft；版本仍只由 freeze CAS 创建。 | DONE |
| P1 | UI state | 稳定上传 command、授权失败清空快照、generation guard、projection pending reproject action。 | DONE |
| P1 | Regression | 真实 EvalData runner 只输出阶段标记；新增 group-local、attempt、command-kind、终态 draft、三分区 hash 回归。 | DONE |

## 4. Systematic Expansion

- **Similar Issues**: 任何“整批 -> 子任务/问题”缩 scope 的证据、权限、缓存和版本合同都需要在子范围重新校验；任何从 union 输出投影到严格 DTO 的 adapter 都应按目标 kind 拆分。
- **Design Improvement**: 业务状态仍是权威，Checkpointer 只保存执行连续性；迟到 branch 必须在业务 repository 的事务内被拒绝，不能由 Worker 日志或 latest checkpoint 猜测。
- **Process Improvement**: 每次真实 Provider 通过后，追加一次“同一输入的恶意/越界/迟到结果”验证；每次前端轮询变更后，至少验证失权、A→B 切换和刷新恢复。

## 5. Knowledge Capture

- [x] 更新 `.trellis/spec/backend/quality-and-tests.md`、`stub-state-and-contracts.md`、`evaluation-sets.md`。
- [x] 更新 `.trellis/spec/guides/cross-layer-contracts.md`。
- [x] 更新 `.trellis/spec/frontend/quality-and-verification.md`、`state-model.md`。
- [x] 记录真实 Provider/Worker/PostgreSQL E2E 与浏览器回归，不复制 EvalData 正文、凭证或内部 Checkpoint 标识。
- [x] 仓库未提供 `src/templates/.../spec` 模板目录，无模板同步动作。
