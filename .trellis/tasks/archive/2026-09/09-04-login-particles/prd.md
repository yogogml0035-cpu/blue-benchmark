# 登录页移除未实现的记住我/忘记密码并改为动态粒子背景

## 背景

上一任务（09-04-login-rebrand）按原型 1:1 还原了登录页：`(auth)` 布局用静态原型 PNG
（`frontend/public/particle-login-bg.png`，1918x1064）整页拉伸做背景，登录表单含
「记住我」复选框与「忘记密码？」死链接。

用户反馈：

1. 「记住我」没有实现——`remember` state 从未传入 `login()`，是死控件。
2. 「忘记密码？」没有实现——代码注释明言"Local deployments have no password-recovery
   channel; the control exists for prototype parity"。所有账号密码由后台 CLI 生成，
   没有找回密码通道。
3. 左侧静态星图（三条粒子弧带：外层电蓝、中层金黄、内层青绿渐白，深海军蓝底）希望
   变成**动态粒子态**——实时渲染的粒子动画，替代静态 PNG。

## 需求

### R1 移除未实现的表单元素

- 删除登录表单的「记住我」复选框与「忘记密码？」链接及仅存它们的 `.options` 容器。
- 同步清理 `remember` state、`.options`/`.remember` 样式块、仅被它们引用的
  `--benchmark-auth-remember` 令牌。
- 登录接口调用与提交逻辑不变。

### R2 动态粒子背景

- 用 Canvas 实时粒子系统重建原型星图：深海军蓝底 + 三条嵌套粒子弧带
  （外蓝 #2DAFFF 系 / 中金 #FFC83D 系 / 内青绿→白），从左下向右上扫过，右侧 ~35%
  保留暗区给登录面板（`left: 62.5vw` 的 `.panelHero`）。
- 粒子动态：沿弧带缓慢流动 + 亮度闪烁（twinkle），整体氛围接近"活的星图"；
  不做剧烈运动，不得干扰表单可读性。
- 删除 `frontend/public/particle-login-bg.png`，`.surface` 改为令牌化底色 +
  Canvas 层。
- 登录与注册页面共用该背景（`(auth)` layout 级）。

### R3 非功能约束

- `prefers-reduced-motion: reduce`：渲染静态单帧，不跑动画循环。
- 页签不可见时暂停 RAF；DPR 上限 1.5；粒子数按画布面积缩放，1920x1080 下不掉帧
  明显（目标 ≤ 16k 粒子，批量绘制）。
- 组件色值属于背景美术层（非 UI 语义色），允许在组件内定义调色常量；UI 面板/表单
  依旧只用 `--benchmark-*` 令牌。
- 最低视口 1280x720：弧带几何按视口比例定位，无横向溢出；品牌字标、面板几何不变。

## 验收标准

1. `http://localhost:3000/login` 渲染页面无「记住我」「忘记密码？」字样；DOM 中无
   `input[name=remember]` 与 `.options` 容器。
2. 登录页背景为动态粒子弧带动画（肉眼看得到粒子流动/闪烁），构图与原 PNG 一致：
   左侧三条弧带（蓝/金/绿白）、右侧暗区、字标位置不变、登录面板几何不变。
3. 注册页共享同一动态背景。
4. `prefers-reduced-motion` 下页面为静态粒子帧（无动画），布局与色彩不变。
5. `git grep -n "particle-login-bg"` 无结果；PNG 文件已删除。
6. 质量门通过：`git diff --check`、`make test`、`make build`；E2E（若含登录用例）
   通过。

## 非目标

- 不实现真正的忘记密码/记住我功能。
- 不改动登录/注册的业务逻辑、API、面板几何与字标。
- 不引入 2D/3D 图形库（无 three.js/pixi 等），仅原生 Canvas 2D。
