# 前端组件与样式

适用于 `frontend/` 的 UI 组件、AURA 视觉令牌与样式约定。不引入 Tailwind、CSS-in-JS 或通用 UI 组件库；用 CSS Custom Properties + CSS Modules。

## 视觉令牌

- 全部语义色来自 `src/app/globals.css` 的 `--aura-*` 变量（page/nav/surface/text/muted/action/focus/success/danger + 文件夹多色板）。组件 CSS 只引用变量，禁止写裸 hex。
- 深色工作台：页面背景 `--aura-page`，表面 `--aura-surface`/`-elevated`/`-overlay`，低对比描边 `--aura-line`。
- 正文 `letter-spacing: 0`；AURA 字标用独立字符 + `gap` 表达分隔，不用负字距。
- 内页标题收敛为操作界面尺度（约 15–18px），不照搬原型 62–72px 展示型字号。

## 组件

- 共享控件在 `src/components/ui/`（Button、TextField、Dialog、StatusBadge、EmptyState、Skeleton、ErrorPanel），壳层在 `src/components/shell/`（AppShell）。页面优先复用，不另造一次性控件。
- 每个控件一个 `.module.css`，类名语义化；动效只用轻量属性（`opacity`/`transform`/颜色/描边/阴影），禁止动画会引发布局位移的属性（width/height/top/left/margin），且必须可被 reduced-motion 覆盖。
- 异步按钮用 `loading` 态：显示 spinner、禁用、保持尺寸稳定，布局不因状态跳动。
- Dialog 负责焦点移入、Tab 循环、Escape 关闭与关闭后还原焦点。
- 表单错误优先用 `TextField error` 关联 `aria-describedby`/`aria-invalid` 并以 `role="alert"` 呈现（如注册"两次输入的密码不一致"挂在确认密码字段）；跨字段的业务失败用表单级 `ErrorPanel`。错误留在操作上下文，不只靠全局 toast。

## 布局与视口

- 桌面优先，最低 `1280px` 宽；`body`/壳层设置 `min-width: 1280px`。主视觉基线 `1440x900`，最低可操作 `1280x720`。
- AppShell 侧栏 232px，可折叠到 80px；底部固定管理员身份与退出。
- 内容可能超出视口高度时（如注册面板），用可滚动容器 + `margin:auto` 安全居中，避免 flex `justify-content:center` 在溢出时裁切顶部。

## 认证面

- 登录/注册共享 `(auth)` 布局：左侧 AURA 字标区 + 右侧半透明面板，背景为确定性粒子场景（`particle-field.tsx`）。
- 粒子画布固定种子、仅在 resize 重绘、不持续占用动画帧；`prefers-reduced-motion` 下保持静态。

## 可访问性与动效

- 所有交互具备键盘焦点与可访问名称；`:focus-visible` 用统一 `--aura-focus-ring`。
- 全局 `@media (prefers-reduced-motion: reduce)` 关闭动画；组件动效必须可被其覆盖。

## 禁止

- 裸色值/裸间距魔法数进入组件 CSS（用令牌与既有间距）。
- 装饰性图表（雷达图等）暗示尚不存在的评分结果。
- 默认组件库观感：浏览器默认灰按钮、白底输入框、浅色后台。
