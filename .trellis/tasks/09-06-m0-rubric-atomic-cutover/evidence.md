# C3 完成证据（完整评分项与业务链路一次性切换）

日期：2026-09-06。执行 worktree：/Users/hsikey/Company/skill-eval-platform-wt/m0-rubric-atomic-cutover（分支 codex/m0-rubric-atomic-cutover，基线 main@e68e9a1）。

## 交付范围（同一语义单元，无半迁移）

- **完整评分项合同**：`criterion + pass_score(0-10 任意整数) + score_anchors(稀疏锚点) + criterion_basis + pass_score_basis(explained_score)`；主张分类 teacher_explicit/ai_inferred，明确要求必带引用；引用 locator 限定本题材料快照词表、quote 逐字程序化校验。生成层强制“建议分有锚点、依据解释建议分”；编辑层无锚点白名单（任意整数可存、依据不被改写、人工维度显式空辅助内容）。
- **生产生成接入 C2 运行基础**：DeepAgentRubricGenerator（受限 Deep Agent、只读材料虚拟文件、结构化 response_format）；thread 按（题目，材料修订）稳定登记于 `question_run_threads`；材料/运行指纹绑定；技术重试从检查点续跑（inputs=None / Command），THREAD_INPUT_CONFLICT 拒绝重复初始输入；预算（模型/工具/时长）有界。旧 `ModelRubricGenerator` 单次调用路径与两字段 prompt 已删除。
- **完整公开消息与真实流式**：`question_run_events` 先持久化后外送；sequence 按 operation 跨 attempt 单调；`_CompletionGatedSink` 把图完成降级为 graph_completed，run_completed 仅在业务 CAS 保存后发出；同源 SSE 读库（不拥有任务），游标重连幂等回放；私有 reasoning/内部摘要调用（lc_internal_call/lc_source）与非 model 节点被过滤。
- **受理式完整删除**：DELETE 202 受理=原子冻结（deleting）+持久清理作业（question_cleanup/question_deletion 独立 kind/target）；全部写路径与事件回放冻结；清理先删全部登记 thread 的检查点（无模型依赖、DSN 缺失/不可达可重试不静默），零残留核验后同一业务事务删除题目+事件+thread 登记+生成历史；回执不被级联删除；失败可见可重试且不误投影为生成失败；provider 损坏不阻塞清理（惰性建模）。旧“204 即删除成功/前端立即跳转”路径已删除。
- **前端 UI/UX**：锚点编辑、依据折叠区（分类徽标+引用）、改分“原依据对应 X 分”核对提示（持久可检测、不静默改写）、重生成整套替换确认弹窗（取消零请求）、生成时间线（连接状态/真实阶段/流式文本/工具行/已用时间/reduced-motion/不抢滚动/读屏节流）、完成后完整过程回看、删除处理中/失败重试/仅 404 后导航。
- **真实验收入口重写**：accept_real_ai_rubric（两组真实样本+恢复+删除+双库零残留）、accept_skill_push（技能客户端+C1 批次+隔离 PG）、smoke_ai_provider（真实数据+合同校验）、real-acceptance.mjs（浏览器+live 增量断言+空闲端口+只清理自有进程）。EvalData ZIP 强依赖、800 字截断、占位答案、假 Bad case 兜底全部删除；验收入口对项目库 fail-closed。
- **文档/规格/生成文件**：README、5 个规格文档、openapi.json、generated.ts 同步；BUSINESS_SCHEMA_HEAD=0021。

## 质量门（本次证据）

- `git diff --check`：0。
- `make openapi` + `make contract-check` + `make frontend-check-api`：一致。
- 后端 `RUNTIME_PG_REQUIRED=1 uv run pytest`：154 passed / 0 skipped（含 PG 崩溃恢复+跨库删除业务集成、删除冻结、事件/SSE、任意整数编辑合同）。
- 前端：tsc 0 错、vitest 75 passed、Playwright E2E 41 passed（生产构建，E2E_PORT=3117/3118）。
- `make build`：EXIT=0。
- **真实 AI API 验收**：`ACCEPT_REAL_AI=PASS`（/tmp/c3-accept-real5.log，隔离库 skill_eval_c3_accept{,_ckpt}）。两组 C1 真实 case 均产出 4 维度、149/175 条事件；F 组经历预算截断→重试→`thread_state_incomplete` 检查点恢复（不重复初始输入）；M 组经历 1 次真实自动重试后恢复成功；引用逐字核验通过；5 分任意整数保存且依据未被改写；发布/重开；受理式删除后双库零残留、兄弟题完好。
- **真实浏览器 Web 验收**：`M0_WEB_ACCEPTANCE=PASS`（/tmp/c3-accept-web.log，隔离库 skill_eval_c3_accept_web{,_ckpt}）。关键阶段：live_streaming_observed（生成完成前浏览器已收到真实增量，经实际 Next rewrite 链路）、real_generation_done criteria=4、events_replayed=173、basis_panel_opened、published、reopened、deleted_and_navigated（404 为准）、residue_verified threads_left=0。

## 旧语义删除核查

- 定向检索 `ModelRubricGenerator`、两字段完成假设、`204` 删除语义、静态假进度/整题轮询、800 字截断、EvalData 布局、占位答案兜底：backend/app、backend/tests、backend/scripts、frontend/src、frontend/e2e、frontend/scripts、README、Makefile、.trellis/spec 无可执行残留；`criterion`/`pass_score` 字段名与删除状态轮询（新语义）为合法保留。
- `accept_skill_push_evaldata.py` 更名为 `accept_skill_push.py`，旧标识符零命中。

## 对抗式审查

- 双审查代理（后端语义/删除链 + 前端UX/跨层合同）结论与修复：待补记。

## 提交与合并

- 分支提交：9ceb902（后端切换）、bfe021a（后端测试）、550a89e（前端切换）、3ea18f0（验收入口+文档+sequence 合同修正）。
- main 合并与复验：待填。

## 边界声明

- 未触碰项目库 skill_eval / skill_eval_checkpoint（验收全部在 skill_eval_c3_accept* 隔离库）；旧演示数据切换归 C5。
- 未新增 M1 聊天/新稿/评分执行入口、跨题检索或 Store；interrupt 协议仅由 C2 隔离验证，生产 profile 无询问工具。
