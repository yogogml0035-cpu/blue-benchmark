# 当前场景与题目列表合同审计

## 已实现事实

- `POST /api/scenes` 创建场景。
- `GET /api/scenes` 返回场景列表，每项包含 `question_count` 与 `active_credential_count`。
- `GET /api/scenes/{scene_id}` 返回场景与凭证安全状态。
- `GET /api/questions` 当前允许省略 `scene_id`，因此能够返回跨场景全部题目。
- `GET /api/questions?scene_id=<id>` 已能按场景过滤，并可叠加 `status`。
- 当前无效 `scene_id` 返回空列表，不返回场景不存在错误。
- 外部批量上传的场景归属由 Bearer 凭证决定，不读取 payload 中的场景字段。

## 需求差异

用户确认未来前端以场景为第一层：场景列表 → 场景内题目列表 → 题目详情；不保留全部题目页面、跨场景搜索或场景筛选器。

因此现有数据库与场景功能可复用，差异集中在：

1. 前端交接稿的信息架构；
2. 管理员题目列表接口的必填场景边界；
3. OpenAPI、测试和 README 的同步口径。
