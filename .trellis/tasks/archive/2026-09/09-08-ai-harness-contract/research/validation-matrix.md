# 分层验证与防止验收失真

本表是实施后的验收要求。当前只有事故只读诊断与 SDK 离线请求构造证据；下表各项尚未执行，不能标为通过。

任务归属：C1 独立交付 L01 及其工具轮后原语恢复证据；C2 消费 C1 后负责 T01–T13、P01–P05、L01–L05 的最终生产验证。C1 的通过不能替代 C2 Worker/业务/main 的最终证据，映射见父 `task-map.md`。

## A. 离线合同层

离线测试使用合成输入、占位凭证、MockTransport/等价受控客户端，并禁止 socket 外连。应走实际 `create_deep_agent` 装配和 SDK 序列化，不用测试替身自己拼出预期请求。

| ID | 输入/故障 | 必须证明 | PRD |
|---|---|---|---|
| T01 | Responses + Luna + medium + 当前完整 schema/工具 | 请求为 /responses，reasoning.effort 保持 medium，input/text.format/tools 为原生形状，execute/task 不出现 | AC1、AC2 |
| T02 | 显式 Chat 模式与现行 Anthropic 模式 | 各自发送正确协议形状，Responses 字段不泄入其它协议；空 effort 与 none 不混同 | AC2、AC7 |
| T03 | 不同思考值/非法枚举/互斥参数 | 只能证明合法配置和传参；不得把 SDK 接受的所有档位宣称为当前模型/网关均支持 | AC2 |
| T04 | 同步 invoke、流式 Agent、摘要/内部模型调用 | 均经过原生协议分发；不存在遗留 Chat-only _generate 路径 | AC2 |
| T05 | 真实形状的 Responses 工具轮与后续请求 | call_id/tool result 对应，opaque reasoning 数据往返；不依赖 previous_response_id 或服务端存储 | AC1、AC5 |
| T06 | 流式分片、reasoning、加密块、完成/不完整/拒绝输出 | 正确构造内部消息；公开流不泄露内部块，不完整/拒绝不冒充成功 | AC4、AC6 |
| T07 | 当前事故的 HTTP 400 | 实际 Worker 收到标准不可重试异常，attempts=1、作业 failed、题目 generation_failed、材料不变、失败事件存在 | AC3 |
| T08 | 401/403/404；429/5xx/连接/超时 | 确定性错误不重发；瞬时错误保留既有有限重试，没有新增第三层重试；显式用户重试不被禁用 | AC3、AC4 |
| T09 | 无效 schema 内容、引用失配、预算耗尽、中断/取消/未知异常 | 原有有限纠正有效；错误分类和控制流不被通用 catch 改写；禁止人工塞结果 | AC4 |
| T10 | 仅改变协议、思考强度、schema、Harness 策略或相关 SDK 版本 | 合同 fingerprint 随语义变化；同配置跨进程稳定；密钥轮换/日志路径/PID 不污染指纹 | AC5 |
| T11 | 注入测试模型与不同全局 Settings | 实际运行与登记指纹一致，不能用 settings 替注入模型伪造运行身份 | AC2、AC5 |
| T12 | 把凭证/材料哨兵放在 provider 原始消息、headers 和异常 cause | 日志、last_error、SSE 均无哨兵；诊断可关联作业且有安全类别/status/param | AC6 |
| T13 | 在 checkpoint 登记前配置解析失败 | 零模型请求，不残留永久 generating，失败终态/事件可查询；模型不可用清理仍可运行 | AC3、AC7 |

不要只 patch `httpx.Client.send` 后假定已禁网：当前安装 SDK 还可能使用其它 HTTP 客户端。T05/T06 要使用足以经过 SDK 解析和 Agent 下一轮构造的响应事件，不用裸字典替代最终框架消息。

## B. 本地持久化与业务层

| ID | 场景 | 必须证明 | PRD |
|---|---|---|---|
| P01 | 工具轮后 Worker 中断、同合同恢复 | 真实 PostgreSQL checkpoint 包含工具消息/工作文件，重启后 inputs=None，初始输入不重复 | AC5 |
| P02 | graph 已完成、CAS 提交前中断 | 重新读取结果后一次提交，模型调用计数不增加 | AC5、AC7 |
| P03 | Chat→Responses 或 medium→其它值 | 命中已有不兼容清理/重建，清理失败不得继续写新状态；不做旧消息迁移/双指纹兜底 | AC5 |
| P04 | 清理、权限、跨题读取、旧任务提交、lease 失效 | 原有限制与 fencing 生效；损坏模型配置不影响删除清理 | AC7 |
| P05 | 流式中浏览器断线重连 | SSE 按 cursor 回放，事件顺序稳定；graph 完成前/业务提交前都不发业务成功 | AC6、AC7 |

普通 API 回归允许独立 SQLite；checkpoint 集成用真实隔离 PostgreSQL。只有下一层的真实双库验收才能证明生产业务库和 checkpoint 库组合。`RUNTIME_PG_REQUIRED=1` 下持久化测试不允许跳过。

故障注入须保留恢复前后的实际合同：当前部分旧测试用 `max_model_calls=1` 制造中断后再恢复到 24，新合同纳入预算后这会变成“合同变化重建”而非同合同恢复。实施应改为工具轮后进程中断/受控故障注入，不通过改变预算或伪造 fingerprint 冒充恢复证据。

## C. 当前网关的真实组合门

| ID | 场景 | 必须证明 | PRD |
|---|---|---|---|
| L01 实施先验 | 同模型/端点、Responses、medium、native schema、文件工具、store=false | 至少一轮实际材料工具读取与结果回送；完整 schema 返回；opaque 历史可继续；请求摘要证明未关思考/删工具/切模型 | AC1、AC2 |
| L02 完整生成 | 现有两组 hash 校验真实样本，通过 production Worker 和隔离双 PostgreSQL | 生成当前完整评分项，锚点/双依据/引用规则全部通过，最终业务原子提交 | AC1、AC7 |
| L03 真实恢复 | 实际生成的工具轮后停止本任务 Worker，重启本任务 Worker | 同合同继续完成，无重复初始输入或第二份业务结果；不通过换材料/换 thread 冒充恢复 | AC5 |
| L04 Web | 本任务独立端口的浏览器完整链 | 真实公开过程、结果可审改、重连回放、失败说明及完成事件时机 | AC6、AC7 |
| L05 main 复验 | 任务合并后的 main，记录精确 SHA | 完整质量门和目标组合真实验收再次通过，不能复用分支/旧端口/旧报告的 PASS | AC8 |

L01 通过不等于 L02–L05 通过。SDK 构造成功、模型自述、HTTP 200、端口监听、普通对话、假模型及人工填写评分项都不能替代任何真实组合门。

## 资源与证据

- 真实模型调用只在本版计划得到明确实施批准后进行。
- 所有测试/验收数据库、文件、端口、Worker 属于本任务；禁止使用当前业务两库。现有 PostgreSQL 测试部分使用固定测试库名，需要独占测试实例或确认独占资源，不能与其它 worktree 共用后清空。
- 真实材料从已有授权只读语料目录经 hash 门禁重建到任务 gitignored 目录；不要从事故 checkpoint 导出真实材料作为新 fixture。
- 报告记录 Git SHA、SDK 版本、合同 fingerprint、实际协议/effort/策略、case hash、调用/工具/attempt 计数、事件计数、耗时和验证结果；不记录原始材料、完整模型输出、encrypted_content 或凭证。
- 若网关拒绝 Responses、native schema 或无服务端状态的历史续传，保留安全错误和失败用例，停止切换并返回计划；不得降低 AC1/AC5 来交付。
