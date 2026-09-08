# 统一 AI Harness 运行合同，修复思考强度与工具调用冲突

## 目标

让蓝标汽车事业 BenchMark 平台在保留管理员配置的思考强度时，可靠完成带工具调用的评分维度生成；通过一致的 Harness 装配与完整链路验收，避免“模型单独可用、实际 Agent 不可用”再次进入运行环境。

本任务为父任务，拥有总需求、共享设计和最终验收；[任务映射](task-map.md)将交付拆成 C1 能力验证、C2 生产原子切换与完整验收，严格串行。父任务不直接实施产品。

## 背景与证据

源码基线为 `f108fe7`。当前部署使用 `openai / gpt-5.6-luna / medium`，模型工厂在 `backend/app/lib/ai_runtime/model.py:167` 强制 Chat Completions。本次失败检查点保存了上游 HTTP 400：该服务端不支持此模型在 Chat Completions 中同时使用函数工具和思考强度，提示 Responses 或 `none`。

项目已使用受限 Deep Agents；问题出在模型协议、Harness 装配、运行指纹及验收没有形成一致合同。三次 attempt 均在首个模型调用阶段失败，适配层又把 SDK 的不可重试错误变成可重试错误（`adapters.py:33`、`:547`）。原先新增的请求测试没有绑定 Agent 工具（`backend/tests/test_ai_runtime_model.py:59`）。完整事实、调用链和证据边界见 [研究记录](research/incident-and-call-chain.md)。

## 范围内需求

| 编号 | 要求 |
|---|---|
| R1 能力组合 | 保留当前模型、端点和 `medium`，在同一真实生成中支持材料读取工具、完整评分项结构、公开流式反馈；不得以关闭思考、删工具、换模型或降低评分项合同冒充修复 |
| R2 一致装配 | 模型、工具限制、结构化输出、验证/纠正和恢复身份使用同一份已解析合同；正常运行与验收走同一生产装配入口 |
| R3 错误与纠正 | 参数/鉴权/权限等确定性错误停止自动重复；瞬时错误遵守已有有限重试；模型可纠正的内容错误仍走现有有界纠正，不能让模型通过 Prompt 修复协议错误 |
| R4 连续性 | 同合同下保留工具消息和必要的内部推理续传数据，重启后从检查点续跑；合同变化不得沿用不兼容上下文，也不得悄悄改为依赖服务端会话存储 |
| R5 可诊断 | 管理员得到可行动的中文失败说明，运维可按作业与 attempt 查到协议、状态码、参数类别和诊断分类；错误/日志/公开流不暴露凭证、材料、原始请求或私有推理 |
| R6 业务边界 | 保留本题材料隔离、无 shell/子代理/跨题 Store、有限预算、单写者、租约/fencing、最终 CAS 及先保存再完成；模型不可用时删除清理继续可用 |
| R7 一次性替换 | 删除“OpenAI 永远强制 Chat”的隐含规则、绕过原生协议分发的 `_generate`、旧的分散运行指纹和通用错误默认可重试路径；同步当前维护文档与测试，不保留错误后自动换协议、删参数或兼容旧指纹的入口 |

显式配置的 Chat Completions 仍可用于实际需要它的兼容厂商；它是现行协议选项，不是本次失败后的自动降级路径。Anthropic Messages 保留现有能力，本任务不新增 Anthropic thinking 支持。

## 验收标准

最终验收记录（2026-09-08，交付 SHA `4dc71c9`，归档收尾 `741e864`；全部证据可由表中入口复核）：

| 编号 | 可观察的通过条件 | 对应需求 | 结果与证据 |
|---|---|---|---|
| AC1 | 目标组合经过实际生产 Harness，发生真实材料工具调用及至少一次工具结果回送，返回符合当前 schema、锚点、依据和引用规则的非空评分项；全过程保留 `medium` | R1、R2 | ✅ L01 探针（11 次工具往返、4-5 维度全合同校验、每请求 reasoning.effort=medium）+ L02 两组真实样本经生产 Worker 完成；证据 `backend/storage/acceptance/c1-capability/`、`m0-accept-real-ai/`（gitignored），C1 归档报告与 C2 prd 状态行 |
| AC2 | 最终发送的协议、思考参数、工具集合及输出策略与登记的合同完全一致；同步普通调用、Agent 流式及内部模型调用均遵守协议选择 | R2 | ✅ 探针逐请求断言（/v1/responses、medium、7 文件工具、text.format=json_schema、store=false、无 previous_response_id）；离线 T01–T04 含同步 invoke 与流式的原生分发（tests/test_ai_runtime_model.py） |
| AC3 | 本例 400 在第 1 次 attempt 后进入失败终态，不再自动发起第 2/3 次；修正配置后的显式重试仍可恢复，题目材料保留 | R3 | ✅ T07 worker 级测试（attempts=1、failed 终态、AI_CONFIG_INVALID、材料不变、run_failed 事件、显式重试受理）；translate_provider_error 不可重试分类 |
| AC4 | 429/超时/服务端临时错误仍有限重试；schema/引用纠正使用原有有限预算；中断、取消及未知程序错误不被吞成可重复执行的普通失败 | R3、R6 | ✅ T08/T09 离线 + 真实运行中 structured_output_validation 瞬时失败按 attempt 预算自愈（main 验收诊断记录实证）；审查修正补齐裸 httpx/APIError 瞬时白名单；未知错误 retryable=False |
| AC5 | 工具轮之后重启 Worker，恢复时不重复初始输入；graph 已完成而业务未提交时不重新调用模型；协议/思考强度/schema/Harness 合同变化触发已有不兼容重建流程，旧数据不被跨协议转换或回填 | R4 | ✅ L03 真实外部 Worker SIGKILL→lease 过期→重启恢复（同合同指纹 a5d6adf7…，run_resumed/thread_state_incomplete 事件，初始输入恰 1 次）；P02/探针 reread 完成态零模型调用；T10/P03 指纹变化重建、无转换回填 |
| AC6 | 公开流不包含 reasoning/encrypted_content/凭证/原始工具正文；运维诊断可按作业定位本例的 HTTP 400 和 reasoning 参数类别，不再只有异常类名 | R5 | ✅ T06/T12 哨兵测试三出口（last_error/事件/诊断文件）；真实诊断记录含 http_status/param/request_id/operation/question/attempt/thread/合同身份（accept 运行 stderr 实证）；storage/runtime/ai-diagnostics.jsonl |
| AC7 | 原有权限、CAS、发布确认、SSE 回放、材料编辑、删除清理及模型不可用清理测试通过；不新增业务状态、评分算法或 HTTP 字段 | R6 | ✅ 分支与 main 全量 make test（backend 404 + frontend 74）+ RUNTIME_PG_REQUIRED=1 17 项 + L04 浏览器链（发布/重开/审改/删除零残留/断线回放）；openapi 合同零漂移 |
| AC8 | 旧逻辑定向检索、文档与测试同步完成；完整质量门和目标组合的真实 Worker→PostgreSQL→浏览器验收在任务分支及合并后的 main 均通过 | R7 | ✅ 审查代理 A 定向检索 8 项删除全 DONE 零残留；README/.env.example/spec/deploy 模板同步；L05 在 main 检出重跑 make test/build + PG 门 + L01–L04 全 PASS（证据 git_sha=4dc71c9） |

完整分层验证、失败注入和禁止冒充验收的规则见 [验证矩阵](research/validation-matrix.md)。

## 不在本任务范围

- 重写 Deep Agents/LangGraph 的执行循环、另建通用 HarnessManager、模型路由/自动 fallback、通用能力市场。
- 扩大模型/厂商清单、顺手升级依赖、迁移到异步或实验性 v3 流协议。
- M1 新稿生成、实际评分、聊天/HITL 产品入口、跨题长期记忆或宿主机访问。
- 重做 UI、改变评分项标准、清理无关代码；其他 worktree 的材料面板调整不在本任务内。
- 规划期或自动验收触碰当前业务两库、自动重试原失败题、清空数据、重启现有服务或启用外部 tracing。

## 技术验证前提与风险

本轮已证实当前请求组合失败，以及已安装 SDK 可构造 Responses 下同一工具和 schema 请求。**当前网关的完整 Responses 能力仍未验证**。C1 必须验证工具往返、native schema、`store=false` 下的加密推理续传和持久化恢复；通过且交付到已验证 main 后才可开始 C2。失败则保留证据并回到计划，不静默换模型、关闭思考或启用服务端状态。

本例实际选择的是原生结构化输出，未强制 tool_choice。采用此策略并不意味着任何“OpenAI 兼容”端点都支持它。具体选择和失败边界见 [技术设计](design.md)。

## 审批状态

- 2026-09-08 用户明确批准本父子计划并要求实施执行，批准覆盖整棵任务树（C1、C2）；实施按 C1 → C2 严格串行。
- 2026-09-08 任务完成：C1（能力门 PASS，归档 378e809）→ C2（生产切换交付 4dc71c9，归档 741e864）→ 父验收 AC1–AC8 全部通过（见上表）。主环境切换/原题重试不在本任务执行范围，按运维动作另行处理。
- 父任务保持协调职责，不作为产品实施入口，不运行父任务的 `task.py start`。
- 真实模型调用授权：C1 `--execute` 能力门与 C2 真实验收门在本批准范围内，仅限任务独占隔离资源；当前业务两库、现有常驻服务与原失败题自动重试仍不在授权内。
