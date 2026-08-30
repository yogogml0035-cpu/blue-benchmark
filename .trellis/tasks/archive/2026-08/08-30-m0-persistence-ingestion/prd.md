# M0 持久化与上传基础

## Goal

把当前进程内 Stub 升级为可跨重启、可审计、可幂等恢复的 M0 业务与文件基础，并交付上传批次、安全解包、统一后台操作和场景工作台业务投影，供后续共创、版本冻结和前端使用。

## Confirmed Facts

- 当前 auth、workspaces、case_builder 都使用进程内 Repository；重启即丢失。
- 当前只支持单文件、请求内同步处理，没有 Worker、OperationJob、真实文件存储或 PostgreSQL。
- 父任务已经锁定业务表与 Checkpointer 分离、文件只保存服务端存储键、GET 只读、长操作返回 `202` 的合同。
- 本子任务必须先于其余四个 M0 子任务完成。

## Requirements

### R1 — PostgreSQL 业务权威

- 引入数据库会话、迁移和 Repository，实现 auth、workspaces 与新增 M0 业务表的持久化。
- 保持现有登录、私有场景归属与错误码；跨用户访问继续返回 403。
- 业务迁移与 Checkpointer setup 分开，应用启动只检查 schema ready。

### R2 — 文件与证据基础

- 本地开发存储使用服务端生成键，分 uploads、evidence、versions、staging；HTTP、日志和模型上下文不返回宿主绝对路径。
- 支持 `.md/.txt/.json/.jsonl/.zip`；拒绝路径穿越、绝对路径、符号链接、特殊文件、嵌套/数量/大小超限和 zip bomb。
- 每个文件保存 SHA-256、media type、解析状态和 canonical locator 视图。

### R3 — 上传批次与统一后台操作

- 一次上传形成 UploadBatch 和 0..N EvidenceFile，成功接收后返回 `202` 与 StudioProjection，不等待分析。
- OperationJob 覆盖 batch_analysis、cocreation_start/resume/reproject、coverage_review、freeze_package，拥有租约、过期回收、有限重试、command/revision 幂等和 commit-time CAS。
- GET 轮询不创建任务、不续租、不推进状态。

### R4 — 可恢复业务投影

- `StudioProjection` 提供唯一 discriminated `next_action`、active_operation、latest_receipt、阻塞项和必要资产摘要。
- 前端不需要理解 Worker、Agent、thread、Checkpoint 或 Graph node。

## Out of Scope

- Deep Agent 模型调用、任务分组、场景/单题共创。
- 评测集冻结、版本包和下载。
- 前端场景工作台实现。
- 生产对象存储、Redis、Celery、多租户权限和 DLP。

## Acceptance Criteria

- [ ] PostgreSQL 重启后账号、场景、上传批次、文件元数据和 OperationJob 仍可读取。
- [ ] auth/workspaces 现有行为和跨用户 403 通过回归测试。
- [ ] 多文件/ZIP 安全边界和每文件部分失败有测试。
- [ ] 所有 OperationJob kind 具有重复命令、租约回收、重启恢复、迟到分支和陈旧 revision 测试。
- [ ] 上传命令返回 `202`，轮询 GET 无副作用。
- [ ] 对外 DTO、错误、日志和测试制品不含绝对路径、凭证或 Checkpoint 内部字段。
- [ ] `cd backend && uv run pytest -q` 通过；合同变化后 `make openapi` 通过。

## Dependencies and Ownership

- 顺序：本任务完成后才能启动 `m0-deep-agent-cocreation`。
- 独占：数据库/迁移、存储 adapter、`app/lib/operations`、上传解包与 ingestion 模块及其测试。
- 共享集成点：现有 auth/workspaces/case_builder Router、Schema、Service、Repository、`app/main.py`、OpenAPI；本任务先建立持久化与上传合同，后续任务只能在其上顺序扩展。
- 不修改：前端产品文件、evaluation_sets 版本逻辑、Deep Agents adapter。
