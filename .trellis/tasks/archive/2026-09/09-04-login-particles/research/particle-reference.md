# 原型星图构图分析与动态粒子实现方案

## 参考构图（来自 frontend/public/particle-login-bg.png，1918x1064）

深海军蓝底（#061a32 附近，边缘更暗）。左侧约 0–60% 宽度被三条嵌套"弧带"占据，
从左下向右上扫，每条带由数万颗 0.5–2.5px 的尘埃粒子沿一条光滑曲线高斯散布而成：

- **外带（电蓝）**：最外、最粗（散布 σ 最大）。核心线大约经过
  (0, 78%) → (18%, 30%) → (33%, 9%) 顶点 → (40%, 12%) 回落 → (39%, 33%)，
  之后渐隐。颜色从深蓝 #1a5cff 过渡到亮青蓝 #2dafff，顶点最亮。
- **中带（金黄）**：与外带平行、向内收缩约 55%。核心线
  (0, 96%) → (14%, 55%) → (27%, 28%) 顶点 → (33%, 30%) 回落 → (33%, 52%)。
  颜色 #ff9d1c → #ffd964，顶点附近有强光晕。
- **内带（青绿→白）**：再向内一圈。核心线
  (2%, 100%) → (13%, 74%) → (24%, 47%) 顶点 → (29%, 49%) 回落 → (29%, 72%)。
  左段青绿 #12c996，向顶点过渡为白 #eef7ff，中下段最白最亮（视觉焦点）。
- 三条带共用同一形状家族：像一组同心的、顺时针旋转约 30° 的椭圆弧顶部。
- 右侧 62%–100% 宽度基本是空暗区（登录面板 `.panelHero` 位于 left 62.5vw）。
- 左上角白色宽字距字标「汽车事业 BenchMark 平台」压在暗区上。

## 实现方案（Canvas 2D，无第三方库）

### 结构

- 新组件 `frontend/src/features/auth/particle-backdrop.tsx`（"use client"），
  在 `(auth)/layout.tsx` 中作为 `<canvas>` 铺满 surface（position:absolute inset 0,
  z-index 0；brand/stage z-index 1/2 不变）。
- 弧带几何用**三次贝塞尔曲线族**建模：每条带有 4 个控制点（按画布百分比存储，
  带间通过向焦点缩放/平移嵌套），核心线 `bezier(t)`，法向偏移 `n(t)`。

### 静态层 + 动态层（性能关键）

一次性把 ~12k 颗"尘埃"粒子渲到离屏 canvas（按 DPR 缩放），构成密度底图；
每帧只重绘：

1. 底图整体以极慢速度沿切线平移（产生整体流动感）——用两次 drawImage 拼接
   或者直接静态（流动感交给动态粒子）。
2. ~2.5k 颗"活粒子"：每颗绑定弧带参数 t、法向偏移、相位；每帧 t += 流速，
   alpha = base + sin(phase + time·speed)·amp（twinkle）。用预渲染的
   16x16 径向渐变 sprite（每带 2-3 个色相变体）+ `globalCompositeOperation
   = "lighter"` drawImage 批量绘制。
3. 少量（~60 颗）大尺寸低透明光斑沿顶点漂移，营造光晕呼吸。

这样每帧 drawImage 次数 ≈ 2.6k，1080p 下 60fps 无压力。

### 形状与配色参数化

```ts
interface Band {
  stops: [x, y][];        // 百分比控制点（Catmull-Rom → bezier 平滑）
  sigma: number;          // 法向散布（占画布高度 %）
  density: number;        // 粒子数权重
  colors: { at: number; rgba: [r,g,b] }[]; // 沿 t 的渐变
  flow: number;           // 流速系数
}
```

粒子生成：t 按弧长近似均匀采样 + 端点淡出权重；法向偏移 gauss(0, σ(t))，
σ 在端点收窄、顶点最宽；亮度 = 顶点热区增强 × 随机。

### 帧循环与可访问性

- `prefers-reduced-motion: reduce` → 只渲染一帧（活粒子取随机初相定格），不启动 RAF。
- `visibilitychange` → 暂停/恢复 RAF。
- resize（防抖）→ 重算几何重渲底图；DPR 上限 1.5。
- 画布是纯装饰：`aria-hidden="true"`，不进可达性树。

### 清理

- 删 `frontend/public/particle-login-bg.png`。
- `.surface` 底色改用 `--benchmark-auth-page`（#061a32 即原画布底色），
  移除 background-image 相关声明与注释。
- globals.css 中仅被「记住我」引用的 `--benchmark-auth-remember` 一并删除。
- spec `components-and-style.md` 的「认证面」章节同步改写（PNG → 动态粒子层）。

## 风险

- 视觉还原度：贝塞尔族近似原型弧线，需截图对比迭代（顶点位置/带宽/亮度）。
- 帧率：若 60fps 不稳，先降活粒子数与 DPR，再降尘埃总数。
- E2E 截图断言若依赖原 PNG 视觉特征需复核（登录 E2E 以表单行为为主，预期无影响）。
