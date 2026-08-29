# M0 前端工作流

## Goal

把 M0 的上传、任务边界确认、场景/单题共创、下一版本和历史收敛为一个安静、可恢复的场景工作台，让业务老师始终只面对当前最高价值工作和一个主动作。

## Confirmed Facts

- canonical read model 是后端 `StudioProjection`，前端不推导 Worker、Agent 或 Checkpoint 状态。
- 稳定信息架构只有“当前 / 题 / 版本”；下一版与历史都属于“版本”。
- 现有一屏一节题稿审阅可复用；workspace 卡片墙、饱和蓝主按钮和生产 JSON 编辑器不延续。

## Requirements

### R1 — 路由与信息架构

- route family 只保留场景列表、`/workspaces/{id}` 工作台、聚焦题详情和只读版本详情。
- 上传、批次、分组和场景标准是“当前”中的渐进阶段，不拆成技术实体页面。
- 旧 cases 路由重定向到工作台或聚焦题详情，不保留第二套编辑器。

### R2 — 唯一下一步和后台恢复

- UI 只消费 `next_action` 和 active_operation；每个视图最多一个主按钮。
- 所有长操作支持 `202`、友好轮询、离开/刷新恢复、错误重试和答案已保存后的“重试整理”。
- 页面和 DTO 不出现 thread/checkpoint/interrupt/decision/Graph node/raw messages。

### R3 — 聚焦共创与审阅

- 主画布一次只显示一个问题、原因和回答入口；处理后显示“本轮更新”的新增/修改/删除/仍有疑问。
- 场景标准、判定依据、缺口和问答过程默认关闭；桌面用 sheet，窄屏用全屏 sheet。
- 问答阶段和逐节最终审阅分离；生产 DraftEditor 无 JSON 编辑器。

### R4 — 题、下一版本与历史

- 清楚区分继承自场景和本题补充，支持判定依据、可见性、待复核和最终定稿门。
- 版本页同时展示唯一下一版与冻结历史，覆盖不足与已冻结分开表达。
- 下载完整包时明确“给 Skill 的材料 / 评分依据 / 形成记录”及不可交给被测 Skill 的内容。

### R5 — 视觉与可访问性

- 660–720px 阅读主画布、文字型三导航、一个焦点面；普通分组依靠留白和发丝线。
- 中性深色主动作，蓝色只用于链接/焦点/当前态，语义色只表达状态。
- 不使用聊天气泡、机器人、渐变光晕、卡片墙、永久第三列或逐字输出。
- 桌面和窄屏完成键盘、焦点、aria-live、44px 命中和 reduced-motion。

## Out of Scope

- Dashboard、模型设置、成员/权限、实时 Agent console、M1/M2 空页面。
- 新状态库或新组件库，除非现有原语无法满足可访问性且有单独证据。

## Acceptance Criteria

- [ ] 桌面/窄屏静态 Preview 先通过设计审查，再接真实 API。
- [ ] 页面只有“当前 / 题 / 版本”、一个主动作和一个焦点面。
- [ ] 生成 DTO 驱动全部状态；fixtures 不手写第二份类型。
- [ ] 长文件名、多任务、后台中/失败、等待回答、答案已保存、重投影、待复核、冻结阻塞/中/成功和历史只读均有 Preview 状态。
- [ ] 生产页面无 JSON、内部 Checkpoint 词、默认 hash/机器码或 AI 装饰。
- [ ] desktop/narrow 键盘、焦点、sheet、aria-live 和 reduced-motion 验收通过。
- [ ] `cd frontend && pnpm typecheck` 与 `pnpm build` 通过。

## Dependencies and Ownership

- 依赖前三个后端子任务的稳定 OpenAPI；不在后端未冻结字段时并行手写 DTO。
- 独占：`frontend/src/app/(app)/workspaces/**`、workspaces/case-builder/evaluation-set 前端 Feature、Preview fixtures、相关 CSS/测试。
- 生成共享：`frontend/src/lib/api/generated.ts` 只由 `make openapi` 更新；共享 UI 原语仅在第二处真实复用时扩展。
- 不修改后端业务规则、版本包 builder 或 Agent adapter。
