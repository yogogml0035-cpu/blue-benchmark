# 前端组件与样式

适用于 `frontend/` 的 UI 组件、BenchMark 视觉令牌与样式约定。不引入 Tailwind、CSS-in-JS 或通用 UI 组件库；用 CSS Custom Properties + CSS Modules。

## 视觉令牌

- 全部语义色来自 `src/app/globals.css` 的 `--benchmark-*` 变量：基础（page/nav/surface/text/muted/action/focus/success/danger）、文件夹多色板、动作色上的前景 `on-action`、反馈色的半透明 `*-tint`/`*-line` 派生令牌，以及 `overlay`/`surface-translucent`。组件 CSS 只引用变量，禁止写裸色值。
- 深色工作台：页面背景 `--benchmark-page`，表面 `--benchmark-surface`/`-elevated`/`-overlay`，低对比描边 `--benchmark-line`。
- 正文 `letter-spacing: 0`；品牌字标（auth 面、侧栏）用 `letter-spacing` 表达宽字距。
- 内页标题收敛为操作界面尺度（约 15–18px），不照搬原型 62–72px 展示型字号；认证面是唯一例外，标题用原型展示尺度（`clamp(30px, 3vw, 43px)`）。

## 组件

- 共享控件在 `src/components/ui/`（Button、TextField、Dialog、StatusBadge、EmptyState、Skeleton、ErrorPanel），壳层在 `src/components/shell/`（AppShell）。页面优先复用，不另造一次性控件。
- 每个控件一个 `.module.css`，类名语义化；动效优先用轻量属性（`opacity`/`transform`/颜色/描边/阴影），必须可被 reduced-motion 覆盖，且不得因内容或状态变化引起布局跳动；新增任何会改变布局的动画前先在此登记理由。
- 异步按钮用 `loading` 态：显示 spinner、禁用、保持尺寸稳定，布局不因状态跳动。
- Dialog 负责焦点移入、Tab 循环、Escape 关闭与关闭后还原焦点。
- 表单错误优先用 `TextField error` 关联 `aria-describedby`/`aria-invalid` 并以 `role="alert"` 呈现；跨字段的业务失败用表单级 `ErrorPanel`（如登录页后端错误走表单状态行）。错误留在操作上下文，不只靠全局 toast。

## 布局与视口

- 桌面优先，最低 `1280px` 宽；`body`/壳层设置 `min-width: 1280px`。主视觉基线 `1440x900`，最低可操作 `1280x720`。
- AppShell 侧栏固定 232px，不折叠；底部固定管理员身份与退出。
- 内容可能超出视口高度时，用可滚动容器 + `margin:auto` 安全居中，避免 flex `justify-content:center` 在溢出时裁切顶部。

## 认证面

- 登录页使用 `(auth)` 布局：背景是 `ParticleBackdrop`（`src/features/auth/particle-backdrop.tsx`）的两层 Canvas——底图层把参考画作 `public/particle-login-bg.png`（rebrand 任务图像修补版：已抹除烤入的 AURA 字标与登录面板，对应提交 95b8977）按 `100% x 100%` 拉伸绘制（`Image.onload` 后重绘，加载前是 `#061a32` 底色），保证色调、亮度与四条环带（外→内：电蓝/金黄/青绿/白）的形状尺寸与原型 1:1；活粒子层以 ~2k 低 alpha 粒子沿弧带（Catmull-Rom 控制点量自画作）流动闪烁（sprite + `lighter` 合成），强度不得改变画作整体观感。`prefers-reduced-motion` 只渲染静态单帧；页签隐藏暂停 RAF；DPR 上限 1.5。背景组件是装饰性的（`aria-hidden`），UI 面板依旧只用 `--benchmark-auth-*` 令牌；不得退回纯程序化重建画作（2026-09-04 因与参考图不一致被用户否决），也不得换回带烤入字标/面板的 raw 参考图（双面板）。
- 登录面板由页面自身渲染（`auth-form.module.css` 的 `.panelHero`）：`top: 18.2vh / left: 62.5vw / width: 30.6vw / height: 65.5vh` 固定在背景右侧预留暗区；视口高度 ≤839px 时放宽为内容自适应并内部滚动，保证 1280x720 不裁切。
- 认证面的原型精确色板收敛在 `globals.css` 的 `--benchmark-auth-*` 令牌块（页面底色、面板渐变、输入框、渐变按钮、链接、状态色），与工作台令牌并存；组件 CSS 依旧禁止裸色值。
- 登录表单只有邮箱/密码字段；「记住我」「忘记密码？」没有后端能力（密码由后台 CLI 生效），不得凭原型还原重新引入死控件。E2E 用 `E2E_PORT` 可把整套 Playwright（webServer+baseURL）挪到其他端口，避免与手动预览的 3000 冲突。

## 可访问性与动效

- 所有交互具备键盘焦点与可访问名称；`:focus-visible` 用统一 `--benchmark-focus-ring`。
- 全局 `@media (prefers-reduced-motion: reduce)` 关闭动画；组件动效必须可被其覆盖。

## 禁止

- 裸色值/裸间距魔法数进入组件 CSS（用令牌与既有间距）。
- 装饰性图表（雷达图等）暗示尚不存在的评分结果。
- 默认组件库观感：浏览器默认灰按钮、白底输入框、浅色后台。
