# 实施记录 — 登录页 1:1 视觉还原与 BenchMark 品牌更名

## 变更清单

**认证面 1:1 还原**
- `frontend/public/particle-login-bg.png`：参考图经图像修补（四边逆距离双线性填充 + 羽化）抹除烤入的 AURA 字标与整个登录面板，仅保留粒子画作背景（参考图为整页截图，面板与字标都烤在图里，登录页靠实时面板精确覆盖，注册页则会露出——这是首轮 judge 发现的双面板根因）。
- `(auth)/layout.tsx|module.css`：重写为「背景画作 + 左上角固定字标 + 居中 stage」；删除旧三栏布局与 ParticleField 引用。
- `features/auth/particle-field.tsx|.module.css|.test.tsx`：删除（确定性画布方案整体退役，静态画作模式取代）。
- `features/auth/auth-form.module.css`：重写为原型面板皮肤（描边/圆角/渐变/投影、50px 输入框、图标槽、渐变按钮 + 扫光、状态行）；`.panelHero` 按原型固定几何（18.2vh/62.5vw/30.6vw/65.5vh），≤839px 高度自适应防裁切；表单 `space-between` 纵向分布对齐参考图；复选框 appearance:none 空心描边。
- `(auth)/login/page.tsx`：按原型 DOM 重写（欢迎回来 / 登录以继续 / 邮箱地址+信封图标 / 密码+锁+眼睛切换 / 记住我 / 忘记密码 / 登 录渐变按钮 / 状态消息行 / 注册引导行）；登录逻辑（identifier、session refresh、returnTo 校验、ADMIN_EXISTS 跳转）不变。
- `(auth)/register/page.tsx`：三个返回分支统一包进 `.panelFlow` 面板，表单逻辑不变。

**品牌更名（全量、无兼容层）**
- `--aura-*` → `--benchmark-*`（globals.css 及全部引用，0 残留）；globals.css 新增 `--benchmark-auth-*` 原型色板令牌块。
- 根布局标题、auth 字标、侧栏字标 → 「汽车事业 BenchMark 平台」；侧栏折叠显示首字 monogram「汽」，修复折叠态字标/退出按钮溢出截断（identity 纵向堆叠、brandRow 收紧）。
- 注释层 AURA 语义清除（button/text-field/dialog/app-shell/globals）。
- 测试同步：e2e fixture `aura-admin`→`benchmark-admin`、选择器（邮箱地址 / 登 录 / 欢迎回来 / 用户名或密码错误）、画布断言→背景图断言；session 单测 fixture 同步。

**文档**
- `.trellis/spec/frontend/components-style/*`：认证面新约定、令牌改名、字标规则更新。

## 验证证据

- `git diff --check` ✅；`pnpm typecheck` ✅；`pnpm test` 71/71 ✅；`pnpm check:api` ✅；`make build` ✅；`make test` ✅
- Playwright e2e：41/41（chromium 全量 + chromium-minimum 1280x720 + webkit auth）✅（修复后重跑）
- 视觉验收（judge 两轮）：第一轮 2/7 → 修复（PNG 修补、纵向分布、复选框、折叠侧栏）后 6/7 → 错误态截图时序修正（应在注册开放时拍摄）后 **7/7 pass**。截图目录 `/tmp/login-rebrand-shots/`。

## 已知边界

- 「记住我」「忘记密码？」为原型 parity 的视觉控件：本地单管理员部署无找回通道，忘记密码链路刻意不做后端。
- 注册引导行仅在后端 `registration_available` 时渲染；注册关闭时（已有管理员）该行隐藏，属预期。
- `pnpm build` 的 `/api` 代理目标在构建期固化（`BACKEND_URL`，缺省 8000）：手动构建后跑隔离后端截图/测试时必须带一致的 `BACKEND_URL` 重建。
