# Implementation Plan

1. 建立 evaluation-set service、连接状态与稳定颜色纯函数及测试。
2. 实现彩色文件夹网格、加载/空/错误状态与创建 Dialog。
3. 实现详情页元数据、编辑和空集删除，连接后端 409/422。
4. 实现 CredentialPanel 的签发、轮换、撤销、刷新和脱敏时间线。
5. 实现 Agent 提示词模板与一次性 Dialog，覆盖复制成功、Safari fallback、未复制关闭确认和 state 清理。
6. 增加 20 卡片、同名、并发非空删除、旧凭证失效、无 token 泄漏的组件/API/E2E 测试。
7. 在 Chrome `1440x900`、Chrome/Safari `1280x720` 目检文件夹、Dialog、长名称/描述和凭证状态。
8. 运行 typecheck/test/build、后端回归、OpenAPI 漂移、Skill connection 测试与 `git diff --check`，经 `trellis-check` 后提交、合并、main 复验与归档。

## Risky Files

- 一次性提示词模板与 Dialog
- 凭证 mutation 响应处理
- 评测集删除与刷新逻辑

## Stop Conditions

- token 出现在任何持久化或测试 artifact；
- Safari 复制失败后用户无法取得提示词；
- 前端能够删除非空评测集或创建时自动签发凭证；
- 卡片视觉偏离 AURA 或在正式桌面视口溢出。
