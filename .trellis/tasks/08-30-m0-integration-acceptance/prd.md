# M0 集成与真实样本验收

## Goal

用合成 fixture 和用户现有三份真实材料验证完整 M0：从创建场景、导入任务包、共创合同/题，到冻结、下载和机械校验版本包；同时交付可复制启动说明和与最终源码一致的 Trellis 规范。

## Confirmed Facts

- 默认 CI 不提交真实业务样本，只用合成/脱敏 fixture。
- 财报 JSONL、MEGA ZIP、媒体沟通 Markdown 当前是两个真实任务加一个 runtime Brief 候选，不是三道题。
- Preview、HTTP 200、监听端口和文档截图都不是闭环运行证据。

## Requirements

### R1 — 默认自动化

- `make test` 覆盖后端、生成合同和前端类型；`make build` 覆盖生产构建。
- 合成 fixture 包含 100 行后关键反馈、Markdown 尾部判断、多任务/多 attempts 和 runtime/judge/provenance 泄漏标记。
- 不把真实正文、凭证、Checkpoint 或临时模型输出提交 Git。

### R2 — 真实样本闭环

- 验证 JSONL 是一个任务的事件流并保留多次生成/反馈；MEGA 三文件归为一个任务包；Brief 建议为 runtime 输入。
- 两个任务分别完成单题共创，加入同一场景下一版并冻结。
- 解包后机械验证分区哈希、整体哈希和 runtime 信息隔离。

### R3 — 重启与恢复

- 在 batch 分析、等待老师回答、答案已保存未 resume、produced 未投影和 freeze 过程中分别刷新/重启。
- 证明不丢答案、不重复模型调用、不采用 raw latest/stale branch。
- 删除已完成共创 thread 后业务资产仍完整，活动 thread 不被清理。

### R4 — 真实 UI 与运维说明

- 浏览器走通桌面和窄屏主流程、键盘/焦点/sheet/reduced-motion 和错误恢复。
- README 给出数据库迁移、Checkpointer setup、API、单消费者、前端地址、成功标记、失败检查和人工验收路径。
- 更新 Trellis specs 为最终源码事实，删除 Walking Skeleton 过时边界。

## Out of Scope

- 把真实样本复制进 Git、公开分享或上传到非批准服务。
- 性能压测、生产部署、M1/M2 和多人协作。

## Acceptance Criteria

- [ ] `make test` 与 `make build` 通过。
- [ ] 合成 fixture 默认 CI 全绿，真实样本只在本地显式运行。
- [ ] 三份真实材料的任务/角色分类符合已确认边界。
- [ ] 两道题冻结为同一 v1，下载包哈希和 runtime 隔离机械通过。
- [ ] 三个 Checkpoint 故障点和 freeze 重启点恢复通过，无重复模型调用。
- [ ] 完成 thread 删除后业务回查完整；活动 thread 受保护。
- [ ] 桌面/窄屏真实浏览器闭环通过，Preview 不冒充结果。
- [ ] README 命令在干净本地环境可复制，规范与源码一致。

## Dependencies and Ownership

- 严格依赖前四个子任务完成；发现业务缺陷时回到对应所有者修复，不在集成任务复制逻辑。
- 独占：跨层/端到端测试、合成验收 fixture、真实样本本地 runner、README、最终 harness/spec 刷新和验收报告。
- 共享：Makefile、配置示例和少量测试 hook；业务源码变更必须回到原子任务所有权。
