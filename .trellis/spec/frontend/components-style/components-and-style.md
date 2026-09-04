# 前端组件与样式

适用于 `frontend/` 的 UI 组件、BenchMark 视觉令牌与样式约定。不引入 Tailwind、CSS-in-JS 或通用 UI 组件库；用 CSS Custom Properties + CSS Modules。

## 视觉令牌

- 全部语义色来自 `src/app/globals.css` 的 `--benchmark-*` 变量：基础（page/nav/surface/text/muted/action/focus/success/danger）、文件夹多色板、动作色上的前景 `on-action`、反馈色的半透明 `*-tint`/`*-line` 派生令牌，以及 `overlay`/`surface-translucent`。组件 CSS 只引用变量，禁止写裸色值。
- 深色工作台：页面背景 `--benchmark-page`，表面 `--benchmark-surface`/`-elevated`/`-overlay`，低对比描边 `--benchmark-line`。
- 正文 `letter-spacing: 0`；品牌字标（auth 面、侧栏）用 `letter-spacing` 表达宽字距；侧栏折叠时以首字 monogram 代替整段字标。
- 内页标题收敛为操作界面尺度（约 15–18px），不照搬原型 62–72px 展示型字号；认证面是唯一例外，标题用原型展示尺度（`clamp(30px, 3vw, 43px)`）。

## 组件

- 共享控件在 `src/components/ui/`（Button、TextField、Dialog、StatusBadge、EmptyState、Skeleton、ErrorPanel），壳层在 `src/components/shell/`（AppShell）。页面优先复用，不另造一次性控件。
- 每个控件一个 `.module.css`，类名语义化；动效优先用轻量属性（`opacity`/`transform`/颜色/描边/阴影），必须可被 reduced-motion 覆盖，且不得因内容或状态变化引起布局跳动。唯一允许的布局过渡是侧栏折叠的 `width` 动画（有意、有界、可中断）；新增任何会改变布局的动画前先在此登记理由。
- 异步按钮用 `loading` 态：显示 spinner、禁用、保持尺寸稳定，布局不因状态跳动。
- Dialog 负责焦点移入、Tab 循环、Escape 关闭与关闭后还原焦点。
- 表单错误优先用 `TextField error` 关联 `aria-describedby`/`aria-invalid` 并以 `role="alert"` 呈现（如注册"两次输入的密码不一致"挂在确认密码字段）；跨字段的业务失败用表单级 `ErrorPanel`。错误留在操作上下文，不只靠全局 toast。

## 布局与视口

- 桌面优先，最低 `1280px` 宽；`body`/壳层设置 `min-width: 1280px`。主视觉基线 `1440x900`，最低可操作 `1280x720`。
- AppShell 侧栏 232px，可折叠到 80px；底部固定管理员身份与退出。
- 内容可能超出视口高度时（如注册面板），用可滚动容器 + `margin:auto` 安全居中，避免 flex `justify-content:center` 在溢出时裁切顶部。

## 认证面

- 登录/注册共享 `(auth)` 布局：背景为已确认的原型静态粒子图（`frontend/public/particle-login-bg.png`，`background-size: 100% 100%` 铺满），左上角固定「汽车事业 BenchMark 平台」字标。旧的确定性粒子画布（`particle-field.tsx`）已删除，不再维护。
- 登录面板由页面自身渲染（`auth-form.module.css` 的 `.panelHero`）：`top: 18.2vh / left: 62.5vw / width: 30.6vw / height: 65.5vh` 固定在背景图右侧预留区；视口高度 ≤839px 时放宽为内容自适应并内部滚动，保证 1280x720 不裁切。注册面板用 `.panelFlow`（465px、`margin: auto` 居中、超高时随页面滚动）。
- 认证面的原型精确色板收敛在 `globals.css` 的 `--benchmark-auth-*` 令牌块（页面底色、面板渐变、输入框、渐变按钮、链接、状态色），与工作台令牌并存；组件 CSS 依旧禁止裸色值。

## 可访问性与动效

- 所有交互具备键盘焦点与可访问名称；`:focus-visible` 用统一 `--benchmark-focus-ring`。
- 全局 `@media (prefers-reduced-motion: reduce)` 关闭动画；组件动效必须可被其覆盖。

## 禁止

- 裸色值/裸间距魔法数进入组件 CSS（用令牌与既有间距）。
- 装饰性图表（雷达图等）暗示尚不存在的评分结果。
- 默认组件库观感：浏览器默认灰按钮、白底输入框、浅色后台。
