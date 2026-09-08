# C1 能力验证报告：当前网关的 Responses Harness 完整能力

日期：2026-09-08。结论：**PASS**。本报告只含脱敏事实（版本、指纹、hash、计数、时序、安全错误类别）；私有原始产物（证据 JSON、重建样本）仅存于本任务 gitignored `backend/storage/acceptance/c1-capability/`，不进 Git。

## 1. 结论摘要

当前生产配置组合（`openai / gpt-5.6-luna / medium`，当前中继端点）在 **Responses 协议**下，经现有生产 `DeepAgentRubricGenerator` 完整装配，能够：

| 能力 | 结果 | 证据 |
|---|---|---|
| 真实材料工具往返 | ✅ | full_run 发生 11 次工具调用（1×ls + 10×read_file），全部 finished |
| 完整评分项生成（生产 schema） | ✅ | full_run 返回 4 维度/16 锚点/21 引用，全部通过现有确定性校验（含逐字引用审计） |
| 原生结构化输出 | ✅ | 每次请求 `text.format.type=json_schema`，无强制 `tool_choice` |
| 思考强度保留 | ✅ | 每次请求 `reasoning.effort=medium`；协议切换未降级思考 |
| 公开流式反馈 | ✅ | full_run 3470 个 message_delta；工具轮后仍持续有增量（last_delta 459610ms > first_tool 314947ms） |
| 客户端持有历史（无服务端会话） | ✅ | 全部请求 `store=false`、`previous_response_id=null`、`include=["reasoning.encrypted_content"]`；多轮请求 input 含 `reasoning`/`function_call`/`function_call_output` 项 |
| 工具轮后硬中断 → 检查点恢复 | ✅ | 执行子进程在第 1 个工具轮后的模型调用起点 `os._exit(42)`；新进程/新连接/新 saver 以 `inputs=None` 续跑至完成 |
| 恢复不重复初始输入 | ✅ | 恢复完成后检查点消息 15 条，初始输入恰好 1 次，工具消息 11 条；恢复后首个请求携带完整 `function_call_output` 历史 |
| 完成态重读零模型调用 | ✅ | reread 阶段 `thread_state_complete`，0 个 HTTP 请求、0 delta，重新读出同一结果（7757 chars）并通过全部校验 |
| 无模型清理零残留 | ✅ | checkpoints/checkpoint_writes/checkpoint_blobs 全部归零（预清理、full_run 后、最终清理三次验证） |
| 受限工具边界 | ✅ | 每次请求工具集合恒为 7 个文件工具；`execute`/`task` 从未出现在任何请求 |

## 2. 运行身份

| 项 | 值 |
|---|---|
| 源码 SHA（PASS 运行） | `13e312190d08f98163b95e9871215794f4270652`（codex/ai-harness-capability） |
| 模型 | `openai / gpt-5.6-luna`，endpoint fingerprint `a36425030c24a7c4` |
| 协议 / 参数 | Responses（`/v1/responses`）、`reasoning.effort=medium`、`store=false`、`include=["reasoning.encrypted_content"]`、`use_previous_response_id=false`、stream=true |
| SDK | deepagents 0.7.13、langchain 1.4.0、langchain-core 1.6.1、langchain-openai 1.6.0、langgraph 1.2.11、langgraph-checkpoint-postgres 3.1.2、openai 3.6.0、psycopg 3.3.4 |
| 检查点库 | `blue_benchmark_c1_capability`（任务独占；连接后 `current_database()` 复核） |
| 样本 | `m0-real-m-mega-press-release`，case sha256 `5f7e87d5…4427eb`，语料 6 源 hash 门禁通过，6 材料文件 |
| 预算 | max_model_calls=24 / max_tool_calls=120 / max_total_seconds=1800 / max_stage_attempts=3（中断与恢复进程同一预算） |
| 线程 | `c1-capability-probe` |

## 3. PASS 运行阶段计数（2026-09-08T05:18Z 起）

| 阶段 | attempts | 关键计数 |
|---|---|---|
| full_run | 1 | 总时长 476194ms；HTTP 请求全部 `/v1/responses`；工具 11 起 11 成；delta 3470 个/6842 字符；结果 4 维度通过完整校验 |
| run-child（中断） | 1 | 第 1 个工具轮后的首个 `model_call_started` 处 `os._exit(42)`，检查点已含工具轮（durability=sync） |
| resume | 1 | 总时长 178449ms；`run_resumed/thread_state_incomplete`；首请求 input 含 reasoning+function_call+function_call_output；再发生 10 次工具调用；完成并产出 5 维度/20 锚点/15 引用 |
| reread | 1 | 0 请求、0 delta、0 工具；`thread_state_complete`；结果与 resume 一致 |
| cleanup | — | 三处清理均零残留 |

## 4. 过程事实与对 C2 的输入

PASS 之前的三轮真实运行观测（同一目标组合，均已脱敏）：

1. **第 1 轮**：full_run PASS、中断 exit 42 按计划触发；resume 阶段发生一次瞬时失败（见下），单独重跑 `--stage resume` 后从同一检查点（16 消息、next=model）续跑成功并产出合法结果——本身即是一次真实的“瞬时失败后同检查点续跑”观测。
2. **第 2 轮**：full_run PASS（约 25 分钟）；resume 阶段失败，安全诊断为 `AI_CALL_FAILED`（retryable=True），cause 类型 `StructuredOutputValidationError`。
3. **第 3 轮**：暴露探针编排缺陷（阶段函数未绑定 config 的 TypeError），已修复并补编排层离线测试；非网关能力问题。
4. **第 4 轮（PASS 证据）**：全序列各阶段一次通过，无瞬时重试（full_run_attempts=1、resume_attempts=1）。

**关键发现（C2 必须处理）**：`ProviderStrategy`（原生 json_schema）下，模型采样出的最终结构化输出若违反 `RubricGenerationResult` 的跨字段 pydantic 校验（如锚点唯一性、teacher_explicit 必带引用——这些规则无法表达进 wire JSON Schema），langchain 在 `factory.py::_handle_model_outputs` 抛 `StructuredOutputValidationError` 且 **无 run 内重试**（重试路径只存在于 ToolStrategy）。当前适配器把它包装为 `AI_CALL_FAILED retryable=True`，生产语义 = Worker 下一个 attempt 从检查点续跑重新采样，实测可恢复。C2 的错误分类必须保留该瞬时语义（它是内容采样问题，不是协议/配置错误），且不得让 Prompt 纠正路径假装能修复它。

**时序特征（验收预期管理）**：medium 思考下首个模型调用可长时间无公开文本（本轮 full_run 首个 delta 在 342890ms，首个工具在 314947ms）；最终结构化输出单次流式调用可长达约 8-20 分钟。`request_timeout=180` 不会截断持续有分片的流。L02-L04 真实验收的超时与预算设置必须容纳该时序。

## 5. 可复跑命令

```bash
# 默认 dry-run：脱敏预检，零网络、零数据库
(cd backend && uv run python -m scripts.probe_ai_harness_capability)

# 真实能力门（需实施批准；隔离库名必须含 c1_capability）
C1_CHECKPOINT_DSN=postgresql://<user>@127.0.0.1:5432/blue_benchmark_c1_capability \
(cd backend && uv run python -m scripts.probe_ai_harness_capability --execute)

# 单阶段复跑（诊断用）：--stage full-run|run-child|resume|reread|cleanup
```

凭证实值一律经 gitignored `.env` / 进程环境注入，不进命令行、报告或 Git。

## 6. 未覆盖项（归 C2/父任务）

- 本报告证明的是**运行原语层**能力（L01 + 工具轮后原语恢复）：生产 Worker 的 attempt/lease/fencing、业务 CAS 提交、SSE 回放、Web 完整链、合同指纹切换与 main 复验（L02-L05、P/T 矩阵）由 C2 在最终生产装配下验收。
- 探针的候选模型构造是 C1 局部产物；C2 接管后必须删除并改用统一生产合同。
- Chat Completions 显式模式与 Anthropic 的现行能力未被本轮触碰，也未被本报告背书或否定。
- 结论仅对当前模型/端点/参数/SDK 版本组合有效；任何一项变化都使本证据失效，须复跑能力门。

## 7. C1 验收清单自评

| 项 | 状态 |
|---|---|
| C1-AC1 dry-run 零请求、隔离资源门禁、离线断网测试 | ✅（40 项离线测试，socket 级阻断） |
| C1-AC2 Responses+medium+文件工具+native schema 真实往返与完整生成 | ✅ |
| C1-AC3 运行中公开增量；推理/加密块、原始正文、凭证不入报告与公开事件 | ✅（事件级敏感标记门禁 + 证据级密钥值门禁） |
| C1-AC4 工具轮后换进程恢复、初始输入不重复、完成态重读零模型调用、合同一致 | ✅ |
| C1-AC5 可复跑脚本、离线回归、安全报告、分支与 main 质量门 | 本报告 + 待 main 复验 |
| C1-AC6 backend/app、生产默认配置与主环境零变更 | ✅（交付仅 scripts/tests/任务材料） |
