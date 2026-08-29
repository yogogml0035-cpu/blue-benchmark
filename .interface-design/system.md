# 审校台 · Proofing Desk

Skill Eval Platform 前端的设计系统。改 UI 前先读这份，值已经定好了，照用不要重新推导。

实现位置：`frontend/src/app/globals.css`（token 与基础件）、`frontend/src/components/ui/`（跨 Feature 原件）、
各 Feature 目录下的 `*.module.css`（组合件）。

## 1. 方向与语气

**审校台**：业务老师把一份真实案例校订成一条可复核的候选用例。界面按「校样台」隐喻组织——
桌面（desk）上摊开纸张（paper），纸上每条主张都带一条来源墨线和一条边栏引注，最后落章签署。

- 使用者：PR/传播口的业务老师，不是开发者。刚做完一次真实交付，想把「什么算好」固定下来。
- 核心动词：**确认**。老师是权威，AI 是必须给出处的书记员。
- 语气：审校/校样，冷静、有据、可追溯。不是 dashboard，不是聊天。
- **只做浅色**。校样台就是被照亮的纸；半成品深色模式比没有更糟。`color-scheme: light`。

反面清单（这些是刻意避开的默认值，不要退回去）：

- Inter + `#3B82F6` + 灰卡片的通用 SaaS 面板；
- 侧边栏 + 顶栏的外壳（本闭环只有四条路由且流程是线性的，**状态机进程条就是导航**）；
- 把草案塞进一个 JSON `<textarea>`（JSON 只作折叠的逃生口）；
- 居中转圈的加载态（用撑住最终版面的骨架）。

## 2. 签名元素

改任何与草案/证据有关的界面都必须保留这两个：

1. **来源墨线** — 每条主张左侧 3px 竖线，颜色说明「是谁说的」：
   墨=输入事实、朱=老师判断、蓝=AI 候选、琥珀=未知缺口、中性=草案结构字段。
   颜色在这里承担证据链职责，**不是装饰**。实现见 `ClaimBlock.tsx` + `--claim-ink`。
2. **引注边栏** — 主张右侧 208px 等宽栏，`附件 lines 12-18` + `「短摘录」`。
   本应带出处而缺失时明确写「无引注」；结构字段不承载证据，边栏留白。

其余四处签名：**校次印**（第 N 校，楷体朱框）、**追问单**（琥珀单据，提问原因用楷体）、
**落章印**（旋转 -4° 的朱红方印）、**进程条**（收件→解析→起草→追问→校订→落章）。

## 3. 颜色

一个暖色相，只移动明度。60/30/10：纸占大部分，墨做结构，朱只出现在主操作、老师的笔迹和印章。

```
纸与桌   --desk #e9e2d4 · --desk-edge #ded5c4 · --paper #fbf8f2
        --paper-raised #fffdf9 · --paper-inset #f4efe3 · --paper-sunken #f0e9dc
墨四级   --ink #26211c · --ink-secondary #4d453c · --ink-muted #6b6254 · --ink-faint #7b7163
发丝线   --rule-soft 6% · --rule 11% · --rule-strong 19%（均为 rgb(38 33 28 / x)）
来源墨   --prov-fact #3a342c · --prov-teacher #a6362b · --prov-ai #3f5d7d
        --prov-gap #94661c · --prov-cleared #4c6b4e · --seal #9c2a22
```

规则：

- `--prov-teacher` 同时是全站主操作色——主操作永远是「老师行使判断」（登录、建卷宗、收件、提交回答、确认落章）。
- 输入框比周围**更暗**（`--paper-inset`），因为它接收内容。
- 顶栏与画布同色（`--desk`），只用一条发丝线分隔；不同色会把界面切成两个世界。
- **四级文字全部满足 WCAG AA**（对纸约 14 / 8.9 / 5.7 / 4.5:1）。新增文字色必须先算对比度再用。
- 维度类型（hard_gate / required_quality / diagnostic）**不用颜色区分**，用字重与描边
  （实心墨 / 描边 / 虚线描边）——否则会稀释来源墨线的语义。

## 4. 字体与层次

```
--font-ui    -apple-system, PingFang SC …        界面文字
--font-doc   Iowan Old Style, Palatino, Songti SC … 正文/标题/被撰写的内容
--font-mark  Kaiti SC, STKaiti …                 批注：提问原因、印章文字（克制使用）
--font-mono  SF Mono, ui-monospace …             引注、ID、时间戳、错误码、数字
```

字号 14px 基准、1.25 比例：`11 · 12 · (13) · 14 · 16 · 18 · 22 · 28 · 36`。13px 是比例外的一档，
只给按钮和校注这类界面文字。

层次靠 **size + weight + color 三根杠杆一起**，不靠单独放大：

- `.doc-title` 28/600/-0.015em 衬线 — 页面焦点（案例标题、卷宗架标题）
- `.doc-title-sm` 18/600 衬线 — 区块标题
- `.doc-body` / `.claimText` 16/1.65 衬线 — 被撰写的内容
- `.section-label` 11/600/0.09em 大写 muted — 分组标签
- `.mono` 12/tabular-nums — 机器可读的东西
- 所有动态数字加 `tabular-nums`

## 5. 密度、间距、圆角、深度

- 间距基准 4px：`--s-1..--s-14`。区块内 12–16px，纸内 20–24px，区块之间 32px。
- 纸的内边距：`.sheet-pad` 24px、`.sheet-pad-sm` / `.sheet-head` / `.sheet-foot` 16/20px。
- 圆角小：`--r-sm 3px`（输入框、按钮）、`--r-md 5px`（纸）、`--r-lg 8px`。**纸是方的**，不要大圆角。
- 页宽：`.page-narrow 468` 登录 · `.page-mid 880` 列表/收件 · `.page-wide 1120` 校样（需要正文+引注两栏）。
- **深度只有一种策略**：桌面/纸张的色阶差 + 发丝线。唯一的阴影是「纸离开桌面」的
  `--lift`（两层，极轻），弹层用 `--lift-pop`。按钮、卡片内部一律不加阴影。

## 6. 组件测量

| 组件 | 规格 |
|---|---|
| `.btn` | 34px 高 · 0 16px · 3px 圆角 · 13/550 · `:active` scale(0.975) · 140ms |
| `.btn-lg` | 40px 高 · 0 20px · 14px（表单主提交用这个） |
| `.btn-sm` | 28px 高 · 0 12px · 12px |
| `.btn-icon` | 28×28 视觉 + `::after inset:-6px` 扩到 40×40 命中区 |
| `.control` | 9px 12px · `--paper-inset` 底 · 3px 圆角 · 14px · focus 时 3px 朱色 12% 光环 |
| `.chip` | 2px 8px · `--r-sm` · 11/550（不要用胶囊圆角，纸是方的） |
| `.state` | 4px 10px · `--r-sm` · 12/600 + 6px 圆点，色调对应八个业务状态 |
| `.note` | 校注块：左边框 3px 语义色 + 12px 16px + 左侧圆形校注图标（`AlertMark` / `QueryMark` / `CheckMark` / `InfoMark`） |
| `.claim` | grid `1fr 208px` · gap 20px · 左边框 3px 来源色 · ≤900px 收成单栏，引注移到下方 |
| `.sheet` | `--paper` + 1px `--rule` + 5px 圆角 + `--lift` |
| `.folder` | 卷宗卡：上沿伸出 52×10px 牛皮纸标签 · hover 上移 1px 换 `--lift-pop` |
| `.sealRing` | 76×76 · 2.5px 朱框 · 旋转 -4° · 楷体 22px |
| `.track` | 进程条：11px 圆点（done 实心中性 / active 语义色环+脉冲 / pending 描边 / failed 实心朱 / skipped 短横） |

## 7. 动效

- 时长一律 < 300ms。按钮 110–140ms，入场 220ms。
- 只用 `cubic-bezier(0.23, 1, 0.32, 1)`（`--ease-out`）；不用 ease-in，不写 `transition: all`。
- 只动 `transform` / `opacity` / 颜色。
- `.enter` = opacity + translateY(4px)，用于状态切换后出现的纸。
- 骨架用 1.5s 横扫；`generating` / `parsing` 的圆点用 1.4s `pulse-dot`。
- `prefers-reduced-motion` 下全部退化为近零时长。

## 8. 状态是一等公民

每个页面必须覆盖 loading / empty / success / error / unauthorized。约定：

- 加载态用**撑住最终版面**的骨架（`Skeleton*`、`ProofSkeleton`、`PageFallback`），不用转圈。
- 空态要有设计：卷宗架为空时创建表单**升为这一屏的焦点**；有内容时它退回成可展开的动作。
- 报错/越权/不存在共用 `StatePanel`：一条色边 + 一个印章式标记（`fault` 用退件叉章，
  `locked` 用锁）+ 一句原因 + **等宽的机器码** + 唯一的下一步。
- 错误码永远以 `mono` 原样展示（`403 · FORBIDDEN`、`PARSED_CONTENT_EMPTY`、`retryable · false`），
  验收时可直接对照合同。
- 会话没读完之前不显示任何身份信息（`UserChip` 走读取态），更不显示猜的用户名。
- 状态预演：`?preview=` 把页面钉在某个状态上，仅开发构建渲染，数据只用 `generated.ts` 的类型构造。

## 9. 硬性约束

- 文本框凡承载不定长正文的，用 `AutoTextarea` 按内容增高，不用固定高度（会把长文截成半行）。
- 引注摘录用 `-webkit-line-clamp: 5` 截断并把全文放 `title`，不让一段长摘录撑高整行。
- 所有类型来自 `src/lib/api/generated.ts`，不写第二套 DTO；证据引用（`evidence_refs`）在
  界面上**只读**，人工不能伪造出处。
- 页面只调本 Feature 的 Service；Service 只调 `lib/api/client`。
- 新增控件先看 `src/components/ui/` 有没有；重复第二次就抽成组件，不要撒同一串内联样式。
