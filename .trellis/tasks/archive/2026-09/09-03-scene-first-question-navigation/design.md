# Technical Design

## Product hierarchy

未来前端采用固定层级：

```text
GET /api/scenes
  → 场景列表
  → GET /api/questions?scene_id=<scene_id>&status=<optional>
    → 当前场景题目列表
    → GET /api/questions/{question_id}
      → 题目详情
```

场景是第一层业务容器。全局题目集合仍存在于数据库中，但不再作为产品入口或公开的无范围列表能力。

## API tightening

保留现有 `GET /api/questions` 路径，避免新增重复的嵌套列表接口；将 `scene_id` 从可选 Query 参数改为必填。`status` 仍是场景内可选筛选。

Router 负责必填参数形状；Question Library Service 通过 Scenes Service 校验场景存在，再调用 Repository。Repository 的 `list_questions` 要求非空 `scene_id` 并始终生成场景过滤条件，不能保留“未传则不过滤”的分支。

错误合同：

- 缺少 `scene_id`：FastAPI/Pydantic 统一返回 `422 VALIDATION_ERROR`；
- 场景不存在：返回 `404 RESOURCE_NOT_FOUND`，消息为“场景不存在。”；
- 未登录：保持 401。

## Compatibility

这是有意的破坏性管理员 API 变更。现有上传 Skill 不调用管理员题目列表，因此不受影响。所有仓库内调用者、测试、README 示例和 OpenAPI 必须迁移为显式传入 `scene_id`；不提供兼容参数、默认场景或隐藏全量入口。

## Documentation boundary

前端交接稿只描述未来界面和用户路径，不声称当前仓库已有前端。README 描述当前后端事实：场景列表是导航起点，题目列表必须在场景范围内查询。

## Rollback

本任务不改数据库。若需要回滚，只需恢复可选 Query 参数、Service/Repository 可选过滤分支、OpenAPI、测试和文档；现有场景与题目数据不发生迁移或丢失。
