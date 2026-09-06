# 当前生成链路、材料依据与框架研究

研究日期：2026-09-05。只做静态代码、官方文档和发布包检查；没有安装 Deep Agents、调用真实模型或测量质量、费用、耗时。候选设计不等于已批准实施。

后续决定：用户要求最新 Deep Agents，并接受带真实阶段/流式反馈的长等待。版本复查与流式加载方案见 `streaming-progress.md`；本文保留此前策略比较，不再将短等待容忍度或是否使用旧 SDK 当作未决问题。

进一步决定：完整公开消息与同题上下文需要持久保存，检查点使用当前 Docker PostgreSQL。运行方案见 `../runtime-design.md`，实际数据库与指定技能核查见 `persistence-middleware.md`；此前无连续性的目标提案不再适用。

## 1. 当前代码实际如何生成

| 环节 | 现场证据 | 结论 |
| --- | --- | --- |
| 输入 | `backend/app/lib/ai_runtime/adapters.py:50` | 六类材料进入 `RubricGenerationInput`；反馈嵌在 Bad case 中，故顶层五个字段。标题、场景名称不作为额外生成依据。 |
| 模型输出 | 同文件 `CriterionDraft:62`、`RubricGenerationResult:69` | 每项只生成 `criterion` 与 `pass_score`；分数是 0–10 整数。Schema 允许 1–20 项，Prompt 建议 2–6 项。 |
| 调用 | 同文件 `ModelRubricGenerator.generate:139` | 对同一个聊天模型执行 `with_structured_output(RubricGenerationResult, method="function_calling")`，一次 `invoke(messages)` 联合返回维度和通过分。不是两次独立生成，也不是正则提取自然语言里的数字。 |
| Prompt 与材料 | 同文件 `_SYSTEM_PROMPT:162`、`_render_materials:170` | 固定 system prompt，加上拼接的本题材料全文；没有 `create_agent`、`create_deep_agent`、自主工具循环或语义修订步骤。 |
| 模型工厂 | `backend/app/lib/ai_runtime/model.py` | 自建聊天模型工厂支持 OpenAI-compatible Chat Completions 和 Anthropic；OpenAI 路径关闭 Responses API，并有 relay header/raw-response 兼容处理。 |
| 业务保存 | `backend/app/features/question_library/rubric_generation.py` | Worker 取得输入，调用 adapter，校验候选、补 ID，再以 revision/CAS/job fencing 原子提交完整结果；adapter 不直接写库或发布。 |
| 前端审改 | `frontend/src/features/questions/criterion-draft.ts`、`components/criteria-editor.tsx` | 勾选维度、编辑内容、填写整数通过分；选中的草稿投影为提交内容，另有手工新增入口。 |

“一次逻辑模型调用”不是“一定只有一个 HTTP 请求”：SDK 重试和 Worker 重试可能增加请求。

当前主要缺口不是“没有高级 Agent”，而是输出只描述判断事项和一个数，没有可观察的分数表现说明、可核查依据，以及它们之间的一致性校验。合法 JSON 只能证明形状合规，不能证明依据充分或标准可用。

## 2. 输入体量与实际工程约束

- `question_library/schemas.py` 允许题目 100,000 字符、标准答案 200,000 字符；单条参考、记忆和 Bad case 正文各可达 200,000 字符，三类列表各最多 50 条。当前全部拼接，而不是按模型上下文预算读取。
- 这是允许输入的上界，不是实际业务材料分布；本轮未统计用户真实题目长度。定向检索未找到后端全题 token-budget/request-body guard，不据此声称网关和部署层完全没有限制。
- 长输入为“材料目录、按需读取、受限搜索、覆盖检查”提供了具体价值，但检索也可能漏掉低频重要要求。题目、标准答案、反馈应建立必读覆盖规则；无法完成必要覆盖时不能伪装成已完整核查。
- `OperationWorker` 已有独立心跳续租线程，不需要因为引入 Agent 就另造队列；默认模型请求 timeout 180 秒、SDK retries 1、lease 60 秒、job max attempts 3。
- 新增多轮调用须有整个 job 的调用数、总耗时和 token/费用预算，不能把单请求 timeout 当整题预算。例如一次尝试计划 6 次模型调用，若每次最多 2 个 HTTP 尝试、job 最多 3 次尝试，理论上可放大到 36 个 HTTP 尝试；此数只是重试叠加示例，不是性能实测。

## 3. Deep Agents 的已核实能力和未核实条件

- 官方定位是基于 LangChain/LangGraph 的 agent harness，提供材料/文件工具、规划、上下文管理和子代理等能力。它不是另一种推理模型，也不是与 LangChain 相互排斥的替代品。
- 本轮从官方 PyPI 获取 `deepagents==0.7.13` 的 metadata 与 wheel，在内存校验 wheel SHA256 后用 AST 检查，未安装或执行包；该 wheel 上传时间为 2026-09-02T17:36:37Z。本报告以此具体版本为候选，不宣称它永远是最新版。
- `create_deep_agent` 的该版本参数含 `model`、`tools`、`middleware`、`subagents`、`permissions`、`backend`、`response_format`、`checkpointer` 等；`deepagents/graph.py:956` 内部调用 `create_agent`。
- 发布包要求 Python >=3.11,<4，`langchain>=1.3.18,<2`、`langchain-core>=1.6.1,<2`、`langchain-anthropic>=1.7.0,<2`，另依赖 `langchain-google-genai` 等。
- 当前主工作区 `.venv` 可见 `langchain-core 1.6.1`、`langchain-openai 1.6.0`、`langchain-anthropic 1.7.0`；`langchain`、`langgraph`、`deepagents` 未安装。项目不是已有 Deep Agents 链路的简单开关切换。直接下界匹配不等于整个 lock 解析或 relay 运行兼容已通过。
- 官方支持结构化输出与调用限制 middleware；采用 `response_format` 不会自动消除引用错误、模型自我确认偏差或上下文遗漏。
- 默认 harness 可能带通用子代理、文件写工具等。本轮发布包包含 `GeneralPurposeSubagentProfile.enabled`；不能假定传 `subagents=[]` 就关闭了默认通用子代理。后续要锁定版本、显式配置并断言实际暴露的工具集合。
- 当前官方文档说明 v0.7 起任务规划为按需开启，并提供 `FilesystemMiddleware` 工具白名单；不能照搬旧 Skill 中“规划默认开启”的描述。路径 permissions 未匹配时默认允许，且不能替代自定义工具的权限检查；材料隔离仍需由后端保证。
- 官方结构化输出能力与项目 relay 的 tool-call 行为必须专项验证；继续使用项目 `build_runtime_model()`，不复制文档中的默认模型配置。

## 4. 三种生成策略

| 策略 | 适用情况 | 优点 | 代价和风险 |
| --- | --- | --- | --- |
| 一次联合生成 | 材料短、证据简单、耗时约束强 | 同一上下文产出整份 rubric，调用路径最小 | 全文超窗、长材料漏读、缺少定向补证据；增加字段后输出更长 |
| 固定阶段流程 | 读取和检查步骤大致固定 | 材料梳理 → 联合生成 → 规则校验 → 有限修订，预算与行为容易解释 | 遇到复杂材料时不如工具循环灵活；多阶段也会增加耗时，不天然保证质量 |
| 受限 Deep Agents | 材料分散或较长，需自主决定读哪段、追查哪条反馈 | 复用材料工具和上下文管理，让模型按问题补查，再产出同一完整合同 | 更多依赖、工具权限和预算管理；可能漏检、循环或自证；需真实样本比较 |

推荐研究方向：**受限 Deep Agents + 确定性业务外壳**，而不是“因为更高级所以全部自主”。整体是一项后台生成任务，内部可以多轮读取和修订，最后只提交一个完整结构化结果。

维度、分档、通过分与两类依据保持联合生成；不按字段分四五次独立调用，也不默认每个维度交给不同代理。读取材料可以分步，校验可以分层，最终结果必须自洽。

框架选择与质量来源应分开验证：必须将同模型、同材料、同样输出合同的固定流程作为对照。若 Deep Agents 无实际材料读取/修订收益，只增加开销，不应为了框架名词采用它。

## 5. 文案维度研究对本题生成的启示

- CMU 对 rubric 的定义区分评价事项、表现描述和表现层级。这支持增加分数锚点，却不要求把老师的通过分输入改成“档位选择”。数字、数字的表现解释、最终选择权是三个不同问题。
- SummEval 在摘要任务中区分一致性、相关性、连贯性、流畅性。可据此提醒生成器区分“材料事实是否一致”“所需内容是否覆盖”“结构是否连贯”“表达是否易读”，不能把这组摘要标准宣布为所有文案的通用必选项。
- 在这些研究之外，本题还可以依据材料检查受众/体裁/渠道适配、语气和品牌表达、新颖性/辨识度等方向；这是设计候选方向，不是研究已证明的固定分类或每题必选清单。
- 是否需要新颖性、最低要求多高，应回到本题材料和老师反馈；不能把新闻稿自动套用创意广告的高新颖性要求。维度存在与最低通过要求很低可以同时成立。
- “老师说太套路”只能直接支持老师在意辨识度，不能直接支持“老师要求至少 6 分”。数字门槛若不是老师明确给出，应标记为 AI 推定，并解释与表现锚点的关系。
- 引用存在性可以程序验证，引用是否真正支持该主张仍有语义判断；第二次模型检查也不是正确性证明。老师核查与修订权不可被 harness 取代。

## 6. 后续效果验证，不是本轮已完成工作

- 用经授权的同批材料，对照“扩展后的一次联合生成”“固定校验流程”“受限 Deep Agents”；不能只拿旧两字段输出与新长输出比较后宣布框架获胜。
- 关注本题要求覆盖、引用准确性、明确要求/推定区分、锚点可观察性和单调性、建议分与说明一致性、老师为达到可用标准的修订负担，同时记录调用数、token、费用与 P50/P95 耗时。
- 样本至少包含简单题、多 Bad case、长材料、低新颖性门槛、老师给出明确数字、只有模糊反馈、材料内提示注入等情况；不在这项验证中生成 M1 新稿或评分。
- 旧测试数据可一次性清理，真实样本指定为 `.local-samples`，使用与集成/冒烟要求已由 D21/D22 确认，详见 real-sample-validation.md。工程预算在获批实施时有界配置并验证，review.md 等待最终实施批准；静态源码、官方文档和 wheel 校验不替代实际效果证据。

## 官方与一手来源

均于 2026-09-05 检索；在线文档是滚动版本，具体实现以选定版本和锁文件为准。

1. Deep Agents overview：`https://docs.langchain.com/oss/python/deepagents/overview`
2. Deep Agents harness：`https://docs.langchain.com/oss/python/deepagents/harness`
3. Deep Agents customization：`https://docs.langchain.com/oss/python/deepagents/customization`
4. Deep Agents backends：`https://docs.langchain.com/oss/python/deepagents/backends`
5. LangChain structured output：`https://docs.langchain.com/oss/python/langchain/structured-output`
6. LangChain built-in middleware：`https://docs.langchain.com/oss/python/langchain/middleware/built-in`
7. Anthropic, Building effective agents：`https://www.anthropic.com/engineering/building-effective-agents`
8. PyPI release metadata：`https://pypi.org/pypi/deepagents/0.7.13/json`
9. CMU, Creating and Using Rubrics：`https://www.cmu.edu/teaching/designteach/teach/rubrics.html`
10. Fabbri et al., SummEval (TACL 2021)：`https://aclanthology.org/2021.tacl-1.24/`
11. Deep Agents profiles：`https://docs.langchain.com/oss/python/deepagents/profiles`
12. Deep Agents permissions：`https://docs.langchain.com/oss/python/deepagents/permissions`
