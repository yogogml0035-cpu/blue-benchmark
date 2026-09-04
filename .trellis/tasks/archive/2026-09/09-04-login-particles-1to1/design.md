# Design — 登录粒子背景 1:1 对齐参考图

## 一次性切换边界

本任务把"程序化重建画作"整体替换为"参考画作底图 + 活粒子叠加"，不存在双轨：

- 删除的旧实现（`frontend/src/features/auth/particle-backdrop.tsx` 内）：
  - `BANDS[].dust` / `BANDS[].live` 中的尘埃计数与尘埃生成逻辑（`buildBands` 的 dust 部分、
    `dustSprites`、尘埃绘制循环）；
  - `paintCrestGlows` / `paintRibbonWash` / `paintAmbient` / `widthProfile` / `endWindow` 中
    仅服务于尘埃层的部分（`endWindow` 仍被活粒子使用，保留）；
  - `REFERENCE_AREA` 面积缩放（底图随画布拉伸，尘埃数量缩放失去意义；活粒子按画布面积
    以简单系数缩放）。
- 新实现：
  - 运行时资产 `frontend/public/particle-login-bg.png`：rebrand 提交 95b8977 的图像修补版
    画作（已抹除烤入的 AURA 字标与登录面板；raw 参考图带字标/面板，直接用会双面板）；
  - `paintBase` 退化为：海军蓝底色填充 + `drawImage(artwork, 0, 0, width, height)`；
  - artwork 用 `new Image()` 加载，`decode()` 成功后触发一次底图重绘（加载前画布为底色，
    避免闪烁）；
  - 活粒子（ribbon + sprite + `lighter`）保持既有架构，`BANDS` 仅保留控制点、色标与
    活粒子参数；初始把活粒子 alpha 乘 0.7、数量乘 0.8，防止叠加后整体亮度超过参考图，
    以截图对比最终定参。

## 数据与接口

- 无后端/接口/DTO 变化；纯前端装饰层。E2E 断言（画布存在、`aria-hidden`、已绘制非空）
  继续成立。

## 回滚方式

- Git 回退本任务提交（资产 + 组件 + spec 文档一个变更集）；无数据库、无配置、无开关。

## 性能

- 底图每帧为一次 `drawImage`（离屏 base canvas 每 resize 重绘一次，主循环仅回放位图），
  相比删除前 ~24k 粒子重绘显著更省；活粒子 ~2.3k（×0.8）维持现状。
