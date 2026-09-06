# C2 完成证据（Deep Agents 持久运行基础）

日期：2026-09-06。执行 worktree：/Users/hsikey/Company/skill-eval-platform-wt/m0-rubric-deep-runtime（分支 codex/m0-rubric-deep-runtime，基线 main@f777492）。

## 版本锁定（实施当日实时核查）

- deepagents == 0.7.13（PyPI 实时核查：最新正式版，2026-09-02 上传，无 yank）
- langgraph-checkpoint-postgres == 3.1.2（PyPI 最新）
- 传递依赖：langgraph 1.2.11、langchain 1.4.0、langchain-core 1.6.1、psycopg 3.3.4、psycopg-pool 3.3.1、pycryptodome 3.23.0（新增，加密 serializer 所需）
- `backend/tests/test_deep_runtime.py::test_locked_sdk_versions_match_verified` 使版本漂移在 CI 直接失败。

## 实际 API 核查结论（0.7.13 / langgraph 1.2.11，非文档转述）

- `create_deep_agent(model, tools, system_prompt, middleware, backend, permissions, checkpointer, response_format, context_schema, ...)`；无 `harness_profile` 参数，profile 走 `register_harness_profile(key, HarnessProfile(...))` 全局注册，键为 `provider:model`（对预构建模型按 get_model_provider/get_model_identifier 派生，本实现同时注册 identity 键与模型派生键防止派生偏差）。
- `StateBackend()` 无参构造；文件存于图状态 `files` 通道，经 `invoke/stream({"files": {...}})` 预填充；线程内持久，跨线程隔离。
- 默认工具含 `execute`（shell）与 `task`（子代理委派）。硬禁用方式：HarnessProfile `excluded_tools={"execute","task"}` + `GeneralPurposeSubagentProfile(enabled=False)`。实证：`task` 从执行器彻底消失；`execute` 保留在执行器但对模型不可见（bind_tools 层验证）且调用边界直接拒绝（幻觉调用得到 error ToolMessage，未执行）——测试覆盖两层。
- `FilesystemPermission(paths, operations, mode)` 按声明序首条命中；`/materials/**` 写拒绝+读允许、`/workspace/**` 读写允许已实证（篡改材料的 write_file 得到 error，材料不变）。
- 同步流式：`stream_events(version="v3")` 在 langgraph 1.2.11 标记 experimental/beta 且返回 caller-driven GraphRunStream；v1/v2 仅异步。**选定唯一生产路径为同步 `stream(stream_mode=["messages","updates","custom"], durability="sync")`**，不维护第二条流式路径；v3 形状已实验性核查（extensions=values/messages/lifecycle/subgraphs/tool_calls/subagents）留作证据。
- `PostgresSaver(conn, serde=EncryptedSerializer.from_pycryptodome_aes(key=...))`；`setup()/get_tuple/put/put_writes/delete_thread` 齐备；blob type 带 `+aes` 加密标记。
- `interrupt()` / `Command(resume=...)` 协议在 PG saver 上验证通过（暂停→“重启”→回复→续跑，初始输入不重复）。

## 交付组件（backend/app/lib/ai_runtime/deep_runtime.py）

- 受限装配：`build_restricted_agent`（无 store、无子代理、无 shell、StateBackend、材料只读权限、观测 middleware、可选 response_format/context_schema）。
- 公开事件归一：`normalize_stream_chunk`（messages→message_delta，私有 reasoning/thinking 块与 relay reasoning_content 丢弃；updates→stage；custom→stage 文本）；工具边界事件由 `ObservationMiddleware.wrap_tool_call` 发出（完整请求可见，参数只出白名单定位字段，截断 160 字符）；`PublicEvent`/`ProgressSink`/`ListSink`。
- 预算：`RuntimeBudget`（模型调用/工具调用/时长上限）+ `BudgetCounters`（每运行实例，不共享 self 状态）→ `BudgetExceededError`。
- 检查点会话：`open_session/open_checkpoint_session`（专属连接、显式 setup、EncryptedSerializer、fail-closed 配置校验）；`CheckpointSession` 同连接持有线程级 advisory lock（`pg_try_advisory_lock`），锁与 saver 共享同一物理连接，连接断开锁即释放（旧写者无法换连接续写）。
- 恢复语义：`classify_thread_state`（new/incomplete/complete）；`run_streaming` 对已有检查点的线程**拒绝重复提交初始输入**（THREAD_INPUT_CONFLICT），续跑用 `inputs=None` 或 `Command(resume=...)`；`inspect_interrupt` 投影等待状态；中断不发 run_completed。
- 无模型清理：`delete_thread_data`（delete_thread + checkpoints/writes/blobs 三表残留核验，残留即报错可重试）；`thread_data_residue` 查询原语。
- 设置接入：`Settings.checkpoint_database_url` / `Settings.langgraph_aes_key`（消费既有 .env 变量，SecretStr，不输出）；`.env.example` 补齐两项及准备说明。
- `build_runtime_model(streaming=True)` 显式流式参数（默认 False，现有调用方零变化）。

## 测试

- `backend/tests/test_deep_runtime.py`：13 个 stub 合同测试（版本锁、受限装配、排除工具调用边界拒绝、材料只读、工作区持久、事件归一与私有内容过滤、预算、锁键、配置 fail-closed）。
- `backend/tests/test_deep_runtime_postgres.py`：9 个 PG 测试，跑在同 Docker 实例的**本任务独占库 `skill_eval_c2_runtime_test`**（owner=skill_eval_checkpoint；建库命令记录于 fixture docstring）。覆盖：重启恢复不重复输入+新输入冲突拒绝、密文入库（明文标记零命中、+aes 类型标记）、同线程第二写者拒绝、连接崩溃锁自动释放、删除覆盖三表且不影响兄弟线程、清理不需要模型 Provider、清理幂等、interrupt/resume 协议、跨线程隔离。项目两库 skill_eval / skill_eval_checkpoint 未被 reset/setup/写入。
- 全量：backend 138 passed（含既有 110 与新增 22+探针无关项），frontend 70 passed。

## 真实 Provider 探针（scripts/probe_deep_runtime.py）

- 输入：C1 已合入 main 的 `scripts.m0_samples` 现场重建的真实 MEGA 新闻稿 case 六材料（6 文件 30,989 字符，不用占位/编造样本）。
- 模型：真实 relay（provider=openai，fingerprint=bbcc4d985ea811d5，streaming=True）。目标库：skill_eval_c2_runtime_test（探针线程 probe-deep-runtime-m0，跑前清理）。
- 结果（2026-09-06，审查修复后重跑，EXIT=0，全部门禁通过；完整证据 storage/acceptance/m0-deep-runtime-probe/probe-evidence.json，私有）：
  - 受限装配：模型 bind_tools 实际收到列表无 execute、无 task（bind spy + assert 兜底）；执行器注册表无 task。
  - 真实流式：475 个公开 message_delta，首个工具事件 3,971ms、首个增量 22,588ms、末个增量 31,039ms / 总时长 31,238ms——增量在运行中到达且晚于首个工具调用，非结束后一次性爆发；内部元数据过滤生效后公开字符数（811）只含主模型公开文本。
  - 真实工具：9 次工具调用（材料 ls/read/grep），结构化 ProbeResult 返回 4 条探针维度、6 个已读文件申报。
  - 预算：4 次模型调用 / 9 次工具调用（上限 14/60），未触顶。
  - 持久化与加密：checkpoints 11 行、blobs 8 行，明文标记泄露 0，cipher 类型 msgpack+aes。
  - 重启恢复：新连接/新 saver/新 agent classify=complete，55ms 读回全部状态与结构化结果，0 次模型调用。
  - 无模型清理：delete_thread_data（持锁）后三表残留全部为 0。
  - 目标库防线：探针连接后强制 current_database()==skill_eval_c2_runtime_test。

## 边界声明

- 本任务未接入生产评分入口：`ModelRubricGenerator`、Worker 初始化、题目 API、前端均未改变；新组件只有底层接口与显式测试/探针入口，无第二个生产路径或兼容开关。
- 探针使用测试 schema（ProbeResult），不接收/保存正式评分项；生产合同与业务回放证明归 C3/C4。
- M1 中断协议已在隔离 runtime 验证，但未发布任何询问工具、聊天或评分入口。

## 对抗式审查

双审查代理（运行原语正确性 + 边界/生产安全）结论：无 Critical；核心安全主张（材料只读、工具排除双层、加密落库、锁随连接死亡、恢复不重复输入）全部经独立实证成立；项目库 skill_eval_checkpoint 只读核查 4,415 行未动、零测试线程。发现并已在合入前修复：

- 正确性-M1：连接死亡后 `release_lock`/`close` 抛 OperationalError 掩盖原始运行错误 → release/close 对已死连接静默（PG 断连自动释放锁，已实证），原始异常保持传播。
- 正确性-M2：`run_streaming`/`delete_thread_data` 不强制 `lock_held`，单写者只是约定 → 两个入口增加 THREAD_LOCK_REQUIRED 机械守卫；`delete_thread_data` 改为接收 session（清理也是写者，必须持锁），全部调用点同步更新。
- 正确性-M3：messages 通道丢弃 metadata，无法区分主模型与 middleware 内部调用（如摘要模型 token 会混入公开增量）→ 核查 langchain 1.4.0 实际机制：内部调用带 `lc_internal_call`/`lc_source=summarization` 元数据；`normalize_stream_chunk` 按元数据过滤内部调用与非 model 节点，新增定向测试。
- 正确性-M4：PG 测试不可达时静默 skip 仍报绿 → 新增 `RUNTIME_PG_REQUIRED=1` 硬门禁（skip 变 fail）；C2 验收命令必须带该变量执行并留存输出。
- 边界-M1：探针对 `RUNTIME_CHECKPOINT_TEST_DSN` override 缺库名断言，误配可对项目库执行 setup/delete → 探针连接后强制 `current_database() == skill_eval_c2_runtime_test`，否则 PROBE=FAIL 退出。
- Minor 修复：materials_files 段级拒绝反斜杠/`.`/`..`；profile 注册仅精确键（无 identifier 的测试 fake 才回退裸 provider 键并注释说明全局副作用）；预算测试拆分为确定性步骤并新增“预算中止后 incomplete + 盲目续跑再撞预算”PG 用例；加密测试固化为三表全列双标记扫描；测试 `_open` acquire 失败路径关闭连接；探针 TimedSink 与 total 计时统一 t0；pyproject 显式声明 langchain==1.4.0、langgraph==1.2.11（原为传递依赖）；task.json 行尾换行修复。
- 已知边界（如实记录，不伪装已解决）：墙钟预算只在调用边界检查，单次超长模型调用可超出时长上限（依赖 provider request timeout 兜底）；custom 通道 160 字符截断可能切断敏感词，C3 需在合并文本上复扫；探针 bind spy 依赖 pydantic 实例字典遮蔽（有 assert bind_log 兜底，失效即响亮失败）。

修复后：stub+PG 27 passed（RUNTIME_PG_REQUIRED=1，0 skip），真实探针重跑通过（证据见下）。

## 质量门与合并

- `git diff --check`：通过（DIFFCHECK=0）。
- `make test`：backend 138 passed + frontend 70 passed，TEST_EXIT=0。
- `make build`：frontend 生产构建成功，BUILD_EXIT=0。
- 改动文件清单（全部在 C2 边界内）：backend/app/lib/ai_runtime/{model.py(streaming 参数),deep_runtime.py(新增)}、backend/app/lib/settings.py（checkpoint 两字段）、backend/pyproject.toml + uv.lock（精确锁定新依赖）、backend/scripts/probe_deep_runtime.py、backend/tests/test_deep_runtime{,_postgres}.py、.env.example、.trellis/spec/backend/core/{structure-and-boundaries,stub-state-and-contracts}.md、本任务文档。features/、worker、router、前端、迁移零改动。
- 审查修复后最终门禁：`git diff --check` ✓；`RUNTIME_PG_REQUIRED=1` 下 27 passed / 0 skip；`make test` backend 143 passed + frontend 70 passed（TEST_EXIT=0）；`make build` ✓（BUILD_EXIT=0）。
- 提交 SHA：cdf7aee（feat(ai-runtime): durable deep-agent runtime primitives (deepagents 0.7.13)），基线 main@f777492。
- 合并：主工作区 `git merge --ff-only codex/m0-rubric-deep-runtime`，`git log main..codex/m0-rubric-deep-runtime` 为空。
- main 复验（合并后主工作区执行）：`git diff --check` ✓、`make test` 143+70 passed（TEST_EXIT=0）、`make build` ✓（BUILD_EXIT=0）。
