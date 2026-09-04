# Journal - hsikey (Part 1)

> AI development session journal
> Started: 2026-08-29

---



## Session 1: M0 持久化与上传基础合并收尾
<!-- trellis-session: v=2 fp=458f647920b03580 -->

**Date**: 2026-08-30
**Task**: M0 持久化与上传基础合并收尾
**Branch**: `main`

### Summary

完成 M0 持久化与上传基础的分支开发、质量检查、合并到 main、合并后复验和 Trellis 归档；PostgreSQL 17、OpenAPI、后端测试、前端 typecheck 与 build 均已验证。旧任务分支待完成最终状态核对后删除。

### Git Commits

| Hash | Message |
|------|---------|
| `efec7f0` | feat(persistence): 增加 M0 持久化与安全上传基础 |
| `a6fdd8b` | docs(trellis): 固化任务分支集成闭环与后端合同 |
| `e4545d4` | chore(api): 同步前端生成类型 |

### Status

[OK] **Completed**


## Session 2: M0 Deep Agent 与共创
<!-- trellis-session: v=2 fp=53a89ed1d74c4f64 -->

**Date**: 2026-08-30
**Task**: M0 Deep Agent 与共创
**Branch**: `main`

### Summary

完成受限 Deep Agents AI runtime、只读证据后端、任务分组、稳定共创会话、HITL 问答、Checkpoint 恢复与 continuity reset；通过 38 个后端测试、OpenAPI、schema migration 和 main 构建复验。

### Git Commits

| Hash | Message |
|------|---------|
| `440acdb` | feat(cocreation): implement M0 restricted agents and co-creation |

### Status

[OK] **Completed**


## Session 3: M0 共创与评测版本
<!-- trellis-session: v=2 fp=16f1a93a8a618989 -->

**Date**: 2026-08-30
**Task**: M0 共创与评测版本
**Branch**: `main`

### Summary

顺序完成 M0 Deep Agent 共创和评测版本两个子任务：受限只读 EvidenceBackend、ToolStrategy/HITL、稳定共创恢复、任务分组、合同/判定依据、WorkingSetDraft、合同影响复核、coverage、连续冻结 v1/v2、canonical 三视图包及 Manifest/下载。随后完成一轮对抗式审查，修正版本身份不一致、命令跨草稿复用、分页边界、EvidenceRef 回查、敏感 metadata、并发锁、批次投影原子性、orphan intent、Checkpoint reset 和历史包完整性校验。最终 46 个后端测试、make test、make build、make openapi、Alembic/schema readiness 通过。

### Git Commits

| Hash | Message |
|------|---------|
| `440acdb` | feat(cocreation): implement M0 restricted agents and co-creation |
| `e9819b8` | feat(evaluation): add immutable M0 version packages |
| `ed948bb` | fix(m0): harden co-creation and version package boundaries |

### Status

[OK] **Completed**


## Session 4: 完成 M0 集成与父任务对抗式审查
<!-- trellis-session: v=2 fp=3cb6b8f310c0287b -->

**Date**: 2026-08-30
**Task**: 完成 M0 集成与父任务对抗式审查
**Branch**: `main`

### Summary

完成 M0 合成与真实样本闭环、跨批次题池、合同传播与版本隔离修正；通过 53 个后端测试、前端类型检查、OpenAPI 漂移检查、生产构建、真实样本 runner 和真实浏览器验收。完成父任务最终对抗式审查并记录生产 Checkpointer 常驻接入、自动清理消费者、完整提案 UI 与 M2 执行等未验证边界。

### Git Commits

| Hash | Message |
|------|---------|
| `93a6214` | feat(integration): complete M0 acceptance workflow |
| `b5b2970` | chore(m0): record final adversarial review |

### Status

[OK] **Completed**


## Session 5: Trellis Bootstrap 归档收尾
<!-- trellis-session: v=2 fp=faa68a3c9c1ab39a -->

**Date**: 2026-08-30
**Task**: Trellis Bootstrap 归档收尾
**Branch**: `main`

### Summary

完成 00-bootstrap-guidelines 的当前 main 复验与 Trellis 归档；源代码规范已完成回填，归档任务保留初始基线和验收历史。

### Main Changes

- 将 00-bootstrap-guidelines 归档到 .trellis/tasks/archive/2026-08/，状态更新为 completed

### Git Commits

| Hash | Message |
|------|---------|
| `603fe08` | docs(trellis): 添加Treillis开发流程指南和多代理协作技能说明 |

### Testing

- [OK] make test：53 passed，OpenAPI 合同检查通过，前端 typecheck 通过
- [OK] make build：Next.js 生产构建通过

### Status

[OK] **Completed**

### Next Steps

- 后续规范变更由各自功能任务通过 trellis-update-spec 持续维护


## Session 6: 生产 AI Worker 真实 Provider 接线
<!-- trellis-session: v=2 fp=30bf5efb34bd6f10 -->

**Date**: 2026-08-30
**Task**: 生产 AI Worker 真实 Provider 接线
**Branch**: `main`

### Summary

按 AI_PROVIDER 选择 OpenAI 兼容或 Anthropic，接入真实模型客户端、同步加密 PostgreSQL Checkpointer 与 production Worker；补齐 .env.example、ai-smoke、测试和后端规范。完成四轮对抗审查，并在 PostgreSQL 17 临时实例中验证 setup、跨进程恢复和 claim 前 schema fail-fast。真实 Provider smoke 因没有用户凭证保留待执行。

### Git Commits

| Hash | Message |
|------|---------|
| `8021638` | feat(runtime): wire production AI worker adapters |

### Status

[OK] **Completed**


## Session 7: 真实 Provider smoke 对抗加固
<!-- trellis-session: v=2 fp=3cce661ccfe681d0 -->

**Date**: 2026-08-31
**Task**: 真实 Provider smoke 对抗加固
**Branch**: `main`

### Summary

真实 make ai-smoke 首次暴露 Deep Agents 0.7.11 将 memory=[] 误解释为启用 MemoryMiddleware 的 NotImplementedError；改为 skills/memory=None，补充 model id、启动异常、spec 与回归测试。修正后真实 OpenAI 兼容模型 gpt-5.6-luna smoke PASS；main 复验 make test、make build 通过。

### Git Commits

| Hash | Message |
|------|---------|
| `c11285d` | fix(runtime): harden real provider smoke path |

### Status

[OK] **Completed**


## Session 8: 修复 Worker runpy 启动警告
<!-- trellis-session: v=2 fp=dd1cb1134c904a11 -->

**Date**: 2026-08-31
**Task**: 修复 Worker runpy 启动警告
**Branch**: `main`

### Summary

将 app.lib.operations 的 Worker 符号改为惰性重导出，移除 python -m app.lib.operations.worker 的 runpy RuntimeWarning；保留包级兼容导出并新增真实子进程回归测试。main 合并后后端 81 tests、make test、make build 和模块帮助启动均通过。

### Git Commits

| Hash | Message |
|------|---------|
| `f5d5904` | fix(worker): avoid runpy startup warning |

### Status

[OK] **Completed**


## Session 9: M0 真实 AI E2E 验证与跨层加固
<!-- trellis-session: v=2 fp=7353fcd45159ec17 -->

**Date**: 2026-08-31
**Task**: M0 真实 AI E2E 验证与跨层加固
**Branch**: `main`

### Summary

用 /Users/hsikey/BenchMark/EvalData 三份资料在临时 PostgreSQL 17 与独立加密 Checkpointer 上重跑真实 Provider/Worker E2E；修复 evidence scope/group-local 引用、completion fallback、operation kind/attempt CAS、终态 draft command、前端轮询与上传幂等边界。真实包、浏览器桌面/窄屏/旧路由/私有隔离与对抗审查记录已归档；make test 105、make build、ai-smoke、OpenAPI 和 diff check 通过。保留原生 5432 数据库未启动与默认 12 轮真实跑量未验证边界。

### Git Commits

| Hash | Message |
|------|---------|
| `347df56` | test: validate and harden real M0 AI E2E |

### Status

[OK] **Completed**


## Session 10: M0 真实 AI E2E 重跑与对抗加固
<!-- trellis-session: v=2 fp=5acac76663dbbacd -->

**Date**: 2026-08-31
**Task**: M0 真实 AI E2E 重跑与对抗加固
**Branch**: `main`

### Summary

按归档 M0 需求使用 EvalData 三份真实文件重跑 Provider/Worker/PostgreSQL/API/版本包和浏览器链路；修复分组顺序、projection/lease/合同/证据/前端迟到状态与 Fake Worker 验收冒充边界，完成两轮对抗回归并在 main 复验。

### Git Commits

| Hash | Message |
|------|---------|
| `6eadc16` | fix: harden M0 real AI E2E boundaries |
| `a631041` | docs: record M0 main E2E rerun evidence |

### Status

[OK] **Completed**


## Session 11: 修复零候选任务分组死循环
<!-- trellis-session: v=2 fp=545f2b676f593f1a -->

**Date**: 2026-08-31
**Task**: 修复零候选任务分组死循环
**Branch**: `main`

### Summary

定位到整理完成但 task_packages 为空时，前端把可恢复的分组状态渲染成无操作空页。修复题页在有可用资料时支持手动新增、分配和确认；分析中/失败、全部资料忽略、资料用途未确认分别提供等待、重试或上传入口。完成真实隔离浏览器回归、对抗式审查、111 个后端测试、前端 typecheck/build、OpenAPI 合同检查，并合并到 main。

### Git Commits

| Hash | Message |
|------|---------|
| `e09d6ac` | fix: keep empty task grouping recoverable |

### Status

[OK] **Completed**


## Session 12: 修复共创阶段连续性与 Worker 模式隔离
<!-- trellis-session: v=2 fp=78538d093988427d -->

**Date**: 2026-08-31
**Task**: 修复共创阶段连续性与 Worker 模式隔离
**Branch**: `main`

### Summary

核实 /goal 当前问题由 Fake Worker 混入真实队列与题级共创未继承场景合同共同造成；补齐合同传递、共享 hard gate 防弱化、Worker 数据库互斥锁和 Fake PostgreSQL 隔离，完成对抗式审查并在 main 复验。旧 Fake 会话不静默改写，真实 Provider E2E 仍需单独验收。

### Git Commits

| Hash | Message |
|------|---------|
| `60e9119` | fix: preserve co-creation continuity and worker mode |

### Status

[OK] **Completed**


## Session 13: 完成对话式建题与题级恢复
<!-- trellis-session: v=2 fp=f7ac7ccde26daf2e -->

**Date**: 2026-09-01
**Task**: 完成对话式建题与题级恢复
**Branch**: `main`

### Summary

完成第一阶段对话式建题会话：接入题级独立 question_cocreator 与安全 HITL、服务端快照/SSE、投影无模型恢复、幂等并发与证据边界；重构 transcript/composer/题目审阅 UI，使用 EvalData 真实 AI E2E 在 strict msgpack PostgreSQL 生产栈通过，并完成多轮对抗修正后合并 main、归档和删支。

### Git Commits

| Hash | Message |
|------|---------|
| `01b9121` | feat: 实现对话式建题会话与题级恢复 |
| `c9c2ce9` | docs: 记录建题会话验收合同 |

### Status

[OK] **Completed**


## Session 14: 完成评分规则共创与题目发布
<!-- trellis-session: v=2 fp=4966eb94c426f83e -->

**Date**: 2026-09-01
**Task**: 完成评分规则共创与题目发布
**Branch**: `main`

### Summary

完成 100 分制 rubric 共创、标准答案双层门、不可变题目修订、Working Set authored/mixed v2 包桥接和前端规则审阅 UI。补齐 projection_pending 无模型重投影、真实 Provider 输出修复、服务端轮询、空态 200、favicon/标签可访问性。main 上 make test 155 passed、build、迁移/schema、OpenAPI、ai-smoke 和 EvalData 真实浏览器 E2E 1 passed；Worker 运行标记为 production。

### Git Commits

| Hash | Message |
|------|---------|
| `29c0c15` | feat: publish rubric and authored question revisions |
| `43457e8` | test: cover conservative rubric review path |
| `c025aab` | fix: bind rubric anchor labels to inputs |

### Status

[OK] **Completed**


## Session 15: 完成待评答卷与人工评分
<!-- trellis-session: v=2 fp=67ff3dee151fd190 -->

**Date**: 2026-09-01
**Task**: 完成待评答卷与人工评分
**Branch**: `main`

### Summary

完成独立答卷粘贴/单文件上传、发布题目修订绑定、服务端确定性评分、parent-linked 不可变重评历史与双区评分 UI；补齐 OpenAPI、Preview、真实 EvalData AI/Worker/浏览器 E2E、迁移和对抗式权限/幂等/存储完整性测试。

### Git Commits

| Hash | Message |
|------|---------|
| `e1439b5` | feat: add human submission scoring workflow |

### Status

[OK] **Completed**


## Session 16: 完成 Benchmark 外部收题 API 与真实验收
<!-- trellis-session: v=2 fp=8d47e6e5733ef59f -->

**Date**: 2026-09-02
**Task**: 完成 Benchmark 外部收题 API 与真实验收
**Branch**: `main`

### Summary

在 main 合并外部收题子任务：新增场景绑定连接码、hash-only token、严格文本 payload、幂等草稿写入与 Web-only 编辑；补齐空场景快照、连接管理 UI、精确草稿链接、OpenAPI、对抗测试和真实 HTTP/Provider/Worker/浏览器 E2E。迁移至 0017，质量门 183 passed。

### Git Commits

| Hash | Message |
|------|---------|
| `a23361e` | feat: add external authoring draft API |

### Status

[OK] **Completed**


## Session 17: 补充绝对草稿链接并完成 ai-eval-push 本地验收
<!-- trellis-session: v=2 fp=88cc2a47883b708b -->

**Date**: 2026-09-02
**Task**: 补充绝对草稿链接并完成 ai-eval-push 本地验收
**Branch**: `main`

### Summary

将外部草稿响应改为基于 FRONTEND_URL 的绝对可点击链接；独立 ai-eval-push 已完成 SKILL/AGENTS/stdlib 客户端、预览确认、Keychain/0600 凭证、验证与安全扫描、本地安装和真实 HTTP 重试 E2E。私有 GitHub 仓库已创建，但 push 因 github.com:443 网络不可达未完成。

### Git Commits

| Hash | Message |
|------|---------|
| `109e134` | fix: return absolute external draft URL |

### Status

[OK] **Completed**


## Session 18: 完成前端工作台重构与真实 AI 全链路验收
<!-- trellis-session: v=2 fp=58b12aab970f9a31 -->

**Date**: 2026-09-02
**Task**: 完成前端工作台重构与真实 AI 全链路验收
**Branch**: `main`

### Summary

在当前 main 完成前端交互/UI 硬化：预演不再读取真实 Session，工作台主流程先于 Agent 连接，主动作统一 --action，移动导航改为可访问链接并加入焦点循环，rubric 隐藏内部评分项 ID，删除旧前端 Case Builder/旧路由兼容入口；本地验收脚本直连 loopback 避免系统代理 502。使用 /Users/hsikey/BenchMark/EvalData 完成真实 Provider/生产 Worker smoke、真实 HTTP 生命周期 runner、真实浏览器 5 项全套 E2E；make test/build、任务校验和对抗审查通过。修复并验证 ai-eval-push 实际源码路径、全局 symlink、私有 GitHub main 与本地提交一致。

### Git Commits

| Hash | Message |
|------|---------|
| `2d1db72` | feat: harden frontend authoring workflow |
| `adebe52` | test: guard real authoring state polling |

### Status

[OK] **Completed**


## Session 19: 前端桌面化重构：全站宽度体系与建题会话双栏
<!-- trellis-session: v=2 fp=7d1060928c20356f -->

**Date**: 2026-09-02
**Task**: 前端桌面化重构：全站宽度体系与建题会话双栏
**Branch**: `main`

### Summary

定位竖屏观感根因（760px 居中页 + 300px 右栏塞长表单），重定全局宽度档 480/1040/1280/1440，新增 PageShell 统一 8 处重复壳层，建题会话改 460px 双栏并修复资料行一字一行与 composer 遮挡；修复坏 token --text-1/--t-17；工作台画布 720→1120、场景列表 1280 卡片网格、人工评分 entry 1040；sticky 侧栏加视口内滚动兜底。质量门：typecheck/build/make test/contract-check 全过，Playwright 3 passed（真实 AI 2 例按设计跳过），preview 13 项目检 0 横向溢出。

### Git Commits

| Hash | Message |
|------|---------|
| `f70aed0` | feat(frontend): 桌面化宽度体系与 PageShell 壳层 |
| `c98dda2` | feat(frontend): 建题会话页双栏工作面 |
| `3f58cf0` | docs(spec): 记录桌面化版面体系与 PageShell 壳层约定 |

### Status

[OK] **Completed**


## Session 20: 重建统一题库后端（六类材料+两字段评分）
<!-- trellis-session: v=2 fp=8eb38e17a396a898 -->

**Date**: 2026-09-03
**Task**: 重建统一题库后端（六类材料+两字段评分）
**Branch**: `main`

### Summary

子任务1：以六类材料当前题目模型与 criterion+pass_score 两字段评分替换后端领域合同；实现场景凭证批量收题（事务全成全败、命令幂等、凭证隔离）、评分维度自动生成（Worker 租约/重试、revision CAS、原子提交防覆盖）与破坏式迁移 0018；删除旧建题/共创/Working Set/版本包/人工评分全链；经两轮多智能体对抗审查修复并发、安全与状态机漏洞；52 测试 + 真实 AI 验收通过。

### Git Commits

| Hash | Message |
|------|---------|
| `75adc14` | feat(backend): 重建统一题库后端并删除旧建题评分链 |

### Status

[OK] **Completed**


## Session 21: 收敛为纯后端工程并新增管理员 CLI
<!-- trellis-session: v=2 fp=fa925a0e33e6fe22 -->

**Date**: 2026-09-03
**Task**: 收敛为纯后端工程并新增管理员 CLI
**Branch**: `main`

### Summary

子任务2：删除 frontend/ 与 Next.js/pnpm/Playwright 工件及前端规范，移除 Node 依赖；重写 Makefile 为后端命令族；新增 scripts/admin_cli.py（场景与凭证签发/轮换/撤销/状态，明文只显示一次）；修复对抗审查发现的 CLI 错误路径、空白场景名、超长凭证标签与 shell 注入面；README/.env.example/.gitignore/specs 同步为后端边界。

### Git Commits

| Hash | Message |
|------|---------|
| `b70f83d` | refactor(repo): 收敛为纯后端工程并新增管理员 CLI |

### Status

[OK] **Completed**


## Session 22: 新增 ai-eval-push 上传 Skill 与外部连接状态端点
<!-- trellis-session: v=2 fp=78f9bce75c903d83 -->

**Date**: 2026-09-03
**Task**: 新增 ai-eval-push 上传 Skill 与外部连接状态端点
**Branch**: `main`

### Summary

子任务3：新增 skills/ai-eval-push/（SKILL.md 工作流 + 标准库客户端 + API 合同 reference + 隔离测试）；后端新增外部连接状态端点；服务端补齐反馈单项长度上限；对抗审查加固客户端（跨主机重定向剥离凭证、连接响应白名单、scheme 校验、未知字段/命令长度/空白原因拒绝）；EvalData 真实 API 验收通过（多题识别→整批上传→真实 AI 生成→逐题回读）。

### Git Commits

| Hash | Message |
|------|---------|
| `5c5a3d4` | feat(skill): 新增 ai-eval-push 上传 Skill 与外部连接状态端点 |

### Status

[OK] **Completed**


## Session 23: Benchmark M0 后端接口与上传 Skill 重构（父任务完成）
<!-- trellis-session: v=2 fp=aebe82bb0282a65f -->

**Date**: 2026-09-03
**Task**: Benchmark M0 后端接口与上传 Skill 重构（父任务完成）
**Branch**: `main`

### Summary

父任务完成：三个子任务串行交付并全部合并回 main。子任务1 重建统一题库后端（六类材料当前题目模型、场景凭证原子批量收题、两字段评分维度自动生成、破坏式迁移 0018），删除旧建题/共创/Working Set/版本包/人工评分全链；子任务2 删除 Next.js 前端与 Node 依赖，收敛为纯后端工程并新增管理员 CLI；子任务3 新增 skills/ai-eval-push 上传 Skill 与外部连接状态端点。每个子任务经多轮多智能体对抗式审查（并发/安全/合同）并修复；测试走真实 AI 执行，EvalData 真实 API 验收通过。

### Git Commits

| Hash | Message |
|------|---------|
| `950ce36` | docs(task): 完成 Benchmark M0 后端接口与上传 Skill 重构最终验收 |

### Status

[OK] **Completed**


## Session 24: 场景优先题库导航与接口收紧（父任务 + 两子任务串行闭环）
<!-- trellis-session: v=2 fp=96a06321a33f12de -->

**Date**: 2026-09-03
**Task**: 场景优先题库导航与接口收紧（父任务 + 两子任务串行闭环）
**Branch**: `main`

### Summary

子任务1重写 M0 前端交接稿为场景列表→场景题目列表→题目详情（外部仓库提交 a7ff2c7），两轮对抗审查修正全部发现项；子任务2将 GET /api/questions 的 scene_id 改为必填（缺参422、场景不存在404），删除无场景全量查询分支，同步测试、OpenAPI、README、验收脚本与上传 Skill 口径，两轮对抗审查后合并回 main；真实 AI 验收在分支与 main 均 ACCEPT_REAL_AI=OK；独立审计 10/10 验收标准 PASS。

### Git Commits

| Hash | Message |
|------|---------|
| `f50037f` | feat(backend): 题目列表接口收紧为场景必填并删除无场景全量查询 |
| `64a2726` | docs(spec): 记录旧语义删除的全仓库同步检查 |

### Status

[OK] **Completed**

### Next Steps

- 父任务最终验收记录已写入，随后归档父任务。


## Session 25: 题目上传 Skill 文档中文化
<!-- trellis-session: v=2 fp=273874b0b5185ef6 -->

**Date**: 2026-09-03
**Task**: 题目上传 Skill 文档中文化
**Branch**: `main`

### Summary

将 skills/ai-eval-push 的 SKILL.md 与 references/api-contract.md 从英文翻译为中文，新增与老师交互使用中文的约定；机器标识符（字段名/错误码/脚本输出前缀/限制数值）逐字保留并经 token 对比核对零漂移；沉淀 Skill 文档编辑规则到 cross-layer-contracts 指南

### Git Commits

| Hash | Message |
|------|---------|
| `4ba7518` | docs(skill): 题目上传 Skill 文档中文化 |
| `f00e0a0` | docs(spec): 记录 Skill 文档编辑的机器标识符保留规则 |

### Status

[OK] **Completed**


## Session 26: 登录页 1:1 还原与 BenchMark 品牌更名
<!-- trellis-session: v=2 fp=6b3333fa86420e0f -->

**Date**: 2026-09-04
**Task**: 登录页 1:1 还原与 BenchMark 品牌更名
**Branch**: `main`

### Summary

按用户原型（静态粒子画作模式）1:1 还原登录页：修补背景 PNG 抹除烤入的 AURA 字标与旧面板，重写 (auth) 布局/登录页/注册页面板与表单样式；全项目 AURA 更名汽车事业 BenchMark 平台（--aura-*→--benchmark-* 令牌、字标、标题、注释、测试 fixture），删除 particle-field 画布旧方案；侧栏折叠态溢出截断一并修复。验证：typecheck/vitest 71/check:api/make build/make test、Playwright e2e 41/41、judge 视觉验收 7/7（两轮）。

### Git Commits

| Hash | Message |
|------|---------|
| `95b8977` | feat(auth): 登录页按原型 1:1 还原并更名汽车事业 BenchMark 平台 |
| `bb7d1d2` | chore(task): login-rebrand 任务记录（PRD/实施证据/上下文清单/参考原型归档） |

### Status

[OK] **Completed**


## Session 27: 登录页动态粒子背景与死控件清理
<!-- trellis-session: v=2 fp=dcd10aadc3b10800 -->

**Date**: 2026-09-04
**Task**: 登录页动态粒子背景与死控件清理
**Branch**: `main`

### Summary

删除未实现的记住我/忘记密码（含样式与令牌）；ParticleBackdrop Canvas 2D 实时重建原型星图（四条嵌套粒子弧带，确定性种子静态尘埃+活粒子流动闪烁，reduced-motion 静态帧，页签隐藏暂停）；删除静态 particle-login-bg.png；重写 E2E 背景断言并支持 E2E_PORT。工作区并行会话切换分支，经独立 worktree 隔离完成闭环；E2E 03/04 两个失败经 main 基线比对确认为存量问题。

### Git Commits

| Hash | Message |
|------|---------|
| `2c5af3e` | Merge branch 'main' into codex/login-particles |

### Status

[OK] **Completed**


## Session 28: ai-eval-push 凭证硬编码绑定机制
<!-- trellis-session: v=2 fp=1a4fd81f698af01f -->

**Date**: 2026-09-04
**Task**: ai-eval-push 凭证硬编码绑定机制
**Branch**: `main`

### Summary

需求访谈六轮收敛：凭证承载从环境变量改为脚本内硬编码占位符，绑定=直接替换。实施：脚本绑定槽+未绑定保护、SKILL.md 绑定流程、测试 seam 改写、验收 harness 临时副本绑定、前端签发提示词同步；沉淀仓库副本永不绑定的铁律到后端规范。make test 全绿后合入 main 并复验。

### Git Commits

| Hash | Message |
|------|---------|
| `ec5d62d` | feat(skill): ai-eval-push 凭证改为脚本内硬编码绑定，移除环境变量链路 |

### Status

[OK] **Completed**


## Session 29: 平台凭证 1:1 模型与明文可见
<!-- trellis-session: v=2 fp=7eeaf4a81603fdc7 -->

**Date**: 2026-09-04
**Task**: 平台凭证 1:1 模型与明文可见
**Branch**: `main`

### Summary

凭证与场景严格 1:1：创建/轮换合并为单一动作（create_or_replace_credential），删除多凭证签发旧语义与 /credentials/rotation 端点；数据库持久化明文（撤销/替换即清空），场景页掩码+小眼睛查看，迁移 0020 存量归一（保留最新、其余作废 model-migration），admin CLI 合并为 credentials replace；BUSINESS_SCHEMA_HEAD 同步。开发期间 main 前进，先集成回任务分支重跑全部门禁后 fast-forward 合入。后端 84、前端 70、make build 全绿。

### Git Commits

| Hash | Message |
|------|---------|
| `da1ddea` | feat(scenes): 凭证 1:1 模型与明文查看，合并创建/轮换为单一动作 |

### Status

[OK] **Completed**


## Session 30: 服务器部署方案定稿与部署文件落地
<!-- trellis-session: v=2 fp=f26707224855b758 -->

**Date**: 2026-09-04
**Task**: 服务器部署方案定稿与部署文件落地
**Branch**: `main`

### Summary

苏格拉底式访谈定稿部署需求（单用户全公开、裸 IP HTTP 过渡、本地构建→ACR→服务器拉取、2GiB 基线）；重写任务 prd 并产出 design/implement；实现前后端 Dockerfile（standalone/uv 多阶段）、deploy/ 五服务 compose 编排、nginx 登录限流、push-images.sh 发布脚本、backup.sh 每日 OSS 备份与四份初学者手册；本地完成跨架构镜像构建与全链路冒烟（迁移/健康检查/注册登录/Worker 快速失败）；ff 合并回 main 并复验全部质量门。

### Git Commits

| Hash | Message |
|------|---------|
| `b6f0c63` | chore(task): 08-30-server-deployment-planning 部署方案定稿（prd/design/implement） |
| `638979b` | feat(deploy): 单机 Docker Compose 生产部署编排与发布手册 |

### Status

[OK] **Completed**
