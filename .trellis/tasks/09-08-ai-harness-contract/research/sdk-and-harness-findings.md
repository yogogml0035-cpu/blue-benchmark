# SDK、技能经验与 Harness 决策证据

日期：2026-09-08。结论按“服务端事故证据 → 当前安装源码/受控构造 → 官方文档 → 技能经验”核对。资料中的建议不自动成为产品范围或实施授权。

## 1. 版本和原生能力

| 包 | 本地安装版本 |
|---|---|
| deepagents | 0.7.13 |
| langchain | 1.4.0 |
| langchain-core | 1.6.1 |
| langchain-openai | 1.6.0 |
| langchain-anthropic | 1.7.0 |
| langgraph | 1.2.11 |
| langgraph-checkpoint-postgres | 3.1.2 |
| openai | 3.6.0 |

本轮只读查询 PyPI，`deepagents` 最新正式版仍为 `0.7.13`。这次修复没有升级 SDK 的已证实必要性；实施开始与交付时复核版本，新增版本的存在本身不是升级理由。

关键安装源码（相对 `backend/.venv/lib/python3.13/site-packages/`）：

- `deepagents/profiles/provider/_openai.py:21`：OpenAI ProviderProfile 默认 `use_responses_api=True`。
- `deepagents/graph.py:271`：构造函数是 `create_deep_agent`（单数），不接受 `harness_profile=`；`:323` 说明预构造模型可以显式选择协议。
- `deepagents/graph.py:614`：传字符串才经 `resolve_model`；传实例仍解析 HarnessProfile，但不会重新执行 ProviderProfile 的模型构造默认值。
- `langchain/agents/factory.py:560`、`:1355`：直接给 schema 时按模型 profile 选择 ProviderStrategy/ToolStrategy；显式策略不会在上游 400 后自动切换。
- `langchain/agents/factory.py:1422`：ToolStrategy 可能强制 `tool_choice="any"`；不能把模型包装层的 `disabled_params` 经验错误迁移到 Agent 层。
- `langchain_openai/chat_models/base.py:1915`、`:3702`、`:4479`：SDK 原生负责两种协议的路由、流式以及消息/工具/schema 参数转换。
- `langchain_core/exceptions.py:70`：`ModelInvalidRequestError.is_retryable=False`；限流、服务端错误、连接失败和超时有自己的可重试类型。

## 2. 本轮受控请求构造

使用本任务 worktree 源码、主工作区已安装依赖、占位凭证与合成文本；通过实际 `build_restricted_agent → create_deep_agent → graph.stream → 模型 SDK` 截获首个请求。没有调用真实模型、使用业务材料、连接业务/checkpoint 数据库或修改产品文件。

首轮实验只拦截了 `httpx.Client.send`，未覆盖 OpenAI 3.6.0 内部另一种 HTTP 客户端，候选构造尝试连接占位端点后失败；该轮不作为候选通过证据。随后改为显式 MockTransport，并在进程内禁止 socket 连接，两条路径均完成离线截获。由此要求正式离线测试具有阻止漏网网络调用的门禁，不能只假设 SDK 始终使用同一个 HTTP 包。

| 观测项 | 当前工厂 | 原生 Responses 候选（仅内存构造） |
|---|---|---|
| HTTP 路径 | `/v1/chat/completions` | `/v1/responses` |
| 思考强度 | 顶层 `reasoning_effort=medium` | `reasoning.effort=medium` |
| 输入形状 | `messages` | `input` |
| 结构化输出 | `response_format.type=json_schema` | `text.format.type=json_schema` |
| 工具 | delete / edit_file / glob / grep / ls / read_file / write_file | 同一工具集合 |
| 工具选择 | 无强制 `tool_choice` | 无强制 `tool_choice` |
| 流式 | `stream=true` | `stream=true` |
| 服务端会话存储 | 未显式设置 | `store=false` |
| 无服务端状态的推理续传 | 未显式设置 | `include=[reasoning.encrypted_content]`，不使用 previous_response_id |
| 当前项目 telemetry header 清理 | 生效 | 裸模型未带项目 hook，因此 header 仍存在；实施必须在原生 SDK 上保留已需要的 HTTP 配置 |

结论：本例实际走原生 schema 策略，不是 schema 被变成函数工具后强制选择失败。工具来自 Deep Agents 文件上下文能力。将 JSON mode、ToolStrategy 或 `disabled_params` 当成通用补丁没有本例依据。

候选仅证明 SDK 能构造对应请求。**Responses 端点可用、工具往返、原生 schema、无服务端存储的推理历史、真实流式和断点恢复均尚未在当前网关上验收。** 它们构成实施阶段的第一道真实能力门。

## 3. 技能经验如何采用

已阅读 `ecosystem-primer`、`deep-agents-core`、`deep-agents-memory`、`deep-agents-orchestration`、`langchain-middleware`、`langgraph-persistence`、`langchain-dependencies`，以及用户指定的 `langchain-dev-guide` 和其 Deep Agents、模型集成、结构化输出、middleware、streaming 参考。

| 经验 | 本任务的采用方式 |
|---|---|
| Deep Agents 对工具调用能力要求高 | 按完整配置组合验收，不按模型品牌、SDK 接受参数或一次对话判断可用 |
| Harness 已提供上下文与工具循环 | 保留原生 create_deep_agent；应用只拥有装配合同、业务校验和生命周期边界 |
| ProviderProfile 与 HarnessProfile 不同 | 前者只作用于字符串模型构造；后者管行为和工具限制，不能替代 HTTP 协议配置 |
| 结构化输出有模型包装与 Agent 两条 API | 使用 Agent 的 ProviderStrategy/ToolStrategy，不叠一层 with_structured_output 来绕过 Agent |
| 工具错误、瞬时失败、配置错误应分类 | 复用 SDK 标准异常与 is_retryable；配置错误交给运维纠正，内容错误才允许模型有限纠正 |
| middleware before/after/wrap 顺序不同 | 保留既有观测与限制，只在完整装配后的请求处验证最终有效工具和参数 |
| StateBackend、checkpointer、Store 范围不同 | 保留 StateBackend + 加密 PostgresSaver 的同题连续性；不新增 Store/跨题记忆 |
| reasoning 历史可能需要往返 | Responses 的 opaque encrypted_content 在内部消息/checkpoint 中保留；公开事件仍过滤 reasoning |
| 流式 API 输出结构有版本差异 | 继续使用当前已验证的同步 stream + sync durability，不顺手迁移实验性 v3 Event Streaming |

明确不照搬的内容：

- 技能中的 `harness_profile=`、`StateBackend(runtime)` 示例与当前安装签名不符。
- “核心 middleware 一律不能调整”“StateBackend 一律不能持久化”缺少版本/范围条件；当前版本支持部分 profile 排除，StateBackend 的线程状态可由 checkpointer 持久化。
- 不按技能示例启用默认子代理、宿主机文件系统、外部 tracing、模型 fallback 或另一层重试；这些都不是本次目标所需。
- 技能中的模型排名不是当前网关的兼容性或本产品质量证据。

## 4. 第一性原理下的最小设计

“LLM + 上下文 + 工具 + 约束 + 验证 + 纠正”适合描述本产品的受控生成系统，但各部分不必塞进同一个类或一组 middleware。

| 要素 | 本项目应该由谁负责 |
|---|---|
| LLM / 协议 / 思考强度 | 模型工厂从同一份已解析合同构造原生 provider 模型 |
| 本题上下文 / 工作文件 / 历史 | Deep Agents StateBackend + 同线程 checkpointer，服务只提供当前题目的不可变材料视图 |
| 工具循环 / 结构化结果 | create_deep_agent + LangChain 原生工具节点及明确的 Agent 输出策略 |
| 权限 / 工具可见性 / 预算 | 精确模型 HarnessProfile、permissions、现有每次运行独立的观测和预算机制 |
| 结构和引用验证 | 原生 schema 校验 + 现有确定性业务校验；业务服务继续决定能否提交 |
| 内容纠正 | 原有一次引用修订和有界 schema 纠正；预算仍生效 |
| 配置纠正 | 输出可关联诊断并停止自动重复；由管理员修正配置后按既有动作重试 |
| 运行恢复和业务提交 | 统一合同指纹 + 服务线程登记；Worker/数据库继续管理租约、fencing 和 CAS |

由此只需要在既有 ai_runtime 内收敛装配与身份来源，不需要新建通用 HarnessManager、配置注册平台、自研 Agent loop 或动态模型路由。

## 5. 官方来源（本轮实际读取）

- [Deep Agents Profiles](https://docs.langchain.com/oss/python/deepagents/profiles)：模型构造 profile、Harness 行为 profile、实例解析、合并式注册。
- [Deep Agents Models](https://docs.langchain.com/oss/python/deepagents/models)：预构造模型是正式支持的用法；兼容性需具体模型和 Provider 验证。
- [LangChain Structured output](https://docs.langchain.com/oss/python/langchain/structured-output)：Agent 输出策略、同时使用工具的约束、schema 纠正。
- [Deep Agents Fault tolerance](https://docs.langchain.com/oss/python/deepagents/fault-tolerance)：区分瞬时、模型可纠正、人可纠正及未知错误；标准异常的 is_retryable。
- [PyPI deepagents 元数据](https://pypi.org/pypi/deepagents/json)：本轮最新正式版本查询。

官方结构化输出文档中关于 fallback 的笼统说明，与安装源码对显式策略的处理需区分：本计划遵循安装源码，不承诺显式 ProviderStrategy 在 HTTP 400 后自动降级。

OpenAI 官方文档在前两轮尝试访问时返回 403；不以未读取的文档证明当前网关可用性。事故的 HTTP 400 与本地 SDK 证据已经支持协议修复方向，真实端点证据必须在批准后补齐。
