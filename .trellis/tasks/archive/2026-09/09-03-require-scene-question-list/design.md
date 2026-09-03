# Technical Design

## Router contract

`question_library/router.py::list_library` 保留 `/questions` 路径，将签名改为必填 `scene_id: str = Query(...)`，`status` 保持可选。Router 的 `responses` 增加场景不存在的 404 说明；缺参继续由全局验证处理器投影为 422。

## Service boundary

`question_library/service.py::list_library` 接受必填 `scene_id`。在查询题目之前，通过 `scenes.service` 暴露的业务入口确认场景存在；不存在时沿用 `404 RESOURCE_NOT_FOUND / 场景不存在。`。

Question Library 不直接依赖 `scenes.repository`。若现有 `get_scene_or_404` 返回的 DTO 过重，可在 Scenes Service 内增加只做存在性校验的窄入口，但不复制场景查询逻辑。

## Repository boundary

`question_library/repository.py::list_questions` 将 `scene_id` 改为必填字符串，查询永远包含 `EvalQuestionRow.scene_id == scene_id`。删除可选分支是防止未来调用者绕过 Router 后重新获得全量查询。

## Tests and contract

- 改写现有 `test_library_filters_by_status_and_scene`，删除无场景成功断言。
- 新增缺少 `scene_id`、不存在场景、双场景隔离、场景内状态筛选测试。
- 更新发布覆盖测试中对列表数量的断言，使其显式携带题目所属 `scene_id`。
- 更新场景凭证越权测试，请求使用有效 `scene_id`，确保失败原因仍是 401 而非参数缺失。
- 更新 OpenAPI 生成文件与合同测试，断言 `scene_id.required=true`。
- 更新 README 的领域模型与题目列表调用示例。

## Compatibility and rollback

该变更只影响管理员列表读取，是有意破坏性合同；上传 Skill 与写入路径不受影响。无需数据库迁移。回滚时恢复可选参数和 Repository 可选过滤分支，并重新生成 OpenAPI。
