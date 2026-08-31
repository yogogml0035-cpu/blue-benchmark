# M0 真实 AI E2E 重跑与缺陷修复

## Goal

使用用户指定的三份 EvalData 文件重新执行 M0 真实 AI 冒烟与端到端验证，修复本轮复现的最小缺陷，并完成对抗式回归。

## Requirements

- 以 `.trellis/tasks/archive/2026-08/08-29-m0-evaluation-set-planning` 的 M0 业务边界为验收来源，严格区分真实 Provider、真实 Worker、业务持久化、浏览器和版本包证据。
- 真实运行必须显式使用 `/Users/hsikey/BenchMark/EvalData` 顶层恰好三份文件：一份 Markdown、一份 JSONL、一份 ZIP；不得复制样本正文、凭证、模型原文或内部 Checkpoint 到仓库或报告。
- 真实 E2E 使用 production AI 配置、隔离 PostgreSQL 业务库、独立 PostgreSQL Checkpointer 库、临时 storage 和单 Worker，覆盖上传、后台分析、资料角色确认、任务分组、场景标准共创、单题判定依据共创、下一版草稿、覆盖确认、冻结、Manifest/三分区包下载与隔离。
- 相同任务分组命令重放必须返回同一组业务任务、同一稳定顺序且不创建第二组任务；修复必须位于实际拥有该行为的 Repository/Service 路径，不能通过放宽真实 runner 断言掩盖 API 不稳定性。
- 对本轮发现的漏洞进行最小修复，并对权限、越权证据、迟到/重复命令、版本 lineage、runtime/judge/provenance 泄漏、失败清理和配置漂移做回归审查；不实现 M2 Skill 执行、Judge 或评测报告。

## Acceptance Criteria

- [ ] `make ai-smoke` 在当前已配置凭证下真实返回目标结构化结果，输出不含密钥、URL 密码、正文或 private reasoning。
- [ ] 真实隔离栈上的 runner 输出 `M0_REAL_AI_E2E_STAGE=complete`，并证明 3 份顶层输入展开为 5 份证据、确认 2 个任务/3 个 attempts、完成合同与两道题判定依据共创、冻结连续 `v1`。
- [ ] runner 机械校验 Manifest 整体 hash、runtime/judge/provenance 三分区 bytes/hash、ZIP 条目和身份一致，runtime allowlist 不含评分依据、老师判断、形成记录或凭证。
- [ ] 新增的分组幂等回归测试证明重放返回相同任务 ID 与顺序；现有 `cd backend && uv run pytest -q`、`make test`、适用的 `make build` 和 `git diff --check` 全部通过。
- [ ] 真实运行的临时容器、API/Worker、storage 和日志按精确目标停止/清理；报告只保留阶段、计数、哈希一致性、错误类型和未宣称边界。
- [ ] 修复分支合并到 `main` 后在 `main` 重跑完整质量门和目标回归；通过后再完成 Trellis 归档和旧分支安全删除。

## Notes

- Keep `prd.md` focused on requirements, constraints, and acceptance criteria.
- Lightweight tasks can remain PRD-only.
- For complex tasks, add `design.md` for technical design and `implement.md` for execution planning before `task.py start`.
