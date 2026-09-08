# C2 实施计划：生产原子切换与完整验收

状态：已获实施批准（2026-09-08，覆盖整棵任务树）；开工仍以第 0 节 C1 先决门核查通过为前提。

## 0. 开工门禁

1. 用户明确批准覆盖 C2 的最新父子计划；人工核查 C1 已完成/归档、C1-AC 全通过、脱敏能力报告为 PASS、交付提交已进入当前已验证 main。父子归属与 depends_on 不能替代这个门禁。
2. 核查主工作区和所有 worktree 状态、main/origin/main、当前分支与路径。本轮规划基线为 `f108fe7`，本地 main 比当前远端多 93 个提交；不得顺带推送这些历史提交。
3. 若 main 已前进，在本任务 worktree 集成最新已验证 main，复核事实与冲突；不切换/改动主工作区、不 stash 他人文件。
4. 从已包含父子计划和 C1 交付的 main 创建 `/Users/hsikey/Company/blue-benchmark-wt/ai-harness-cutover`、`codex/ai-harness-cutover`；当前仅为规划，尚未创建。复制 `.env` 后覆盖隔离数据库/输出/端口，禁止把当前业务库地址用于验收；不共享父/C1 工作区的未提交文件。
5. 读取本子任务三文档、父共享 design/research、相关 specs 和 trellis-before-dev；更新实际 branch/worktree 字段后才运行本子任务 `task.py start`，不启动父任务。规划验证 PASS 不替代批准。

规划收尾时只读发现 main 新增 `404029e`（材料模块布局），当前领先远端 94 个提交；已核对它不改变后端模型/Harness/依赖/.env.example，本计划源码定位仍对应 `f108fe7`。本轮没有集成或修改该 UI 提交，实施前按第 3 项重新集成与验证最新 main。

## 1. 消费并复核 C1 能力交付

- 核查 C1 的源码/SDK、模型、端点 fingerprint、medium、schema、store=false 与恢复证据，记录其 main 交付 SHA。
- 在本子任务独占资源复跑 C1 交付的探针作为基线；不启动本项目当前业务库的第二个 Worker。
- 前提变化或能力不再通过时停止生产切换并返回父计划，不自动 none、JSON mode、换模型或启用服务端存储。
- 第 2 阶段生产装配完成后，把 C1 探针改为复用最终生产入口，删除局部候选模型构造，再次跑同一能力门；C1 旧报告不代替最终生产验收。

## 2. 收敛模型与 Harness 装配

1. `settings.py` 增加 OpenAI 专用协议枚举，默认 Responses；思考强度保留空值与 none 的语义区别。
2. `model.py` 使用原生 SDK，按显式协议传参；保留必要 HTTP 配置，删除自定义 Chat-only `_generate` 类。
3. 在现有 `ai_runtime` 内落地不可变合同。`DeepAgentRubricGenerator` 是单一生产装配入口，正常运行/脚本/测试注入都明确传递实际合同。
4. 当前 Responses/Luna 使用明确 ProviderStrategy；其它原有模型按既有能力在装配时解析一次策略，纳入合同。不要新增按错误切策略的旁路。
5. 保留 StateBackend、精确模型 HarnessProfile、权限、同步 stream/durability 和每次运行独立状态；校验最终工具集合，不只测配置字段。
6. 所有 Responses 调用显式使用客户端历史模式；内部消息保留 SDK 所需 reasoning/call_id/tool-result 数据，公开流继续过滤。

## 3. 接入指纹、错误分类和诊断

1. 服务使用实际 generator 的合同 fingerprint；删除服务内独立拼接身份及异常退回 runtime_mode 的实现。更新 RubricGenerator 合同与 durable 测试替身，不保留旧签名兜底。
2. 将合同解析、模型初始化、线程登记及执行失败纳入同一可投影的失败边界；零模型调用的配置失败也必须终结作业、记录公开失败事件。
3. 复用当前锁保护不兼容清理/重建；指纹变化时不跨协议读取/转换旧消息。保留材料变化重建、完成结果重新提交和 model-free cleanup。
4. 生成轮和引用纠正轮统一翻译标准 ModelError，保留 is_retryable；400/401/403/404/配置错误不再消耗第 2/3 个 attempt。未知错误不默认可重试。
5. 保持 Worker 是 retry/lease/终态所有者，不增加模型 fallback 或第二个 retry middleware；原有 schema/引用纠正仍有界。
6. 以标准 logging 和有限轮转文件记录白名单诊断字段；测试错误 cause 含敏感哨兵时所有出口均不泄露。替换后删除 WORKER_DEBUG_TRACEBACK 原文打印分支。

## 4. 验收入口与维护文档同步

- 现有 `smoke_ai_provider.py`、`accept_real_ai_rubric.py` 和 Web 验收复用同一合同；报告增加合同身份与真实请求组合的安全摘要。
- 接管 C1 的 `probe_ai_harness_capability.py` 与测试，将候选模型构造替换为最终生产装配；同任务删除临时构造代码与对应旧测试假设。
- 接通 smoke 已存在但未传入的模型/工具预算选项，并加入预算生效的回归。
- `probe_deep_runtime.py` 仍只是原语验收，不把较小测试 schema 的通过等同于生产完整 schema 通过。
- 同步 `.env.example`、README、后端结构/状态/错误/质量 spec 中相关维护说明。只同步本任务改变的合同，不批量改写归档任务。
- 对外 code/message 形状保持；新增机器码核对现有 API 类型和使用处。若机器合同实际发生变化，必须通过生成命令更新 OpenAPI/前端类型，不能手工修改。

## 5. 质量与真实验收顺序

第 1 阶段复核 C1 后，先 T01–T13，再 P01–P05，再通过最终生产装配复跑 L01–L04。矩阵定义见父 `research/validation-matrix.md`。每次真实运行使用本任务资源和同一目标组合，不用“所有测试大部分通过”掩盖未运行的层级。

现有命令入口：

```bash
git diff --check
make test
make build
(cd backend && RUNTIME_PG_REQUIRED=1 uv run pytest -q tests/test_deep_runtime_postgres.py tests/test_question_runtime_postgres.py)
```

运行前向进程注入本任务独占 PostgreSQL 测试 DSN；当前原语测试会验证固定安全测试库名，必要时在本任务独占 PostgreSQL 实例上使用该库名。不得让并行 worktree 共用会被清空的测试库。

真实双库和 Provider 验收通过环境配置明确绑定本任务的 `ACCEPT_BUSINESS_DSN`、`ACCEPT_CHECKPOINT_DSN`、`SMOKE_CHECKPOINT_DSN` 和语料根目录；凭证通过 gitignored 配置或进程环境注入，不写进命令实值、报告或 Git：

```bash
SMOKE_CORPUS_ROOT=/Users/hsikey/Company/blue-benchmark/.local-samples/m0
(cd backend && uv run python -m scripts.smoke_ai_provider --corpus-root "$SMOKE_CORPUS_ROOT")
(cd backend && uv run python -m scripts.accept_real_ai_rubric --corpus-root "$SMOKE_CORPUS_ROOT")
ACCEPT_CORPUS_ROOT="$SMOKE_CORPUS_ROOT" make accept-web
```

注意：这些入口的现有默认路径/端口/测试库先从实际脚本核对。Web 验收若覆盖不到新增失败诊断，用已有 E2E 增加对应场景；不改 UI 来迎合验收。两组真实样本、工具轮后重启、graph 完成后提交恢复必须分别留证。

## 6. 同任务删除与检索

逐项删除父 design 第 7 节列出的被替代路径，以及 C1 探针的局部候选构造，更新失效测试；保留显式 Chat 模式、现行 Anthropic 能力及无模型清理。不能借此任务删除仍有当前用途的其它入口。

```bash
rg -n 'OpenAICompatibleChatOpenAI|WORKER_DEBUG_TRACEBACK|def runtime_fingerprint|single structured invoke|Force the protocol explicitly' backend README.md .env.example .trellis/spec
rg -n 'use_responses_api|reasoning_effort|reasoning|ProviderStrategy|ToolStrategy|runtime_fingerprint' backend/app backend/tests backend/scripts README.md .env.example .trellis/spec
git diff --check
```

第二条检索会命中现行合法实现，逐项审查，不机械要求零命中。`.trellis/tasks/archive/` 保持历史记录。

## 7. 文件边界与提交批次

| 文件/模块 | 变更理由 |
|---|---|
| `backend/app/lib/settings.py`、`ai_runtime/model.py` | 明确协议与原生模型构造 |
| `backend/app/lib/ai_runtime/contract.py`（新增） | 只承载不可变运行合同与 fingerprint，不新增执行循环 |
| `ai_runtime/deep_runtime.py`、`ai_runtime/adapters.py`、必要导出 | 同一运行合同、装配策略、恢复描述和错误翻译 |
| `question_library/rubric_generation.py` | 实际合同指纹、失败边界、既有恢复流程接入 |
| `operations/worker.py`、`ai_runtime/diagnostics.py`（新增） | 保留错误重试语义，单一安全序列化与 logging，移除 raw traceback |
| `backend/tests/test_ai_runtime_model.py`、`test_deep_runtime*.py`、`test_question_runtime*.py` 及相关测试替身 | 最终 SDK 请求、失败终态、权限与恢复验证 |
| 现有 provider/runtime/API/Web 验收脚本及对应测试 | 同装配入口、真实组合、预算生效和验收摘要 |
| `backend/scripts/probe_ai_harness_capability.py`、对应测试（C1 交付） | 消费 C1 后切回统一生产构造，删除临时模型构造 |
| `.env.example`、README、相关 `.trellis/spec/backend/core/` 文档 | 新默认、诊断、验收与旧合同删除同步 |

按“模型/Harness 合同”“业务接入/诊断”“完整验收与文档”组织提交，若中间提交会留下不可运行状态则合并成同一批次。无关整理、依赖升级或新的公开字段须先回到计划。

## 8. 集成与收尾

- 按根 AGENTS 的 worktree 质量门、串行合并、main 复验执行，先确认 main checkout 的实际占用；若不能在不影响他人工作区的前提下准备 merge worktree，保留任务分支并协调，不强夺已检出的 main。
- main 必须包含任务全部提交；`git log main..codex/ai-harness-cutover` 为空，且同一 main SHA 的完整质量门与目标真实验收通过，才可归档与清理本子任务 worktree/分支。
- 不顺带 push 当前 main 的历史提交。本任务本轮仅规划，不提交、合并、归档或删除工作区。
- 主环境配置切换、现有 Worker 重启、原失败题重试不在自动验收脚本里执行；需要进入该环境时先报告具体目标与影响，遵守已有授权范围。

## 交付给父任务

提交 C2 全部实现、旧路径删除证据、T/P/L 验收矩阵结果、main 精确 SHA 和剩余运维边界。父任务核查 AC1–AC8 全部满足后才可完成；本子任务的 task.py validate 仅证明规划上下文，不是修复验收。
