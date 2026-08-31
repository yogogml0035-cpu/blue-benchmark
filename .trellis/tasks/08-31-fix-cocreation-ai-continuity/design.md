# 技术设计：共创阶段连续性与 Worker 运行模式隔离

## 1. 问题定义与现状

当前用户路径是：

    场景标准 session
      -> 老师回答两轮固定问题
      -> 确认合同
      -> 前端自动启动 task_judgment session
      -> 新 session 没有收到合同，只拿到同一批文件
      -> Fake adapter 对两种 kind 返回同一套固定问题

这条路径的“先场景、后单题”顺序符合 M0 的两层模型，但缺少跨层上下文，所以表现为重复问答。当前机器还同时运行一个 AI_RUNTIME_MODE=fake Worker 和一个生产 Worker；OperationJob 有任务级 lease，却没有长驻 Worker 级互斥，因此 Fake 结果确实可能进入业务投影。

## 2. 目标边界

### 业务事实所有者

- FastAPI Service/Repository：场景合同、TaskPackage、老师回答、业务 revision、确认和下一步状态。
- OperationJob：排队、lease、attempt、幂等和陈旧结果隔离。
- DeepAgent adapter：受限证据理解、语义缺口识别、一个问题或结构化候选；不确认业务事实。
- Checkpointer：仅保存 standard_cocreator 的短期 Graph 连续性；Service 保存并校验 accepted pointer。
- Fake adapter：只用于测试/显式 Fake 运行，不作为真实 AI 证据。

### 不改变的产品语义

仍然保留：场景标准确认 -> 本题判定依据共创 -> 老师定稿。改变的是题级共创的输入和问题所有权：共享边界从已确认合同继承，题级 AI 只补充本题特有的参考结果、错误、最低质量线和证据。

## 3. 方案

### 3.1 可信合同上下文

在 cocreation_service._run_cocreation_agent 中，针对 task_judgment：

1. 从 package.contract_revision_id 读取合同记录；必须是已确认状态。
2. 校验 session 的合同 ID 与 TaskPackage 当前合同 ID 相同；否则把任务标记为陈旧，不让旧会话覆盖新合同。
3. 将已通过 Pydantic 校验的合同字典作为 adapter 的显式可选参数传给 start/resume/reproject。它不进入浏览器 DTO，也不写入运行时 context 的秘密字段。
4. DeepAgent 首轮消息用明确的“不可信业务材料”边界包住合同 JSON，说明合同是继承标准；resume/reproject 每次重新提供同一业务快照，避免依赖“runtime context 会自动进入模型 prompt”的错误假设。

StandardCoCreator Protocol 的扩展保持向后兼容：shared_contract: dict[str, Any] | None = None。场景合同阶段传 None；题级阶段必须传合同。合同本身的 evidence_refs 仍由现有 Adapter/Service canonical 校验。

题级候选的 hard_gates 必须逐字保留合同 hard_gates；AI 可以增加更严格的题级门禁，但不能删除或改写共享门禁。Repository 在候选投影和老师确认两处都做防御性校验。

### 3.2 Fake adapter 的行为替身

Fake 仍然是确定性的测试替身，但按业务阶段提供不同的最小行为：

- scenario_contract：询问共享任务边界和共享硬门禁。
- task_judgment 且有合同：说明共享标准已继承，只询问本题特有的判定依据；完成结果的题级规则保留合同硬门禁的语义，不重新生成一份场景标准。

测试断言必须检查“题级问题不同于场景问题”以及“合同已传入 adapter”，而不是只断言状态变为成功。

### 3.3 长驻 Worker 单消费者互斥

新增极小的 runtime guard，按业务数据库身份持有一个进程级锁：

- PostgreSQL：使用同一业务库连接上的 session-level advisory lock；连接在 Worker 长驻期间保持，退出时自动释放。锁 key 是固定 namespace 的稳定整数，不包含密钥/DSN。
- SQLite/run_once()：开发环境使用同库文件的 fcntl 锁，保留测试直接调用 run_once() 的合同；生产长驻 Worker 仍要求 PostgreSQL，其他数据库由 guard fail closed。
- run_forever() 在进入消费循环前取得 guard；无法取得时立即抛出安全的 Worker 启动错误，不能进入 claim_next。
- 生产 --once 也应经过同一 guard，避免手工一次性 Worker 与常驻 Worker 争抢；测试直接调用 run_once() 不受影响。
- Fake Worker 只允许连接 SQLite 业务库；即使环境变量显式设为 fake，也不能把测试替身接到 PostgreSQL 业务队列。

不使用文件锁作为唯一边界：不同容器/服务器的文件系统可能不共享。任务级 lease 仍保留，用于 Worker 崩溃后的恢复；Worker 级锁只解决“多个活着的消费者/模式混用”。

## 4. 数据流

    confirmed TaskPackage + confirmed ContractRevision
      -> Service 校验归属 / revision / contract id
      -> OperationJob 记录 accepted checkpoint
      -> StandardCoCreator(adapter)
           -> DeepAgent(model + ToolStrategy + read-only EvidenceBackend)
           -> one ask_teacher OR complete candidate
      -> Adapter canonical evidence validation
      -> Repository revision CAS + accepted checkpoint advance
      -> UI receives only CoCreationSessionView

前端继续使用服务端返回的 kind/status/next_action。只增加一句业务解释“本题沿用已确认的场景标准，仅补充本题判定依据”，不新增客户端状态机和本地 AI 判断。

## 5. 失败与恢复

- 合同不存在、未确认或 session 使用旧合同：不调用模型，业务操作失败/标记陈旧；不返回新的题级候选。
- Worker 锁被占用：第二个进程在 claim 前失败；不会把另一个模式的结果标成 AI 失败，也不会改写业务数据。
- 模型失败：沿用现有 failed/retry；retry 从 accepted Checkpoint 继续。
- Checkpoint 已产生但投影失败：沿用 projection_pending/reproject，不重新调用模型。
- 已存在的 Fake 历史 session：不静默把 Fake 结果改成生产结果；用户通过显式 continuity reset 或重新开始获得新 session，旧 turn 保留为形成记录。

## 6. 对抗审查重点

- 权限：合同和 TaskPackage 必须属于同一 workspace；模型只能读当前任务证据，合同不改变 EvidenceBackend scope。
- 并发：合同更新、重复 start、重复 answer、两个 Worker、lease reclaim 都不能覆盖 accepted pointer。
- 幂等：同一 command 同一 payload 返回原投影；不同 payload/跨 session 复用仍返回 409。
- 恢复：restart/reproject 不使用 thread latest；每次重新传 context 和合同。
- 泄漏：合同/教师回答只进入受限模型上下文和业务投影，不进入公开 DTO、runtime 版本分区或错误日志。
- 旧数据：旧 session 的 contract_revision_id 缺失或已过期时 fail closed，不猜测合同。
- 存储完整性：不新增文件复制或版本包路径；确认/冻结仍依赖现有 ready marker、Manifest 和 hash 门。
