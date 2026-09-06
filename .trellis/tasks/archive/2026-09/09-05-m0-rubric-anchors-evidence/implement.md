# 父任务实施协调与分派索引

状态：planning。以下是获批后的执行顺序，不是本轮已执行清单。当前仅允许任务文档写入；真实模型试跑、安装依赖、产品修改、数据变更需最终规划获明确批准。

## 父任务职责与分派

- 父任务只维护共享要求、设计、分派和跨子任务总验收，不直接执行以下生产修改。实际顺序为 C1 -> C2 -> C3 -> C4 -> C5，依赖及文件所有权见 task-map.md。
- 下文原阶段号保留为总要求/检查项定位，不表示可以绕开子任务依赖。每个子任务都有独立 PRD/design/implement 和 context 清单；它们负责本子任务的具体执行与验收。
- 规划记录先在本工作区建立；后续获批后按质量门集成任务文档基线，再从最新已验证 main 创建各子任务工作区，不能共享当前父任务分支实施。
- 子任务以 main 上交付代码和可重建输入交接；私有证据按 task-map.md 保存到非 Git 持久目录，不能依赖已归档 worktree 或丢失唯一验收证据。

## 阶段 0：父任务收敛与子任务进入门禁

- 业务决定已收敛，包含日常删除时一并清理全部同题过程/上下文并保留原门禁。工程预算先以现有配置和样本体量设置有限上限，再在隔离验收中校准，不再把已回答的产品问题留在规划清单。
- 完成 PRD 收敛整理并给出 `review.md` 最终摘要，等待用户后续明确批准；不把 `task.py validate`、范围确认或本任务建档视为实施批准。
- 每个子任务开始前重读适用规格，核对全部 worktree、主工作区及 main/origin/main，并验证上游完成/归档记录和 main 提交；仅在该子任务的独立 worktree 实施。main 前进时先同步重验，不混入他人改动。
- 核对 `.env` 已复制且不进 Git，再显式隔离测试目标；批准后只在对应子任务 worktree 运行 `task.py start <child>`。父任务不 start 为业务实施任务，各子任务实际 branch/base_branch/worktree 在创建后登记。

## 阶段 1：完整合同与删除清单（C3；数据切换归 C5）

- 确认 `criterion`、整数 `pass_score`、分数锚点、两类依据和材料定位结构；明确生成完整性与人工新建空辅助内容的区别。
- 落实已确认的锚点密度：初始生成采用少量关键分数，并覆盖 AI 建议通过分的表现；建议分锚点存在性只由生成结果校验强制，不限制编辑 DTO 中任意整数通过分的保存。
- 涉及：`backend/app/lib/ai_runtime/adapters.py`、`backend/app/features/question_library/{schemas,service,repository,rubric_generation,rubric_rules}.py`。
- 联动生成 `backend/openapi.json`、`frontend/src/lib/api/generated.ts`；禁止手改生成 TS。
- 定义 thread/命令/attempt、完整公开消息 DTO、展示快照/恢复游标与鉴权合同；制定业务库新表和检查点库 setup 的各自迁移步骤。涉及 `backend/app/lib/operations/`、`backend/app/lib/database/models.py`、新 migration，以及有实际 M0 用途的 ai_runtime 持久化模块，不创建空的未来 Feature。
- 当前项目两库旧测试数据已获一次性清理授权；按 design.md 第 7.1 节实现重置预览、目标核对、备份与重建，实际切换时才执行。保留 Docker 实例与原始样本，不读取转换或重放旧图；新接入使用服务登记的新 thread。
- 旧两字段记录不迁移、不回填；通过清理后新合同重新上传完成切换。当前仅规划，最终实施批准前不操作现有数据库。

### 阶段 1A：样本与验收准备职责索引（C1 / C3 / C5）

- 本节前三项样本基线由 C1 交付，真实验收 runner 的新合同接入由 C3 同任务完成，安全重置工具由 C5 在最后交付；不得按旧阶段号把 reset 提前放进 C1。

- 以主工作区 `.local-samples/m0` 为显式只读来源，按 research/real-sample-validation.md 盘点 hash、解析消息/角色/工具块和材料时点，生成六材料输入、来源 manifest 与独立预期检查；真实内容写入当前 worktree 被忽略的验收目录，不改原件、不提交原始正文。
- 两组来源各整理至少一个证据完整的 case。老师终稿完整提取；实际 Bad case 与反馈配对；缺失 v6 正文不能以 v2 或工具路径冒充，助手思考与系统摘要不能标为老师原话。无法证明的样本/断言明确失败或限定覆盖，不静默跳过后报全通过。
- 基于真实 case 构造单点变异反例并标注派生来源；在运行生成器之前确定预期检查，不能从本次输出反向制造 golden。
- 更新现有 backend/scripts 真实验收入口与 frontend/scripts/real-acceptance.mjs 的样本参数、PostgreSQL 隔离和新合同。消除旧 ZIP 强依赖、前 800 字截断、缺失答案占位和伪造样本兜底；保留通用单测但不得冒充真实验收。
- 设计显式的一次性重置命令及 dry-run/白名单/回滚验证，先在本次独占验收库证明不会触碰其他库或样本。普通 `make test`、应用启动和 schema 检查不得隐式清空库；实际项目两库切换在阶段 6 执行。

## 阶段 2：受限生成器和材料工具（C2 原语；C3 生产接入）

- 获批后实时核查并采用当时最新正式 Deep Agents 及传递依赖，更新 lock；交付前复查，不为适配旧示例降级。复用 `build_runtime_model()`，先 stub 测试 Event Streaming、结构化输出、工具/权限和错误映射，再执行已获准的真实网关验证。
- 按现有 `lib/ai_runtime` 边界实现本题材料目录、读取/搜索、联合候选生成、硬校验反馈及有限修订；不创建新业务 Feature，不恢复历史共创链。
- 把全 job 调用数、耗时、token、SDK/job retry 和摘要调用纳入预算；保留现有 Worker 心跳、失租处理和最终 CAS/fencing。
- 禁用默认子代理、宿主机文件访问、shell、web、跨题记忆及业务写工具；不能只靠 prompt 声明禁止。
- 结果只有全份校验通过后才一次保存；失败不落部分 rubric，不跳过老师确认或自动发布。
- 给生成器注入公开 `ProgressSink`，消费所锁版本官方流式接口；确认版本 API 形状、同步/异步选择及实际 relay header/工具参数增量路径。结构化调用成功不等于流式验证通过。
- 实现作业归属、尝试隔离、fencing、增量合并、快照与游标恢复；新增受题目权限保护的 SSE 订阅，不由 HTTP 请求启动或拥有任务，不引入跨进程不可共享的内存队列冒充持久桥接。

### 阶段 2A：持久化与恢复（C2 原语；C3 业务闭环）

- 按 `runtime-design.md` 接入 PostgresSaver、StateBackend 与服务登记的 thread；在当前同步 Worker 路径验证同步流式、驱动/serializer、连接生命周期和 sync durability，不默认改成全异步。
- 补充设置、示例配置和显式检查点准备流程；当前 `.env` 已有相关变量但代码未消费，不能以此省略实现。绝不输出或重置既有密钥。
- 实现线程单写者及失租停止，验证锁与 saver 固定连接、断线后禁止旧写者换连接续写；仅有业务 CAS 不作为验收。
- 新建输入、checkpoint 续跑、已完成图结果补业务提交分别处理；稳定 command/message ID 防止重复追加，材料变更或 runtime 不兼容时明确拒绝旧运行。
- 完整公开输出先持久化后流向 UI；模型上下文摘要/工具消息裁剪不删除公开历史。过程原文与工作状态恢复分别测试，不能只做页面回放就称执行恢复通过。
- 用少量 class-based middleware 实现多 hook 观测/上下文策略，复用内置能力；验证顺序、状态更新、重试预算和中断透传，不把业务提交或授权仅放进 hook。
- M1 的 interrupt/Command(resume) 与正常消息协议按隔离 runtime 测试验证；M0 不先启用提问工具、聊天入口或空的 M1 业务枚举。已确认不接跨题 Store、不建跨题向量索引或全局偏好提炼任务；不要把未来选项写成必做清单。

### 阶段 2B：同题跨库删除（C3）

- 按 runtime-design 第 11 节保留原删除门禁，将门禁通过后的同题冻结、稳定删除命令和清理作业登记放入同一业务事务；更新 DELETE 合同与状态投影，不提前返回删除完成。
- 复用 OperationJob 的 kind/target、lease、attempt 和重试；同题线程映射在全部 checkpoint 清理完成前保留为清理定位。控制记录不复制原文，删除作业不属于会被删除的生成 jobs 集合。
- 清理该题所有历次 thread 的 checkpoint namespaces、pending writes、blobs、StateBackend 文件与摘要，再删除公开消息/快照和业务题目/生成历史，并原子提交清理作业成功。
- 所有同题写入、重生成、resume 和 SSE 回放检查删除冻结；接入单写者和迟到写 fencing，避免完成删除后旧 Worker 重建内容。拒绝或取消删除不能产生任何关联清理。
- 改造现有 Worker 中偏向 rubric_generation 的初始化与失败投影，只处理本任务新增 kind 的实际需要；清理不请求模型，不能被生成 Provider 配置/网络失败永久阻塞，不新增第二套队列。
- 清理中断、checkpoint 不可用和最后业务提交失败均可恢复；终态失败明确可见并可重试，不把冻结中的原文作为已删除成功，不自动解除冻结或重开旧题。

## 阶段 3：服务和前端审改闭环（C3）

- 完整保存/读取所有新增内容，覆盖 `patch_criteria`、发布/重新审改投影、生成成功投影、fake fixtures，避免辅助信息在中途被丢弃。
- 更新 `frontend/src/features/questions/criterion-draft.ts` 及 `components/criteria-editor.{tsx,module.css}`：保留勾选和任意整数输入，增加可编辑分档、依据折叠区及关联核对提示。
- 更新 `frontend/src/app/(app)/evaluation-sets/[sceneId]/questions/[questionId]/page.tsx`：重生成前提示整套替换，取消不提交；不新增分档下拉选择替代分数输入。
- 普通编辑、标题单改、取消、刷新恢复、主动整套重生成、published/reopen 权限分别走既有语义；不新增后台自动改写。
- 用真实阶段/流式消息时间线替换生成期静态文案与整题轮询；区分连接中断、等待模型、执行恢复、重试、失败和保存完成，刷新/重连不重复生成。完成后完整公开过程可分页回看，不只保留摘要。
- 优先同源 SSE，经现有 Next rewrite 验证增量可见、保活及代理超时；按需调整实际部署配置，不预设已有手写 BFF 路由。不增加虚构百分比、私有 reasoning 展示或前端假打字。
- 更新 deleteQuestion/handleDelete：原确认门禁不变，受理后展示删除处理状态和失败重试；只有清理完成才关闭同题订阅、清空受控草稿缓存并离开。不得保留收到 DELETE 响应就无条件当作成功的旧路径。

## 阶段 4：旧语义删除（C3 同任务完成；C5 处置旧数据）

| 检索/删除对象 | 执行要求 |
| --- | --- |
| `ModelRubricGenerator` 的旧单次调用路径、两字段 `_SYSTEM_PROMPT` 假设 | 若最终选 Deep Agents，在新路径可用后同任务删除旧生成路径；不留运行时切换开关。 |
| `CriterionDraft`、`CriterionView`、PATCH payload、Service 三字段投影 | 改为唯一新合同；删除缺字段默认补齐、旧 DTO 转换、只转存 criterion/pass_score 的路径。保留仍有效的字段名本身。 |
| 前端 `selectedToPayload`、`draftsFromDetail`、手工新增与来源标识 | 转为完整新合同；不继续生成/接受旧缺字段结构，不误删人工入口。 |
| fake、fixture、旧断言 | 全面更新两字段完成的假设；保留证明旧结构被拒绝的否定性回归，不恢复旧功能。 |
| 文档和生成文件 | 同步 README、backend/core 规格、cross-layer-contracts、OpenAPI/TS；历史归档任务保留。 |
| 数据 | 只按获批目标和范围处置；无运行时读取转换、自动批量补写或隐藏兼容。 |
| 旧加载/轮询生成进度分支 | 以新进度订阅和快照恢复替换；保留正常详情读取，不保留静态假降级、计时器假进度或前端模拟流。 |
| 无连续性/摘要唯一保存方案 | 替换从头重试的目标实现和摘要唯一历史假设；不恢复旧共创/旧线程兼容，当前项目旧 checkpoint 按已授权一次性重置处置，不扩展至其他库。 |
| 旧真实验收捷径 | 删除本任务相关验收入口的截断/占位/伪造真实样本兜底和两字段断言；失去样本、production Worker 或 PostgreSQL 时应失败，不静默降级。 |
| 删除早退与通用失败误投影 | 替换原同步 204 即完成及前端立即跳转路径；更新 cleanup 作业初始化/错误分派，不误删仍用于最终业务事务的硬删除与原确认门禁。 |

定向检索范围为 `backend/app backend/tests backend/scripts frontend/src frontend/e2e frontend/scripts README.md Makefile .trellis/spec`；`criterion`/`pass_score` 仍是合法字段，不能以“零字符串命中”代替逐项判定。

## 阶段 5：分层验证（C1/C2 定向；C3 核心；C4 扩展）

- 每个子任务运行自身门禁。C3 必须在交付前完成核心真实闭环、恢复和完整删除，不能将缺失基础能力或旧语义删除留给 C4。C4 扩大故障覆盖并修复其复现的范围内问题；C5 做发布前与实际环境复验。

### 后端与生成器

- 更新 `backend/tests/test_rubric_generation.py`、`test_question_library_api.py`、`test_question_review_contracts.py`、`test_openapi_contract.py`、相关 fixtures；沿既有模式增加有界工具/结构化输出测试。
- 覆盖全部 0–10 整数：初始 AI 建议 5 分但缺少 5 分表现描述时，生成结果校验应要求补齐；不能取整成 4 或 6，也不要求另外 10 个整数均有描述。
- 分开覆盖人工编辑：老师将通过分改为 5，现有锚点只有 4/6 时仍允许保存；不自动补写描述、不增加锚点白名单或范围通过分校验，小数/越界仍拒绝。
- 覆盖虚构 source、跨题定位、错误原文、Bad case/反馈绑定、明确要求与数字推定分别标记，以及 output parse/引用校验失败后的有界修订与预算耗尽。
- 覆盖 prompt injection、材料只读、无默认委派入口、无宿主机/web/DB 工具、无跨 job 信息泄露。
- 覆盖 Worker heartbeat、失租、旧 revision、重复执行、并发重生成、失败不部分提交，以及保存/发布后辅助内容不丢失。
- 覆盖流式消息/工具/custom 事件归一、结构化输出无自然语言的情况、脱敏/长度边界、按 job/attempt fencing、事件序列与去重、断开不取消作业、晚订阅恢复终态及登录/归属校验。
- 覆盖安全停止与正常长等待的区别、终态保存前不能发成功、进度传输中断不直接重启 Agent；不将两分钟以内完成作为本需求验收门槛。
- 增加隔离 PostgreSQL 恢复/连接测试：中止自有 Worker、已完成 checkpoint 未提交业务、重复输入、同 thread 双执行、失租迟到写、连接池归还与密钥重启读取。测试只用本次独占的新数据；已授权旧库重置也不意味着可以对其他活跃运行注入故障。
- 增加上下文与 middleware 测试：同题工作文件恢复、跨题隔离、摘要后原文完整、tool_call/ToolMessage 配对、hook 顺序、state update、interrupt 不被错误重试、重复/过期 resume、暂停释放资源。
- 按 runtime-design.md 第 7 节验证已确认的本题独立要求：B 题变化不触发 A 更新、不改变 A 的实际输入/工具范围；覆盖恢复和摘要路径，不用“模型偶然输出相同”代替隔离证据。
- 按第 11 节验证完整删除：两库、所有历次 thread、原文消息/快照与工作文件无残留；覆盖拒绝/取消无副作用、部分清理后崩溃、重复命令、失租迟到写、checkpoint 不可用后重试、模型初始化失败仍可清理，以及兄弟题和批次回执不受影响。旧同步删除测试改为新完成合同，原门禁断言保留。

### 前端

- 更新 `criterion-draft.test.ts`、相关组件测试和 `frontend/e2e/04-question-review.spec.ts`。
- 验证勾选、手工新增、正文/分档/依据编辑、5 分自由输入、按需展开、刷新恢复和 published 只读。
- 改分后旧依据明确对应原数值，核对提示不修改内容；没有额外生成请求，人工改动不被后台覆盖。
- 重生成弹窗说明替换人工修改；取消无写请求，确认仅一次写请求；标题单改不触发模型任务。
- 覆盖阶段回退补查、流式更新可见、长时间等待模型、断线/刷新/隐藏恢复、乱序/重复/旧 attempt、终态事件丢失及真正 API 失败；连接动画不得冒充任务推进。
- 增加实际 rewrite 链路的流式 E2E：证明生成未完成时浏览器已收到真实增量；验证不抢滚动、节流读屏和 reduced-motion。mock 只证明 UI，不冒充生产模型/Worker 验收。
- 验证公开文本完整回放、后台重启后的恢复提示、部分输出与新 attempt 不被静默拼接；不能用最终一句摘要、只恢复页面或一段假流证明整个运行上下文已恢复。
- 验证原删除确认字段/状态限制不变，处理中/失败/完成分明，刷新可继续查询清理状态；成功后清掉同题前端状态，不可通过回放/详情重新读原文。真实验收同时查存储，不只断言路由跳转。

### 获批后的命令和真实效果证据

```bash
git diff --check
make openapi
make frontend-generate-api
make contract-check
make frontend-check-api
make test
make build
make frontend-e2e
```

- 真实数据集成与冒烟是独立必做门禁，不包含在普通 `make test` 内。先更新 `make ai-smoke`、`backend/scripts/accept_real_ai_rubric.py`、上传 Skill 验收入口和 `make accept-web` 的样本输入与 PostgreSQL/新合同支持，再执行；不能直接运行当前旧脚本后声称本次要求已验证。
- 样本来源参数指向 `/Users/hsikey/Company/skill-eval-platform/.local-samples/m0`。产物包含真实输入、manifest、独立断言、各层结果与 operation/thread/checkpoint 关联证据；两组来源均跑真实闭环，至少完成真实 Worker 重启恢复。缺失、失败、跳过项必须单列。
- 同一 Docker 实例中准备本次独占验收库、存储及空闲端口，仅清理本次启动的进程；移除所用真实验收入口强杀固定端口监听者的做法。按现行要求复制 `.env` 后显式覆盖隔离库目标，不输出凭证。
- 授权后以同模型/同材料/同合同对照三种策略，记录老师修订负担、材料覆盖/引用/锚点质量、成本和 P50/P95 耗时；不以假模型、一次 provider smoke 或无错误 JSON 冒充效果提升。
- 真实样本使用已获授权，实际模型运行随最终实施批准后进行。只报告实际测得的修订/质量证据，没有老师参与的项目不得伪称“老师已认可”；不以用户以后自己重新上传替代本任务验收。

## 阶段 6：各子任务 main 闭环、C5 切换与父任务总验收

- 依项目要求执行 trellis-check、定向遗留检索和完整质量门后，仅提交本任务文件；当前规划阶段不提交、合并或推送。
- 合并前核对 main 是否前进，按项目安全 worktree 流程串行集成；不强改其他 worktree 检出状态，不用 force/reset 制造可合并状态。
- main 上重新执行完整质量门、真实样本集成与冒烟及浏览器闭环，确认任务提交均被包含；需远端时另核对实际远端 SHA。
- 隔离验收与 main 复验通过后，在部署切换步骤按一次性授权重置当前项目两库，运行新 schema/checkpointer 准备与启动检查，确认可重新注册和上传。停止本项目自有写入进程并核对目标，不删容器/其他库/`.local-samples`；旧数据备份只用于受控回滚。
- 验收前后核对原始 6 个业务样本的 hash，保留可重放测试输入与脱敏报告；交付题库不默认保留隔离验收脏数据，用户可自行重新上传测试。
- 复验成功再归档和记录，清理仅限本任务的干净 worktree/分支；任何门禁失败保留现场，不强删。
- 若需运行时回滚，按获批 Git/数据库备份/部署计划成套回退，不启用长期遗留代码路径。
- 上述分支/合并/复验/归档规则对每个子任务分别适用；父任务须等 C1-C5 全部完成并核对跨任务证据后再收尾，不承担未分派的最后一轮代码修补。

## 本轮证据边界

已做：需求与代码研究、独立 worktree 规划文档、官方文档/最新发布包/指定技能交叉核查、Docker 和两库只读元数据检查、`.local-samples` 来源盘点与取样依据核查。旧测试数据的一次性重置和真实样本使用已获授权。未做：产品实施、依赖安装、真实 fixture 生成、数据库清理/setup/迁移、旧图重放、真实模型/恢复试跑、产品测试/构建、提交/合并/推送。
