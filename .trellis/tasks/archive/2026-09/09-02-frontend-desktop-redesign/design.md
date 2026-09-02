# 技术设计：前端桌面化重构

## 病灶定位（已核实的代码事实）

| 症状 | 根因 | 位置 |
|---|---|---|
| 建题会话页窄条居中 | `.page { max-width:760px }` + `.page` 全局居中 | `authoring.module.css:1-4`、`globals.css:233-236` |
| 长表单塞 300px 栏 | `@media ≥900px .workspace { grid-template-columns: minmax(0,1fr) 300px }` | `authoring.module.css:247-261` |
| 资料名一字一行 | `.materialRow` 右列 minmax(150px,220px) 挤压 + `overflowWrap:"anywhere"` | `authoring.module.css:175-187`、`AuthoringConversationPage.tsx:1188-1189` |
| 输入框拉变形 | `textarea.control { min-height:84px }` + 窄栏 + AutoTextarea 自增高 | `globals.css:470-474`、`AutoTextarea.tsx` |
| composer 遮挡 | `.composer` sticky+blur+z-index:5，`width:calc(100%-300px-…)` | `authoring.module.css:189-201,253-255` |
| 全站窄条 | `.page-mid` 880 / `.page-wide` 1080 闲置 / `.canvas` 720 | `globals.css:238-248`、`studio.module.css:57-64` |
| 壳层重复 8 份 | 无共享 layout，DeskRail+PreviewBar+main 各自拼装 | ScenarioShelf/StudioShell/Upload/Version/Authoring×2/Rubric/HumanScoring |
| 坏 token | `--text-1`、`--t-17` 未定义，静默回退 | `globals.css:879`、`humanScoring.module.css:56,238` |

## 方案

### 1. globals.css
- 宽度档：`.page-narrow` 480（不动）；`.page-mid` 880→1040；`.page-wide` 1080→1280；新增 `.page-max { max-width:1440px }`。
- `.canvas` 内内容行宽靠 `.messageBody { max-width:72ch }` 等阅读度量约束，不做全局窄栏。
- 修 `--text-1`→`--text`；头部注释指向 `.trellis/spec/frontend/`。
- 其余 token、组件类、动效、reduced-motion 分支全部不动。

### 2. PageShell（`components/shell/PageShell.tsx`）
```tsx
PageShell({ crumbs, previewStates, mainClassName, children })
// 渲染：<DeskRail crumbs/> <PreviewBar states/> <main class={`page ${mainClassName}`}>{children}</main>
```
- 登录页（page-narrow + 自有结构）不接入。
- StudioShell 的侧栏+画布结构在 main 内部，仍可接入 PageShell（crumbs/preview 逻辑不变）。
- 迁移为纯结构调整，逐页核对 testid 与可访问名不变。

### 3. authoring.module.css + AuthoringConversationPage.tsx
- `.page { max-width:760px }` → 去除模块内 max-width，main 用 `.page-max`。
- `@media ≥900px` 改为 `@media ≥1024px .workspace { grid-template-columns: minmax(0,1fr) 460px }`；`.nextAction { position:sticky; top:76px }` 保留。
- `.materialRow` 两行结构：文件名行（`display:flex` + ellipsis + min-width:0）+ 控件行（`grid-template-columns: minmax(0,1fr) 96px`）。
- 删除 `AuthoringConversationPage.tsx:1188-1189` 的 `minWidth:0/overflowWrap:"anywhere"` 内联样式，文件名截断交给 CSS。
- Composer 移入 transcript 列容器（TSX 中从 workspace 外移到 transcript 列底部），sticky bottom 生效范围限于会话列；删除 ≥900px 的 `width:calc(100%-300px-…)` 与 z-index 遮挡面。注意 `authoring-send`、`authoring-attachment-picker` 等 testid 与表单逻辑（standardAnswerMode、processing 禁用）零改动。
- DraftReview 控件：右栏内 `.control` 高度收敛（栏内 textarea min-height 降为 56–64px），`minRows` 按字段复核（任务指令 2、必须包含/禁止内容/必要背景 2–3、单一标准答案 4、坏样本 2）。

### 4. 其余页面
- StudioShell：`studio.module.css .canvas { max-width:720px }` → 1120。
- ScenarioShelf：main → `.page-wide`；列表容器改 `display:grid; grid-template-columns:repeat(auto-fill,minmax(320px,1fr))`（ScenarioShelf.module.css，视现有结构最小调整）。
- Upload/Version：main 类切到 1040/1280 档。
- Rubric：`.workspace { minmax(280px,360px) minmax(0,1fr) }` 保留，页宽 1280。
- HumanScoring：`entryPage` 720→1040；评分栏 400px 硬合同不动；`--t-17`→`--t-16`。

## 风险与对策

- **Playwright 断言**：全部 testid/可访问名保持；composer DOM 位置移动不影响以 testid/label 定位的断言。
- **preview 状态**：不改 preview.tsx 与 fixtures；仅目检。
- **人工评分硬合同**：human-scoring.md 契约逐条对照，只放宽阅读列宽度。
- **回归**：typecheck + build + make test + 4 spec + preview 目检（1280×800 / 390×844）。
