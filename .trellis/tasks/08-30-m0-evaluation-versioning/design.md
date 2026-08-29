# M0 评测版本与版本包设计

## Domain boundary

`evaluation_sets` 拥有 ScenarioContractRevision、WorkingSetDraft/Member、ContractImpactReview、CoverageSnapshot、EvaluationSetVersion 和版本包。它通过 case_builder Service 读取已确认题，不直接读其 Repository 或 Checkpointer。

## Freeze transaction

1. 命令校验 owner、expected revision、command id 和风险确认。
2. 事务内保存 freeze intent 并创建唯一 OperationJob。
3. Worker 在 staging 构建三分区文件、canonical Manifest 和哈希。
4. 校验 allowlist、泄漏规则和整体哈希，写 ready marker。
5. 单一业务事务 CAS 当前草稿 revision，创建连续版本并发布存储键。
6. 任一步失败只保留可重试 operation/error，不创建可见版本。

## Package contract

- Manifest 固定排序/序列化，记录 schema、版本、合同快照、题修订、来源文件哈希、冻结元数据和风险确认。
- runtime/judge/provenance 各自有 Schema allowlist 和分区哈希。
- 下载和 API 只读取版本记录指向的 ready 包，不重新序列化业务表。

## File ownership

- 独占：`backend/app/features/evaluation_sets/**`、`backend/app/lib/version_packages/**`、相关测试。
- 顺序共享：operations freeze handler、storage versions/staging 接口、StudioProjection、main/OpenAPI。
- 不修改 AI adapter、ingestion 安全逻辑或前端实现。

## Rollback

- 已冻结版本没有“修改回滚”；业务回退通过派生新草稿并冻结新版本。
- staging 可安全清理；ready 包只有在无版本引用时才能由维护任务清理。
