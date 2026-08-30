# M0 前端工作流设计

## Intent checkpoint

- Intent：经过培训的内部业务老师，从真实材料中形成可复用评测资产；界面像安静的编辑工作台，而不是 Agent 控制台。
- Hierarchy：当前唯一问题/审阅节是焦点，靠 700px 阅读宽度、标题权重和留白胜出；导航、状态和检查器退居次级。
- Palette：纸白、石墨、铅灰、发丝灰、墨水蓝和克制警示琥珀，来自稿件审阅与版本校样场景。
- Depth：以发丝线和极轻表面层级为主；sheet 才有轻阴影，不混用重卡片阴影。
- Surfaces：canvas、focus surface、overlay 三层，同一中性温度。
- Typography：中文系统无衬线，14–16px 阅读正文；权重和四级文字色承担层级，数字使用 tabular-nums。
- Spacing：4px 基础单位；控件 8/12/16，组间 24/32，主章节 48/64。

## Domain exploration

- Domain：资料包、任务边界、场景标准、批注、题稿、定稿、下一版、冻结历史。
- Signature：一条“问题 → 回答 → 本轮更新 → 唯一下一步”的纵向形成链，刷新后仍回到同一节点。
- Rejecting：Dashboard 卡片墙改为阅读画布；聊天窗口改为一问一变一确认；永久三栏改为按需 sheet。

## Layout

- 顶部场景标题和状态说明，下方只有当前/题/版本三项文字导航。
- 主区 660–720px 居中；窄屏 16px 页边距。
- 当前焦点面只有一个主按钮；辅助操作为文字链接或 sheet trigger。
- “标准与依据”桌面从右侧进入，窄屏占满视口并返回原焦点。

## State model

- Server snapshot：StudioProjection、题/版本资源和 active operation。
- Page transient：sheet、焦点、回答草稿和 `202` 前短 busy。
- Preview：仅开发门控，覆盖业务投影，不伪造 Agent 内部状态。
- 每次成功读取用服务端 snapshot 覆盖本地服务器状态；表单草稿单独保留。

## File ownership

- 独占：工作台/题/版本 route 与 Feature 组件、服务、Preview、CSS modules。
- 顺序共享：globals tokens、shell、Button/Field/StatePanel 等现有原语、生成 API 类型。
- `.interface-design/system.md` 由父任务先更新替换条款；本任务实施时遵守并在最终验收后沉淀实际源码事实。

## Responsive and accessibility

- 原生 button/link/textarea/details 优先；复杂 sheet 使用已有或成熟可访问原语。
- 所有状态有可读文本，不只靠颜色；处理完成和错误使用 aria-live。
- 关闭 sheet 后焦点返回 trigger；Escape、Tab、窄屏滚动和 reduced-motion 均机械验收。
