# Implement — 登录粒子背景 1:1 对齐参考图

## 执行顺序

1. 恢复资产：`git show 95b8977:frontend/public/particle-login-bg.png >
   frontend/public/particle-login-bg.png`（rebrand 的图像修补版，md5 校验
   7b18672f005abc0889611c4ca77c6393；不得用归档 raw 参考图——带烤入字标/面板）。
2. 重写 `frontend/src/features/auth/particle-backdrop.tsx`：
   - artwork `Image` 加载 + `decode()` 后重绘底图；
   - `paintBase` = 底色 + `drawImage` 铺满；
   - 删除尘埃生成、`paintRibbonWash`、`paintCrestGlows`、`paintAmbient`、`widthProfile`、
     `REFERENCE_AREA` 及相关字段；活粒子 alpha ×0.7、数量 ×0.8 起步；
   - 组件头注释改为"参考画作底图 + 活粒子层"。
3. 更新 spec：`.trellis/spec/frontend/components-style/components-and-style.md` 认证面首条
   改为新分层描述（底图为参考画作 PNG + 活粒子叠加；删除"旧的静态 PNG 已删除"表述）。
4. 检索验证（定向，确认无旧路径残留）：
   `git grep -n "paintRibbonWash\|paintCrestGlows\|paintAmbient\|widthProfile\|REFERENCE_AREA"`
   应无结果；`git grep -n "particle-login-bg"` 仅命中资产引用与新文档。
5. 视觉验证（迭代直至 AC1）：
   - `cd frontend && pnpm install && pnpm build`；
   - `BACKEND_URL=http://127.0.0.1:8000 pnpm start --port 3100`（后台运行，结束清理）；
   - 用 frontend 自带 @playwright/test 的 chromium 截 `/login`（1918x1064 与 1280x720），
     与 raw 参考图
     `.trellis/tasks/archive/2026-09/09-04-login-rebrand/research/particle-login-bg.png`
     的粒子画作部分并排对比（参考图右侧面板区域在运行页由真实 React 面板覆盖）；
     确认活粒子可见且不改变整体色调（AC3）。
6. 质量门：`git diff --check`、`make test`、`make build`（worktree 内，`.env` 已复制）。
7. 提交：两个批次——
   - `chore(task): 09-04-login-particles-1to1 任务文档`（任务目录）；
   - `feat(auth): 登录粒子背景改为参考画作底图+活粒子层，1:1 对齐参考图`
     （资产、组件、spec 文档、e2e 若有注释调整）。

## 验证命令清单

```bash
git diff --check
make test
make build
git grep -n "paintRibbonWash\|paintCrestGlows\|paintAmbient\|widthProfile\|REFERENCE_AREA"
```

## 风险与对策

- 活粒子叠加导致亮区过曝 → 截图对比后继续下调 alpha/数量；下限为完全静态底图
  （届时按 AC1 只保留底图，PRD AC3 允许"可见流动/闪烁"失效需回改 PRD——不允许，
  必须保住动态层，宁可再降参数）。
- PNG 拉伸在非 1918x1064 视口有形变 → 与已验收的 rebrand 行为一致
  （`background-size: 100% 100%`），不新增处理。
