# M0 评测版本与版本包

## Goal

把已确认的场景合同和题从可变题池组织成唯一下一版本草稿，经影响审查、完整性门和覆盖风险确认后，原子冻结为可回查、不可变、自包含的三视图版本包。

## Confirmed Facts

- 每个场景只有一条连续正式版本线和一个下一版本草稿，不支持并行分支。
- AI 只给影响/覆盖建议，不能解除 review_required、确认风险或冻结。
- 历史版本必须从已生成 Manifest/包读取，不能从可变业务表临时重拼。

## Requirements

### R1 — 合同修订与影响审查

- 场景合同每次变化形成新修订，并标记受影响题待复核。
- 确定性规则判定结构/硬门禁冲突；AI 给语义建议；老师最终逐题复核或明确批量确认无冲突。
- 同一冻结版本不得混用未复核的合同修订。

### R2 — 唯一下一版本草稿

- WorkingSetDraft 从最新冻结版本派生；加题、移除、修订和停用只改变下一版本。
- 已冻结版本不可写；丢弃草稿后只能从最新版本重新派生。

### R3 — 冻结门与覆盖风险

- 硬门检查合同确认、至少一题、当前合同复核、任务包/判定依据/来源/能力完整、无阻塞缺口和可见性已确认。
- 覆盖摘要只提示能力、维度、失败模式、重复和空白；无固定题数，覆盖不足经老师确认可继续。

### R4 — 原子三视图版本包

- freeze 命令保存意图并创建 `freeze_package` OperationJob，返回 `202`；Worker 生成 canonical Manifest、runtime/judge/provenance、分区哈希和整体哈希。
- `runtime` 不得含参考结果、评分规则、老师判断或历史评语；`judge` 与 `provenance` 也按 allowlist 构建。
- staging、哈希和 ready marker 全部成功后才原子创建可见 EvaluationSetVersion；失败不留下半版本，重试幂等。
- Manifest API 和下载读取同一已生成包。

## Out of Scope

- 前端冻结/历史页面。
- M2 被测 Agent、运行子集、Judge 执行和评测报告。
- 多版本分支、合并、成员权限和远程对象存储。

## Acceptance Criteria

- [ ] 连续 v1/v2、唯一草稿、历史不可变和草稿重建测试通过。
- [ ] 合同变化后 review_required、确定性无冲突批量确认和老师最终放行测试通过。
- [ ] 无题、未复核、阻塞缺口、必需文件失败、可见性未确认均阻塞冻结。
- [ ] 覆盖警告经明确确认后可冻，不设置固定题数。
- [ ] 重复 freeze command 不生成第二版本；打包失败不产生可见版本。
- [ ] canonical 包哈希稳定，API/下载指向同一整体哈希。
- [ ] 机械泄漏测试证明 runtime 不含 judge/provenance 字段或内容。
- [ ] `cd backend && uv run pytest -q` 与 `make openapi` 通过。

## Dependencies and Ownership

- 依赖 `m0-deep-agent-cocreation` 的已确认合同、题、形成记录和 coverage reviewer 端口。
- 独占：`backend/app/features/evaluation_sets/**`、版本包 builder/storage 发布逻辑及测试。
- 顺序共享：operations freeze handler、StudioProjection、`app/main.py`、OpenAPI。
- 不读取 Checkpointer 私有表，不修改前端产品文件。
