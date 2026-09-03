# 收紧题目列表接口的场景边界

## Goal

要求管理员题目列表查询必须提供有效 `scene_id`，删除无场景全量查询，并同步 Service、Repository、测试、OpenAPI 与 README，使后端合同只能支持“进入场景后查看题目”。

## Requirements

- 保留 `GET /api/questions` 路径，但 `scene_id` 从可选参数改为必填参数。
- `status` 仍为可选参数，但只在指定场景内筛选。
- 缺少 `scene_id` 时返回统一 `422 VALIDATION_ERROR`。
- `scene_id` 对应场景不存在时返回 `404 RESOURCE_NOT_FOUND`，不得返回空列表。
- Service 必须通过 Scenes Service 验证场景存在，不直接读取 Scenes Repository。
- Repository `list_questions` 必须要求非空 `scene_id` 并始终附加场景过滤条件。
- 不新增 `/api/scenes/{scene_id}/questions` 第二套列表路由，不保留隐藏全量查询参数或管理员后门。
- 题目详情和命令路由保持 `/api/questions/{question_id}/...`，不做无关路径迁移。
- 场景创建、凭证生命周期、外部批量上传及题目状态机保持不变。
- 同步 OpenAPI、合同测试、README 和所有仓库内调用者。

## Acceptance Criteria

- [ ] `GET /api/questions` 不带 `scene_id` 返回 422。
- [ ] 有效 `scene_id` 只返回该场景题目，并支持场景内 `status` 筛选。
- [ ] 不存在的 `scene_id` 返回 404 `RESOURCE_NOT_FOUND`。
- [ ] 构造两个场景各自有题时，任一请求都不能获得跨场景合集。
- [ ] 未登录仍返回 401；场景上传凭证仍不能访问管理员题目列表。
- [ ] OpenAPI 将 `scene_id` 标记为 required，并记录 401/404/422。
- [ ] README 不再把无范围“统一题库”作为查询入口，示例均带 `scene_id`。
- [ ] `make test`、`make build`、`git diff --check` 通过。

## Out of Scope

- 数据库迁移或现有题目数据变更。
- 新前端实现。
- 跨场景搜索、移动或复制。
- 修改外部上传 Skill 的场景凭证归属逻辑。
