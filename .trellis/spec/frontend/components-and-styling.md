# 组件、交互与样式

## 组件形状

共享控件保持小而明确，Props 使用本地 `type` 或内联对象类型。包装原生元素时继承原生属性，而不是重新声明一套事件和可访问性字段；参考 `components/ui/Button.tsx::ButtonProps` 和 `AutoTextarea.tsx`。

业务页面由小组件组合，而不是一个文件重复所有细节：`StudioShell` 组合当前、题、版本三个区；`AuthoringConversationPage` 组合建题快照、题目输入、坏样本和组合确认动作；`AuthoringRubricPage` 和 `HumanScoringPage` 分别承担规则审阅与单份答卷评分；版本页只读历史，不再承载组集/冻结编辑器。

对互斥的有限变体使用字面量联合和穷举 `Record`，例如 Button 的 `Variant` / `Size`、Note 的 `Tone`、`AuthoringConversationPage.tsx::STATUS_CLASS`。不要靠自由字符串拼接新增不可检查的样式变体。

## 版面宽度与页面壳

全站是桌面宽版工作台，版面宽度只用 `globals.css` 里这一套档位，不要在 Feature 里另立 max-width：

- `.page-narrow` 480px：登录页；
- `.page-mid` 1040px：表单页、详情页（上传、版本、新建题）；
- `.page-wide` 1280px：列表页（场景卡片网格）、评分规则页；
- `.page-max` 1440px：会话/工作面双栏布局（建题会话）。

页面壳统一用 `components/shell/PageShell.tsx`：入参 `crumbs` / `right` / `previewStates` / `mainClassName`，渲染 DeskRail + PreviewBar + `<main class="page …">`。除登录页外所有页面复用；`previewStates` 用页面内模块级 `as const` 数组声明。工作台这类自带全宽布局（侧栏 + 画布）的页面传 `chromeOnly`，只复用顶栏与预演条，自管 `<main>`。新增页面不要再手拼 `{rail}{previewBar}<main>` 三件套。

双栏工作面的约定（参考 `authoring.module.css` / `rubric.module.css`）：

- 断点 ≥1024px（或 960px）才开双栏，窄屏回落单列；
- sticky 侧栏必须加 `max-height: calc(100dvh - 92px); overflow-y: auto` 兜底——比视口高的长表单钉住后底部仍可滚动到，否则内容永远不可达；
- 长表单里的文件名行用「两段式」：名称独占一行 `nowrap + ellipsis`，控件（下拉/数字）在第二行；禁止 `overflow-wrap: anywhere` 当截断用，窄栏里会一字一行；
- 会话输入卡（composer）sticky 在所属列内部，不允许跨列骑压。

## 浮层（Sheet）

`components/ui/Sheet.tsx` 提供三个原语：

- `Sheet`：按需浮层，桌面右侧滑入、窄屏全屏；打开时锁定背景滚动并把焦点移入，关闭后返回触发器；Escape 关闭，Tab 在面板内循环。
- `ConfirmSheet`：不可逆动作或高后果选择前的二次确认。
- `TechnicalDisclosure`：hash、Manifest、错误码等机器可读信息默认隐藏。

Sheet 的样式在 `globals.css` 的 `.sheet-overlay` / `.sheet-panel` / `.sheet-panel-head` / `.sheet-panel-body`；宽屏变体加 `.sheet-panel-wide`。不要在 Feature 中重复实现浮层。

## 异步交互

- 提交函数先清空本次错误并设置 `busy`，用 `try/catch/finally` 收口；参考 `ScenarioShelf::submit` 和 `UploadPage::submit`。
- 提交中的按钮通过 `busy` / `disabled` 禁止重复操作，Button 可用 `busyLabel` 给出动作反馈。
- 受保护页面在 `useSession` 仍为 `loading` 时只显示骨架，不闪现私有内容。
- 页面级失败使用 `StatePanel` 提供原因和唯一下一步；局部命令失败使用 `Note` 或字段错误，不把所有错误堆到页面顶部。
- 后端命令成功后用返回的完整快照更新页面，不靠本地布尔值宣布 Case 已确认。

## 可访问性

保持当前可验证模式：

- 表单有 `<label>` / `htmlFor` 或明确 `aria-label`；
- 纯图标按钮必须有动作名称，装饰图标使用 `aria-hidden`；
- 互斥选择用 `role="group"` 与 `aria-pressed`，阅读进度使用 `aria-current`；
- 加载区使用 `aria-busy="true"`，失败 Note 使用 `role="alert"`；
- 非提交按钮显式 `type="button"`；
- `globals.css` 保留 `:focus-visible` 和 `prefers-reduced-motion: reduce` 分支。

新增交互时要验证键盘可达、焦点可见、忙碌时不可重复提交、错误仍能与具体字段或动作对应。任务分组使用原生 `fieldset`、`label`、`select` 和按钮支持拆分/合并，不依赖拖拽或隐藏的坐标状态。

## 样式边界

`src/app/globals.css` 是全站 token 和通用原语的来源：颜色、字号、间距、圆角、阴影、动效曲线，以及 `.page`、`.sheet`、`.btn`、`.control`、`.state` 等跨 Feature 类。复用已有的 `var(--s-4)`、`var(--text-2)` 等具体 token，不要在 Feature 中建立第二套同义 token。

较大的 Feature 布局和专用视觉用 colocated CSS Module：

- `workspaces/components/ScenarioShelf.module.css`；
- `workspaces/components/studio.module.css`（场景工作台三导航、侧栏、移动端抽屉）；
- `case-builder/components/authoring.module.css`（建题会话双栏、资料行、composer）；
- `evaluation-sets/components/rubric.module.css`；
- `human-scoring/components/humanScoring.module.css`。

标准与依据 sheet 中的键值分区使用 `globals.css` 的 `.kv-block` / `.kv-label` / `.kv-items`，只用留白和发丝线，不引入卡片阴影。

内联 style 仅用于小范围布局或动态值，并继续引用全局 token；可复用或响应式规则应进入 CSS / CSS Module。不要引入 Tailwind、CSS-in-JS 或组件库作为第二套样式系统，除非有独立任务和迁移计划。

## 开发预演

`src/lib/preview/preview.tsx` 和两个 `preview/fixtures.ts` 只服务开发验收，`PREVIEW_ENABLED` 在生产构建为 false。新增页面状态时可扩展预演，但 fixture 必须使用 OpenAPI 生成类型，开发辅助字段或 Stub 标记不得无条件出现在生产 UI。
