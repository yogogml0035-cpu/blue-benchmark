# M0 前端工作流实施计划

## Ordered checklist

1. 用规划态静态 Preview 完成桌面/窄屏方向验收，更新父任务 UI 合同。
2. 在前三个后端子任务完成后生成 OpenAPI 类型。
3. 建立工作台 shell、三导航和 StudioProjection 状态分发。
4. 接上传、后台操作、角色/分组确认和刷新恢复。
5. 接聚焦共创、本轮更新、标准与依据 sheet、resume 失败保答重试。
6. 扩展一屏一节 DraftEditor，移除生产 JSON。
7. 接下一版、影响审查、覆盖风险、冻结、历史和下载。
8. 重定向旧 cases 路由，完成 desktop/narrow/a11y 状态矩阵。

## Validation

```bash
cd frontend && pnpm typecheck
cd frontend && pnpm build
```

浏览器验收使用真实长度中文、长文件名和极值状态；HTTP 200、Preview 或截图不能替代最终真实 API 闭环。

## Handoff gate

- 四个 route family 可从创建场景走到冻结版本并下载。
- 页面无内部 Agent 字段、第二套 DTO、第二套编辑流程或未门控 fixture。
- 交给 `m0-integration-acceptance` 的是可运行 UI，而不是静态设计稿。
