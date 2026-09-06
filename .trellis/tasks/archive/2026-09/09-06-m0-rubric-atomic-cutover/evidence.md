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

## 质量门与合并（最终 HEAD 5f1b465）

- `git diff --check`：0。
- `make test`：backend 162 passed（RUNTIME_PG_REQUIRED=1，0 skip）+ frontend tsc/vitest 75 passed，TEST_EXIT=0。
- `make build`：BUILD_EXIT=0。
- `make frontend-e2e`（生产构建，E2E_PORT=3121）：44 passed，E2E_EXIT=0。
- **API 真实验收（最终 HEAD）**：`ACCEPT_REAL_AI=PASS`，API_EXIT=0（/tmp/c3-head-accept-api.log，隔离库 skill_eval_c3_accept{,_ckpt}）。F 组：预算截断→重试→thread_state_incomplete 检查点恢复；M 组：真实生成 4 维度/201 事件；两组引用逐字核验、5 分任意整数保存、发布/重开；受理式删除 threads=1 清理后双库零残留、兄弟题完好。
- **Web 真实验收（最终 HEAD）**：`M0_WEB_ACCEPTANCE=PASS`，WEB_EXIT=0（/tmp/c3-head-accept-web.log，隔离库 skill_eval_c3_accept_web{,_ckpt}）。live_streaming_observed（“已连接”+ 生成中真实事件行两次采样）、criteria=4、events 回放、依据面板、任意整数、发布/重开、删除以 404 为准导航、residue_verified threads_left=0。
- 合同链：make openapi / contract-check / frontend-generate-api / frontend-check-api 全部一致。

## 提交与合并

- 分支提交：9ceb902（后端切换）、bfe021a（后端测试）、550a89e（前端切换）、3ea18f0（验收入口+文档+sequence 合同）、9eea638（第一轮审查修复）、26695cd（编辑路径引用校验）、e2a96b9（第二轮审查修复）、5f1b465（有界修订轮）。
- main 合并与复验：待填（合并后补记）。

## 对抗式审查（两轮，多智能体）

**第一轮**（后端语义/删除链 + 前端UX/跨层合同 双代理）：2 Critical + 6 Major，全部在提交 9eea638 / 26695cd 修复并加回归测试：
- C-1（后端 Critical）：图完成但业务未提交的补提交路径会 RUNTIME_NO_EVENTS 死循环 → adapter 对 complete 线程跳过流式、直接补读结构化结果；PG 回归测试锁定。
- C-2（后端 Critical）：superseded 提交路径发假 run_completed → commit_generation_result 三态化，被取代运行以 run_failed(superseded) 收尾；中途改材料竞态测试锁定。
- C1-前端（Critical）：删除清理失败后重试按钮是安慰剂（deleting 分支提前 return，failed 作业永不重排队）→ deleting+failed 时走 accept_delete 重排队；回归测试锁定。
- C2-前端（Critical）：web 验收 live-streaming 断言可被空态占位符满足 → 要求“已连接”+ 真实事件行（占位符无 testid）+ 生成中二次采样。
- M-1 运行指纹只存不校 → register_thread 同时比对 runtime_fingerprint；M-2 编辑路径引用不校验 → patch_criteria 对每条 citation 校验 locator/quote（422 CITATION_INVALID，测试锁定）；M-3 旧同步硬删除函数残留 → 删除，测试改走受理流；M-4 删除回执死分支 → 删除并改正注释；前端 M1 滚动跟随失效/M2 operation 切换状态残留 → stick 追踪 + key 重挂载 + reset effect。
- Minor 全数处理：空白引文拒绝、sink 冻结守卫、sequence 冲突重读游标重试、pre-check superseded 终态事件、schema 巡检唯一约束、迁移索引名对齐、aria-live 节流改 leading+trailing、elapsed 以首个持久事件校准、回放失败区分“已被取代/冻结”、手工维度不可取消勾选（删除即移除）、isOnlyTitleChanged 全字段深比较、RunEventView.kind 收紧为 Literal、保存/重生成后有界重载兜底。

**第二轮**（修复提交复核代理，逐项突变体分析）：无 Critical；2 Major 已修复（提交 e2a96b9）：
- MAJ-1：C-1 回归测试用 stub 镜像锁不死生产分支 → 新增直接驱动真实 DeepAgentRubricGenerator 的 PG 测试（空模型脚本 + 补读打桩；revert 生产修复即 RUNTIME_NO_EVENTS 变红）。
- MAJ-2：THREAD_RUNTIME_MISMATCH 后教师重试死胡同且文案误导 → 失配时清除不兼容线程的检查点与登记（持锁、无模型、检查点不可达则 retryable），同 revision 全新开跑；完整恢复循环 PG 测试锁定（crash→陈旧指纹→重试→清除→全新完成）。
- MIN-1：complete 状态下空结构化结果改 retryable=False（确定性失败不做无谓重试）。其余 8 项 Minor 复核结论为“成立/可接受”（含 superseded+deleting 事件被冻结守卫丢弃的语义分析、sequence 重试只跳号不重号、前端 reset/SSE 无竞态等），已记录不改。
- 第二轮还实证发现并修复 purge 路径 NameError（run_streams 未导入，被 WORKER_DEBUG_TRACEBACK 定位）——该调试开关（默认静默）保留在 worker 通用异常分支。

修复后全量：backend 161 passed（RUNTIME_PG_REQUIRED=1，0 skip）、frontend tsc/vitest 75、E2E 44、双真实验收在最终 HEAD 重跑（结果见下）。

**最终 HEAD 验证链中真实验收暴露的第三个缺口（已修复，提交 5f1b465）**：API 验收在真实模型上出现 `AI_CITATION_INVALID`（模型偶发产出非逐字引文），当时整轮尝试直接失败——设计规定的“同一 job 受限预算内修订”尚未实现。修复：确定性校验失败（引用/锚点覆盖/解释分一致性）触发**一次**同 thread 跟进修订轮（`run_streaming` 新增显式 `allow_followup`，业务恢复路径仍只走 None/Command），修订后重读重校验、无第二次修订；预算计数覆盖修订轮；`revision_requested` 为公开阶段事件；单元测试锁定“无效引用→一次修订→有效结果”与“max_revisions=0 立即失败”。修复后 backend 162 passed。

## 旧语义删除核查

- 定向检索 `ModelRubricGenerator`、两字段完成假设、`204` 删除语义、静态假进度/整题轮询、800 字截断、EvalData 布局、占位答案兜底：backend/app、backend/tests、backend/scripts、frontend/src、frontend/e2e、frontend/scripts、README、Makefile、.trellis/spec 无可执行残留；`criterion`/`pass_score` 字段名与删除状态轮询（新语义）为合法保留。
- `accept_skill_push_evaldata.py` 更名为 `accept_skill_push.py`，旧标识符零命中。
- 前端确认：无“正在生成…自动刷新”静态提示、无 204 即跳转、`selectedToPayload` 为完整六字段投影、无假流式/打字动画（两轮审查代理独立复核通过）。

## 边界声明

- 未触碰项目库 skill_eval / skill_eval_checkpoint（验收全部在 skill_eval_c3_accept* 隔离库）；旧演示数据切换归 C5。
- 未新增 M1 聊天/新稿/评分执行入口、跨题检索或 Store；interrupt 协议仅由 C2 隔离验证，生产 profile 无询问工具。
