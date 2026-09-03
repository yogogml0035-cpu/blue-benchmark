# Implementation Plan

1. 实现 question service、状态文案/动作映射与搜索筛选排序纯函数。
2. 构建 200 项紧凑列表、空/过滤空/加载/错误状态和详情导航。
3. 构建双栏 Workbench 与六类材料阅读态，记忆材料默认折叠。
4. 实现材料编辑草稿、取消、脏状态保护、标题单改、保存并重新生成和 stale 冲突面板。
5. 实现 visible-only 生成轮询、失败重试和手动刷新。
6. 实现 CriterionDraft：首次未选、选择/取消/删除/撤销、手工新增、完整 criterion、0–10 控件和 1–20 校验。
7. 实现保存确认、confirmed 状态、独立发布、重新打开审改和状态刷新。
8. 实现普通删除、生成中禁用、发布态重开、曾发布标题二次确认。
9. 增加状态矩阵、长材料/长标题/20 维度、竞态、键盘与 Chromium/WebKit E2E。
10. 运行 typecheck/test/build、后端回归、OpenAPI 漂移和 `git diff --check`，经 `trellis-check` 后提交、合并、main 复验与归档。

## Risky Files

- question API service 与状态映射
- candidate draft/payload 投影
- 双栏滚动与 sticky 操作区
- 未保存离开保护

## Stop Conditions

- AI 初稿可以不经老师保存直接发布；
- 材料修改后旧维度仍显示为有效；
- stale 响应覆盖本地草稿；
- 已发布题可直接删除或重开后不要求标题；
- 1280px 下长内容造成横向溢出、遮挡或主操作不可达。
