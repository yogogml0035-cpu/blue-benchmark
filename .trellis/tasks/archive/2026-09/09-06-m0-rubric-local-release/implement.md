# C5 实施与最终交付

## 进入条件

- 确认 C4（09-06-m0-rubric-system-validation）及其全部上游在 main 上完成验收；读取完成/归档记录和实际提交，不依赖已删 worktree。
- 在明确批准后创建 codex/m0-rubric-local-release 独立 worktree；保持 base_branch=main，复制 .env 并隔离测试。
- 本任务可落实父任务已批准的一次性旧数据处置范围，但现在的 planning 状态不授权执行。

## 执行顺序

1. 核对现场 Docker/数据库/服务与授权范围，建立脱敏目标清单和拒绝条件，不读取或输出凭证。
2. 实现显式安全重置入口与 dry-run/白名单/备份/回退，在本任务独占测试库覆盖错误目标、连接失败、部分失败和源文件保护。
3. 更新适用 runbook、启动/检查说明与命令入口；不得把 reset 放进 make test、启动或普通 migration。
4. 运行分支完整质量门与真实样本验收，按 project worktree 门禁合入 main，再在 main 重跑对应质量门。
5. 再次确认 SDK 版本、main 身份及 C4 系统证据；有升级/失败则补验证，未通过不切换。
6. 按设计停止自有旧写入进程、预览并备份目标两库，然后执行本次一次性重置与新 schema/checkpointer 准备。
7. 完成切换后数据库、空题库、注册/上传准备和实际服务检查，提供本地 URL、成功标记与失败诊断。
8. 保存源 hash、操作日志和私有证据的持久位置，交付父任务最终验收；仅在验证完成后按 Trellis 清理本子任务分支/worktree。

## 质量门

```bash
git diff --check
make test
make build
make frontend-e2e
make ai-smoke
make accept-web
```

- 另跑安全重置定向测试、真实 backend 集成 runner 与 C4 故障回归；上述真实入口必须使用 C1 样本和隔离 PostgreSQL。
- 当前项目两库的一次性操作不属于普通自动化测试命令；执行记录需含目标核对、备份位置、前后 schema/数据状态，不含原文或密钥。
- main 复验、切换后验证和用户未来自行上传是不同证据，不能互相替代。
- 核对 `.local-samples` 六文件 hash、无其他库/进程损伤，以及交付服务不会随子 worktree 清理失效。

## 收尾

- main 必须包含本任务提交并通过复验；失败时保留现场、分支和回滚资料，不强删。
- 子任务完成后由父任务核对 C1-C5 交付矩阵、共享规格和最终环境，再归档父任务；本任务不能代替未通过子任务宣布父任务完成。
- 是否推送远端依用户要求及仓库流程，不将本次任务拆分当作推送授权。
