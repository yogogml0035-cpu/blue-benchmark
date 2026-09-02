# 实施计划：前端桌面化重构

单分支 `codex/frontend-desktop-redesign` 一次落地（用户已批准）。提交按稳定职责分批。

## 批次

1. **批次 A：全局体系**（globals.css 宽度档 + 坏 token + 头部注释；新 PageShell；8 组件接入除登录外）
2. **批次 B：建题会话页**（authoring.module.css 双栏 460px + 资料行两行 + composer 归位 + AuthoringConversationPage.tsx 对应调整）
3. **批次 C：其余页面**（studio canvas 1120 / ScenarioShelf 网格 / Upload / Version / Rubric / HumanScoring）
4. **批次 D：文档**（spec 更新 + 任务收尾）

## 每批次门禁

- `cd frontend && pnpm typecheck`
- 批次全部完成后：`pnpm build`、`make test`、`make contract-check`、Playwright 4 spec、preview 目检。

## 验证清单

- [ ] typecheck / build / make test / contract-check / git diff --check
- [ ] Playwright：authoring / external-authoring / human-scoring / lifecycle-preview
- [ ] preview 目检：审改 / 处理中 / 后台失败 / 等待恢复 / 重建连续性 @1280×800 与 390×844
- [ ] 人工评分硬合同逐条对照 human-scoring.md
- [ ] spec 写回 `.trellis/spec/frontend/components-and-styling.md`
