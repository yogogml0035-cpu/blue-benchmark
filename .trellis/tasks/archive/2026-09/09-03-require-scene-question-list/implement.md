# Implementation Plan

- [ ] 修改 Question Library Router，使 `scene_id` 成为必填 Query 参数并声明 404。
- [ ] 修改 Service，通过 Scenes Service 校验场景存在。
- [ ] 修改 Repository，删除无场景全量查询分支。
- [ ] 更新题目列表、发布覆盖、授权与双场景隔离测试。
- [ ] 更新 OpenAPI 合同测试并运行 `make openapi`。
- [ ] 更新 README 的场景优先查询说明和示例。
- [ ] 搜索仓库内全部 `/api/questions` 列表调用，确保均传入 `scene_id`；题目详情/命令路径不误改。
- [ ] 运行 `git diff --check`、`make test`、`make build`。
- [ ] 使用 `trellis-check` 做权限、错误码、跨场景泄漏与合同一致性审查。
- [ ] 提交、fast-forward 合并回 `main`，在 `main` 复验后归档并安全删除任务分支。
