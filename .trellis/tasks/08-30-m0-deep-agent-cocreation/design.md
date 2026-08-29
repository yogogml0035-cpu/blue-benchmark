# M0 Deep Agent 与共创设计

## Runtime baseline

以父任务 `research/prestart-spike-results.md` 的精确版本和结果为事实源。生产结构化输出固定 `ToolStrategy`；当前 provider 不发送 temperature，也不使用 ProviderStrategy。

## Ports and ownership

- EvidenceAnalyzer：fresh attempt，返回 BatchAnalysis。
- StandardCoCreator：start/resume/reproject，唯一稳定 Checkpointer thread。
- CoverageReviewer：fresh attempt，只接收结构化业务快照。
- Service 在 Graph 外完成 revision、confirmation、answer、OperationJob 和业务投影事务。

## Safety harness

- ReadOnlyEvidenceBackend 只接收服务端 scope 和虚拟 `/evidence/**`，不返回宿主路径。
- 替换 FilesystemMiddleware 的 0.7.11 `_permissions` 私有参数只在 Adapter 工厂出现，并有签名断言。
- ModelToolSurfaceMiddleware 同时实现 sync/async wrap/after hook：过滤模型可见工具并在工具节点前拒绝隐藏调用。
- 精确 HarnessProfile 只启动注册一次，关闭 general-purpose subagent并全局排除 task/write/execute。

## Checkpoint protocol

- CoCreationSession 保存 stable thread、accepted/pending/produced Checkpoint 指针、business revision、AI Profile 和 Graph Schema 版本。
- resume 输入必须带 accepted checkpoint_id；raw latest 只用于审计，不是恢复权威。
- answer 已保存但 resume 未执行、进程中止、produced ahead/business behind、stale branch 和 incompatible graph 都有单独恢复路径。
- Checkpoint 加密、独立迁移、独立权限和按 thread 删除；活动/待答/projection_pending thread 受清理保护。

## File ownership

- 独占新增：`backend/app/lib/ai_runtime/**`、`backend/app/features/case_builder/cocreation_*`、`task_grouping_*`、对应测试与 provider smoke 标记。
- 顺序共享：case_builder 主 Router/Schema/Service/Repository、operations handler registry、settings/依赖锁和 OpenAPI。
- 父任务拥有 Spike 脚本/结果；实施只能复制其合同到生产 Adapter，不能把测试凭证或临时数据库配置带入源码。

## Rollback

- Provider/版本矩阵任何关键行失败即停止，不降级自由文本。
- Checkpoint 版本升级不兼容时保持旧图路由或 continuity reset，不直接覆盖旧 thread。
- 模型失败不部分确认分组、合同、题或答案。
