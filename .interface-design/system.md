# 评测集平台 · 设计系统

Skill Eval Platform 前端的设计系统。改 UI 前先读这份，值已经定好了，照用不要重新推导。

实现位置：`frontend/src/app/globals.css`（token 与基础件）、`frontend/src/components/ui/`（跨 Feature 原件）、
各 Feature 目录下的 `*.module.css`（组合件）。

> 2026-08-29 全面改版：废除旧「审校台 · Proofing Desk」纸墨方向（卷宗/校样/落章/印章/墨线/引注），
> 改为苹果极简。本文件是唯一事实源，旧方向的任何元素不得复活。

## 1. 方向与语气

**标准工作台**：业务老师把一次真实交付沉淀成一条白纸黑字的标准。核心叙事——
「我在把我们『什么算好』写成标准」；平台自述——「用你的评测集，验证 Skill 每次改版」。

- 使用者：PR/传播口的业务老师，不是开发者。刚做完一次真实交付，想把「什么算好」固定下来。
- 老师是**标准的作者**，不是档案管理员。界面每一屏都应让她觉得「我在写我们业务的标准」。
- 核心动词：**确认收录**。老师是权威，AI 是必须给出处的整理者。
- 语气：安静、清晰、可信。像系统设置页，不像聊天工具，更不是档案室。
- **只做浅色**。`color-scheme: light`。

反面清单（刻意避开，不要退回去）：

- 纸墨隐喻的任何残留：卷宗、校样、落章、印章、牛皮纸标签、楷体、墨线、引注边栏、案号、第 N 校；
- 通用 SaaS 仪表盘（侧边栏+顶栏外壳；本闭环只有四条路由且流程线性，**状态机进程条就是导航**）；
- 把草稿塞进一个 JSON `<textarea>`（JSON 只作折叠逃生口）；
- 居中转圈的加载态（用撑住最终版面的骨架）；
- 装饰性图标、胶囊圆角（999px）、处处显示的状态徽记。

## 2. 词表

界面用词与代码/API 词分两层：**API 契约词永远不动**，界面说人话。

| 界面词 | 代码/API（不动） | 状态 |
|---|---|---|
| 场景 | workspace | 替代「卷宗」 |
| 真实案例 | case / SourceCase | 替代「收件/案例」 |
| 材料 | attachment | 替代「原件」 |
| 标准草稿 | draft | 替代「起草/校样」 |
| 需要补充 | pending_question | 替代「追问单」 |
| 候选标准案例 | candidate_case | 替代「候选用例」 |
| 版本 v N | draft_revision | 替代「第 N 校」 |
| 案例编号 | case id | 替代「案号」 |
| 评测集（未来） | regression set | 替代「回归集」 |

生命周期：真实案例 →（AI 整理标准草稿 → 需要补充 → 审改）→ 候选标准案例 → 评测集。

八个状态的界面标签：parsing=解析中 · parse_failed=解析失败 · ready_for_ai=待整理 ·
generating=AI 整理中 · waiting_for_input=需要补充 · waiting_for_confirmation=待你确认 ·
ai_failed=整理失败 · confirmed=已收录。

关键动作：创建场景 · 上传并解析 · 提交回答并继续 · 确认收录为标准案例。

## 3. 颜色

中性灰骨架 + 唯一强调色。语义色只表达状态，不做装饰。

```
底色     --bg        #f5f5f7   页面
         --surface   #ffffff   卡片
         --surface-2 #f5f5f7   卡片内嵌区域/输入底
文字     --text      #1d1d1f
         --text-2    #6e6e73
         --text-3    #86868b
发丝线   --hair      rgba(0,0,0,0.10)
         --hair-soft rgba(0,0,0,0.06)
主操作   --accent    #0071e3
语义     --amber     #b25000   需要补充/证据缺口
         --red       #d70015   失败
         --green     #1d8a4b   已收录/成功
```

规则：

- 主操作（创建场景、上传、提交回答、确认收录）一律 `--accent`；页面上同时只有一个主按钮。
- 提示卡用语义色 8–10% 透明度做弱底色，文字用上表深档；全站禁用大面积饱和色块。
- 输入控件底色 `--surface-2`，比卡片暗一档。
- 顶栏与画布同色（`--bg`），只用一条发丝线分隔。
- 全部文字色对白底满足 WCAG AA；新增文字色先算对比度。
- 维度类型（hard_gate / required_quality / diagnostic）**不用颜色区分**，用字重与描边。

## 4. 字体与层次

```
--font-ui   -apple-system, BlinkMacSystemFont, "SF Pro Text", "PingFang SC",
             "Hiragino Sans GB", "Microsoft YaHei", sans-serif
--font-mono "SF Mono", ui-monospace, Menlo, Consolas, monospace
```

全站无衬线、无楷体。层次靠 **字重 + 字号 + 灰阶** 三根杠杆：

```
页面标题   28 / 650 / -0.02em     每屏一个（场景、案例标题）
区块标题   20 / 600
分组标题   13 / 600 / --text-2    来源分组用
正文       15 / 1.6 / 400
次要说明   13 / 400 / --text-2
mono       12 / tabular-nums      ID、编号、时间戳、错误码、数字
```

所有动态数字加 `tabular-nums`。

## 5. 密度、间距、圆角、深度

- 间距基准 8px：区块内 12–16px，卡片内 20–24px，区块之间 32px。
- 圆角（连续圆角矩形，**不是胶囊**）：卡片 16px · 按钮/输入 10px · 小徽标 6px。全站禁 999px。
- 页宽：`.page-narrow 480` 登录 · `.page-mid 880` 列表/上传 · `.page-wide 1080` 详情。
- 深度：默认靠发丝线 + 灰阶分层；卡片可用 `0 1px 2px rgba(0,0,0,0.04)` 极浅影；
  弹层 `--lift-pop`。按钮、卡片内部一律不加阴影。

## 6. 组件测量

| 组件 | 规格 |
|---|---|
| `.btn` | 34px 高 · 0 16px · 10px 圆角 · 14/550 · `:active` scale(0.98) · 120ms |
| `.btn-lg` | 40px 高 · 0 20px · 15px（表单主提交） |
| `.btn-sm` | 28px 高 · 0 12px · 12px |
| `.btn-icon` | 28×28 视觉 + `::after inset:-6px` 扩到 40×40 命中区 |
| `.control` | 10px 12px · `--surface-2` 底 · 10px 圆角 · 15px · focus 时 3px accent 35% 光环 |
| `.state` | 6px 圆点 + 12/500 文字 · 圆点色调对应八个状态（生成中脉冲） |
| `.note` | 提示块：语义色 8% 弱底 + 4px 圆角 + 左侧 6px 圆点，无裸标点无装饰图标 |
| `.sheet` | `--surface` + 1px `--hair` + 16px 圆角 + 极浅影 |
| `.track` | 进程条：8px 点 + 细线 + 12px 标签（done 实心灰 / active accent 环+脉冲 / pending 描边 / failed 红 / skipped 短横） |

进程条六步：**上传 → 解析 → AI 整理 → 需要补充 → 审改 → 收录**。

## 7. 来源分组系统（签名元素 ①）

标准草稿按来源分四个分组区，老师一眼看清「是谁说的」——这是老师行使确认权的信息基础，
全站含金量最高的设计，任何改版不得丢失语义：

```
■ 事实（输入里明确存在）
■ 你的判断（你已表达的）
■ AI 推断的候选标准
■ 证据缺口
```

- 分组标题纯文字（13/600/--text-2），**不用彩点不用墨线**——分组本身就是来源信号。
- 每个条目只有一句正文；行号、摘录、208px 引注边栏一律不要。
- 证据细节收进「查看原文」内联展开层（只读，显示 locator + quote）；`evidence_refs` 在界面上只读，人工不能伪造出处。
- AI 生成时不得把候选标准伪装成事实——四分组正是这条合同的前端执行。

## 8. 追问卡（签名元素 ②）

「需要补充」是 AI 和老师的唯一对话接口，任一时刻只允许一个待答问题。单行提示卡，琥珀弱强调：

```
┌────────────────────────────────────────────┐
│ ● 需要补充                                  │
│ 这份案例里，哪一个结果是你最终认可的？        │
│ 为什么问：缺少参考结果，无法形成可验证的通过条件 │
│                                            │
│ ┌────────────────────────────────────────┐ │
│ │ 你的回答…                                │ │
│ └────────────────────────────────────────┘ │
│                          [提交回答并继续]    │
└────────────────────────────────────────────┘
```

- 琥珀 8% 底 + `--amber` 文字点；提交期间输入和按钮一起禁用。
- 不做对话气泡、不做聊天流——这是标准沉淀平台，不是聊天工具。

## 9. 动效

- 时长一律 < 300ms。按钮 110–140ms，入场 220ms。
- 只用 `cubic-bezier(0.23, 1, 0.32, 1)`；不用 ease-in，不写 `transition: all`。
- 只动 `transform` / `opacity` / 颜色。
- `.enter` = opacity + translateY(4px)。
- 骨架用 1.5s 横扫；`generating` / `parsing` 的圆点用 1.4s 脉冲。
- `prefers-reduced-motion` 下全部退化为近零时长。

## 10. 状态是一等公民

每个页面必须覆盖 loading / empty / success / error / unauthorized：

- 加载态用**撑住最终版面**的骨架，不用转圈。
- 空态要有设计：场景列表为空时创建表单**升为这一屏的焦点**；有内容时退回成可展开的动作。
- 报错/越权/不存在共用安静的面板：一个语义色圆点 + 一句原因 + **等宽的机器码** + 唯一的下一步。
- 错误码永远以 `mono` 原样展示（`403 · FORBIDDEN`、`PARSED_CONTENT_EMPTY`、`retryable · false`），
  验收时直接对照合同。
- 会话没读完之前不显示任何身份信息（用户名纯文本 ≥14px，不用 chip 包裹）。
- 状态预演：`?preview=` 把页面钉在某个状态上，仅开发构建渲染，数据只用 `generated.ts` 类型构造。

## 11. 组件与文件重命名映射

| 旧 | 新 |
|---|---|
| `WorkspaceShelf.tsx` / `.module.css` | `ScenarioShelf.tsx` / `.module.css` |
| `CaseIntake.tsx` | `CaseUpload.tsx` |
| `CaseFile.tsx` | `CaseDetail.tsx` |
| `QuerySlip.tsx` | `QuestionCard.tsx` |
| `SealBlock.tsx` | `ConfirmedCard.tsx` |
| `ClaimBlock.tsx` | `SourceGroup.tsx`（重写为四分组） |
| `caseBuilder.module.css` | `caseDetail.module.css` |
| `DraftEditor` / `DraftView` / `AttachmentStrip` / `ProgressTrack` | 文件名保留 |
| feature 目录 `case-builder` | 保留（与后端 `case_builder`、API 路径 `/cases/` 对齐） |

页面标题：`/workspaces` = 场景 · `/cases/new` = 上传真实案例 · 案例详情页 = 案例标题 + 状态徽章。

## 12. 硬性约束

- 承载不定长正文的文本框一律 `AutoTextarea` 按内容增高。
- 所有类型来自 `src/lib/api/generated.ts`，不写第二套 DTO。
- 页面只调本 Feature 的 Service；Service 只调 `lib/api/client`。
- 新增控件先看 `src/components/ui/` 有没有；重复第二次就抽成组件。
- 新增装饰性图标/徽记前先问是否必要——历史反馈四连：符号要少。
- **开发/验收辅助信息不得出现在面向业务老师的界面**：Stub 标记说明、`GET /api/...` 合同原文、
  `retryable` 原始值、完整 UUID 等，一律用 `PREVIEW_ENABLED` 门控，生产构建不渲染；
  同一语义用中文人话常显（如 `private` → 「私有」）。错误码（`403 · FORBIDDEN`、
  `PARSED_CONTENT_EMPTY`）是可上报的标识，保留 mono 原样展示。
- 全站验收：搜索 `卷宗|收件|校样|校订|落章|案号|审校台|原件|追问单` 必须为 0 结果。
