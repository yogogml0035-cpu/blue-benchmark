# 前端桌面化重构

## Goal

把全站从 480–880px 窄栏竖屏式布局重构为桌面宽版双栏工作台。用户反馈：当前界面"是竖屏的，根本不是一个网页，UI 布局乱、长度和尺寸全是拉长或缩小，根本没法用"。根因是已删除的 `.interface-design/system.md` 的「一栏聚焦」窄栏体系：建题会话页整页 760px 居中且「下一步」栏钉死 300px，长表单塞入导致文件名一字一行、输入框拉变形。

## 用户已确认的方向

1. **布局范式**：宽版双栏工作台——保留现有信息架构与流程，全局宽度体系改为真正的桌面布局（整体最大 1280–1440px），不做全局左侧导航的后台式改版。
2. **草稿长表单位置**：留在建题会话页右栏并加宽至 460px，资料行改两行结构。
3. **交付方式**：单任务单分支一次落地（视觉 token 牵一发动全身，子任务不可独立验收；用户已批准共用分支）。

## Requirements

### R1 全局宽度体系
- `.page-narrow` 480px（登录）不变；`.page-mid` 880→1040；`.page-wide` 1080→1280；新增 `.page-max`（fluid，max 1440）供建题会话等工作面。
- 修复坏 token：`--text-1` → `--text`（globals.css）；`--t-17` → 有效档（humanScoring.module.css）。
- globals.css 头部注释从指向已删除的 `.interface-design/system.md` 改为指向 `.trellis/spec/frontend/`。
- 移动端 ≤720px 单列行为保留。

### R2 壳层去重
- 新建 `components/shell/PageShell.tsx` 统一渲染 DeskRail + PreviewBar + `<main class="page …">`；除登录页外全部功能组件复用。
- 不改变任何 `data-testid`、可访问名、`aria-label`、aria-busy 行为。

### R3 建题会话页（重点）
- 页面放宽至 `.page-max`（1440）。
- ≥1024px 双栏：`minmax(0,1fr) 460px`，右栏 sticky。
- 「资料角色与优先级」行改两行结构：文件名独占一行（ellipsis），角色下拉+优先级在第二行；删除 `overflowWrap:"anywhere"`。
- DraftReview 留右栏：栏内 textarea min-height 与 minRows 按字段收敛，不再拉变形。
- Composer 在会话列内 sticky 底部，不再用 `calc(100%-300px-…)` 骑在右栏上。

### R4 其余页面适配
- 工作台 `.canvas` 720→1120（左侧 192px 导航保留）。
- 场景列表放宽至 1280，改响应式卡片网格。
- 上传/版本页套用 1040/1280 档。
- 评分规则页页宽 1280，左上下文栏 280–360 保留。
- 人工评分页 entry 720→1040，遵守 `.trellis/spec/frontend/human-scoring.md` 硬合同（DOM 顺序、宽屏评分栏、390px 不溢出）。

## 约束（红线）

- 视觉语言不动：浅色、中性灰 + `--action` 黑主按钮 + `--accent` 蓝链接；色板/字阶/圆角保留。
- 不引入 Tailwind / CSS-in-JS / 组件库；沿用 globals.css token + CSS Modules。
- `?preview=` 状态预演机制与 fixtures 不动（dev-only，不打真实 API）。
- Playwright 全量 4 spec 必须通过（守住 testid、可访问名、390×844 无横向溢出）。

## Acceptance Criteria

- [ ] AC1 宽屏（≥1280）下建题会话页为「会话流 + 460px 右栏」双栏，无窄条居中；资料名不再一字一行；表单控件尺寸正常；composer 不遮挡右栏与内容。
- [ ] AC2 全站页面（场景列表/工作台/上传/版本/建题/规则/人工评分）在 1280×800 下使用新宽度体系，无 720–880px 窄条。
- [ ] AC3 壳层仅一份实现（PageShell），登录页除外。
- [ ] AC4 `pnpm typecheck`、`pnpm build`、`make test`、`make contract-check`、`git diff --check` 全部通过。
- [ ] AC5 Playwright 全量 4 spec 通过（authoring / external-authoring / human-scoring / lifecycle-preview）。
- [ ] AC6 `?preview=` 逐状态目检建题会话页（审改/处理中/后台失败/等待恢复/重建连续性）在 1280×800 与 390×844 两档无布局破损、无横向溢出。
- [ ] AC7 新宽度体系与 PageShell 结论写回 `.trellis/spec/frontend/components-and-styling.md`。
