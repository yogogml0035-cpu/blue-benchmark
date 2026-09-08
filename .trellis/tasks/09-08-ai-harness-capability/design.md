# C1 设计：隔离能力验证

共享技术背景见父 [design](../09-08-ai-harness-contract/design.md) 与 [SDK 研究](../09-08-ai-harness-contract/research/sdk-and-harness-findings.md)。本子任务不实施父设计第 2–7 节的生产变更。

## 探针边界

新增 `backend/scripts/probe_ai_harness_capability.py`，只作为命令行验收程序；生产 `app` 不导入它，`make start-all` 不调用它。探针内构造原生 `ChatOpenAI` Responses 模型，传给现有 `DeepAgentRubricGenerator(model=..., identity=..., session_factory=...)`。复用当前生产 Prompt、材料文件封装、图装配、权限、完整结果 schema、引用校验和有限纠正，不再写一个简化 Agent 或另一套 SDK 协议适配器。

局部模型构造显式包含现有端点必要 HTTP 配置，禁止复制 `_generate`、流式解析或消息转换。它只用于在生产尚未切换时检验候选协议；C2 接管探针后必须删除这段局部构造，改用统一生产合同。

## 资源和执行

- 默认 dry-run；`--execute` 才创建本次隔离运行线程和调用真实模型。协议固定为本能力门的 Responses，不提供“遇错切 Chat/none”选项。
- 使用任务独占 PostgreSQL 检查点资源。复用现有 saver/session 原语，显式准备并核查目标库；当前项目两库、系统库一律拒绝，不为方便绕过保护。
- 模型配置从本地 gitignored Settings 读取；不输出 key 或 URL，endpoint 用 fingerprint 标识。不给每题写入真实业务库，不登记正式队列作业。
- 读取已有授权样本、hash 门禁重建本题材料；不得从事故 checkpoint 抽取正文。合成样本只用于离线防护测试，不能替代真实材料能力门。
- 本轮调用数、工具数、时长有明确上限；公开 sink 只采集允许的内容/计数，报告不保存正文。

## 恢复验证

1. 在执行子进程运行生产生成器，观测实际材料工具结束与同步 checkpoint 已完成。
2. 中断本探针自己的执行子进程；保留同一 thread、模型、协议、effort、schema 和预算。
3. 新子进程/连接/saver 从该 checkpoint 恢复，确认 inputs=None、初始输入只有一次、工具历史完整，最终结果通过既有校验。
4. 完成后重建 generator/session 读取同一结果，确认不再发模型请求；这只证明运行原语恢复，真实业务 CAS/Worker 恢复仍由 C2 验收。
5. 最后仅清理本探针线程并检查零残留，清理不调用模型。

## 证据与失败

报告关联源码 SHA、SDK 版本、配置/端点 fingerprint、样本 hash、每阶段计数/时长和明确 PASS/FAIL。若 SDK、模型或端点能力与研究预期不一致，记录经过白名单处理的失败类别，停止进入 C2；不修改生产代码以绕过能力门，也不改结果合同。

对外能力结论是当前配置下的经验验证，不是服务端承诺或全模型通用规则。C2 仍须用最终生产装配再验一次。
