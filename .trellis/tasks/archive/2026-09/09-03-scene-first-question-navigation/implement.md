# Implementation Plan

## Child 1: Scene-first handoff

- [x] 将前端交接稿首页改为场景列表，并补充创建场景入口、空状态和场景卡片信息。
- [x] 将题目列表改为场景详情的子页面，仅保留场景内状态筛选。
- [x] 删除全部题目入口、跨场景筛选和“场景只是普通标签”的描述。
- [x] 保持六类材料、两字段评分维度、上传与发布流程不变。
- [x] 全文检索冲突术语并运行 Markdown/差异检查。
- [x] 完成子任务检查、记录交付文件并按项目门禁收尾。

## Child 2: Required scene question list

- [x] 将管理员题目列表 Router、Service、Repository 的 `scene_id` 改为必填。
- [x] 通过 Scenes Service 验证场景存在；缺参返回 422，不存在返回 404。
- [x] 删除无场景全量查询分支，保留场景内 `status` 筛选。
- [x] 更新 API 测试：缺参、无效场景、双场景隔离、场景内状态筛选和授权。
- [x] 更新 OpenAPI 合同测试并运行 `make openapi`。
- [x] 修正 README 中“统一题库/全部题目”口径和管理员调用示例。
- [x] 运行 `git diff --check`、`make test`、`make build`。
- [x] 完成 `trellis-check`、提交、合并回 `main` 并在 `main` 复验后归档。

## Final acceptance

- [x] 交接稿、README、OpenAPI 和运行时 API 对场景层级的描述完全一致。
- [x] 仓库内不存在不带 `scene_id` 的题目列表调用或测试。
- [x] 两个子任务均完成串行分支闭环，父任务再做最终验收与归档。
