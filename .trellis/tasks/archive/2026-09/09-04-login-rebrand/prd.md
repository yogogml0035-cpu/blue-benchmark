# 登录页 1:1 视觉还原与 BenchMark 品牌更名

## Goal

按用户提供的 particle-login 原型 HTML（`research/particle-login.html`，其"静态画作模式"以 `particle-login-bg.png` 为视觉真源）1:1 还原前端登录界面；并将全项目 AURA 品牌替换为「汽车事业 BenchMark 平台」。除认证面外，其余界面保持现有工作台风格与交互不变。

## Requirements

1. 品牌更名
   - 所有用户可见 AURA 文案（根布局标题、auth 字标、侧栏字标与 aria-label）改为「汽车事业 BenchMark 平台」。
   - CSS 令牌前缀 `--aura-*` 全量改名 `--benchmark-*`，不留旧别名、不做兼容层。
   - 源码注释中的 AURA 语义一并清除。
2. 登录页 1:1 还原（原型静态画作模式）
   - 背景为 `frontend/public/particle-login-bg.png`（`background-size: 100% 100%`），底色 `#061a32`。
   - 左上角固定字标「汽车事业 BenchMark 平台」（20px、宽字距）。
   - 登录面板固定于背景图右侧预留区：`top 18.2vh / left 62.5vw / width 30.6vw / height 65.5vh / min-height 560px`，原型面板皮肤（描边、圆角、渐变、投影）。
   - 面板内容按原型：`欢迎回来` 大标题、`登录以继续` 副标题、邮箱/密码输入框（左图标 20px、右密码可见切换）、记住我 + 忘记密码、渐变登录按钮（`登 录`、字距 0.16em、hover 上浮+扫光）、按钮下状态消息行、注册引导行。
   - 视口高度 ≤839px（最低 1280x720）时面板放宽为内容自适应并内部滚动，不裁切。
3. 行为保持
   - 登录仍走 `identifier + password`（用户名或邮箱均可登录），会话刷新与 returnTo 安全校验不变。
   - 注册引导仅在后端 `registration_available` 时展示（沿用现有 bootstrap 逻辑）；忘记密码为原型 parity 的静默控件（本地部署无找回通道）。
   - 注册页共享新认证面（背景/字标/面板皮肤），表单逻辑不变。
4. 旧语义彻底删除
   - 删除 `particle-field.tsx` / `particle-field.module.css` / `particle-field.test.tsx` 与 e2e 画布断言，改为背景图断言。
   - 删除旧 `.switch`、旧 auth 布局样式；ErrorPanel 仅保留在注册表单（跨字段业务错误），登录错误用原型式状态行（role=alert）。

## Acceptance Criteria

- [ ] AC1 登录页 1440x900 截图与参考图一致：背景画作、字标、面板位置/皮肤、标题/副标题、输入框（图标+占位文案）、记住我/忘记密码、渐变按钮、注册行。
- [ ] AC2 1280x720 无横向溢出、无表单裁切（面板进入自适应分支）。
- [ ] AC3 全仓库（frontend/src、e2e、spec 文档）无 AURA 残留、无 `--aura-` 令牌残留；侧栏/auth 字标与页面标题均为「汽车事业 BenchMark 平台」。
- [ ] AC4 用户名与邮箱两种标识均可登录，错误凭证在状态行显示「用户名或密码错误」；注册流程（首启）不受影响。
- [ ] AC5 质量门全绿：`git diff --check`、`pnpm typecheck`、`pnpm test`、`pnpm check:api`、`make build`、Playwright e2e（chromium 全量 + minimum + webkit auth）。
- [ ] AC6 spec 文档（components-style）与任务 PRD 反映新认证面约定与令牌改名。

## Notes

- 原型原型文件与参考图已归档于 `research/`；运行时资产在 `frontend/public/particle-login-bg.png`。
- 「记住我」「忘记密码」为原型 parity 的视觉控件，不承载后端语义。
