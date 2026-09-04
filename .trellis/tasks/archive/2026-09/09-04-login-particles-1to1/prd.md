# 登录粒子背景 1:1 对齐参考图

## 背景

`09-04-login-rebrand` 曾以参考画作 `particle-login-bg.png`（1918x1064，存档于
`.trellis/tasks/archive/2026-09/09-04-login-rebrand/research/`）整页拉伸作为认证面背景，
视觉与参考图 1:1。随后 `09-04-login-particles` 按当时需求把静态 PNG 换成纯 Canvas
程序化重建（尘埃弧带 + 活粒子），但程序化重建结果与参考图明显不一致：整体过暗过细、
色调饱和度不足、环带形状与尺寸漂移。用户反馈当前粒子态与参考图"完全不一致"，要求
1:1 还原——包括光亮程度、环的形状与大小。

## Goal

认证面背景恢复为对参考画作的 1:1 呈现（色调、光亮程度、环带形状与尺寸与参考图完全
一致），同时保留 `09-04-login-particles` 确立的"活的星图"动态粒子体验。

## Requirements

1. 底图层 = 参考画作本身
   - 运行时资产 `frontend/public/particle-login-bg.png` 恢复为 `09-04-login-rebrand`
     提交 95b8977 中的**图像修补版**（md5 7b18672f005abc0889611c4ca77c6393）：即归档
     参考图经修补抹除烤入的 AURA 字标与登录面板后的纯粒子画作。不得直接使用带字标/
     面板的 raw 参考图（md5 09d30b9aad0cd95efe96ea82a605e181），否则出现双面板。
   - `ParticleBackdrop` 的静态底图层改为把该 PNG 按画布尺寸 `drawImage` 铺满
     （等价原 rebrand 的 `background-size: 100% 100%`），不再用程序化尘埃/光晕重建画作。
2. 动态粒子层保留
   - 沿弧带（控制点量自参考图）流动 + 闪烁的活粒子层继续存在，叠加在底图之上
     （`lighter` 合成）；强度需收敛到不改变参考图整体色调与亮度（必要时降低
     alpha/数量），以截图对比验证。
   - `prefers-reduced-motion` 静态单帧、页签隐藏暂停 RAF、DPR 上限 1.5、
     画布面积缩放粒子数等非功能行为不变。
3. 旧语义彻底删除（同任务内）
   - 删除程序化画作重建：`BANDS` 尘埃生成（dust 数组/尘埃 sprite）、`paintRibbonWash`、
     `paintCrestGlows`、`paintAmbient`、`widthProfile` 等仅服务于底图重建的代码。
   - 弧带数据仅保留活粒子所需的控制点与色标。
   - 注释与 spec 文档同步：不再声称"旧的静态 PNG 已删除/程序化重建"。
4. 行为不变：登录/注册业务逻辑、面板几何、字标、E2E 现有用例（画布存在且已绘制）不受影响。

## Acceptance Criteria

- [ ] AC1 1918x1064 视口下登录页截图与参考图并排对比：色调、光亮程度、四条环带
      （蓝/金/绿/白）的形状与大小与参考图一致；差异仅允许来自叠加的活粒子闪烁。
- [ ] AC2 1280x720 视口无横向溢出、面板不裁切（沿用既有面板几何）。
- [ ] AC3 活粒子动画可见（流动/闪烁），且 `prefers-reduced-motion` 下为静态单帧。
- [ ] AC4 仓库内程序化画作重建代码已删除；`git grep` 无 `paintRibbonWash`、
      `paintCrestGlows`、`paintAmbient` 残留；spec 文档与组件注释反映新分层。
- [ ] AC5 质量门全绿：`git diff --check`、`make test`、`make build`。

## Notes

- 画作来源链：raw 参考图（含烤入字标/面板，与用户 2026-09-04 提供文件同 md5
  09d30b9aad0cd95efe96ea82a605e181）→ rebrand 任务图像修补（四边逆距离双线性填充 + 羽化）
  → 运行时资产（md5 7b18672f005abc0889611c4ca77c6393，从提交 95b8977 恢复）。
- 回滚方式：Git 回退本任务提交即可；不保留兼容开关。
