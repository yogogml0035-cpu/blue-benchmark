# M0 真实 AI E2E 报告

日期：2026-08-31
样本来源：`/Users/hsikey/BenchMark/EvalData`，严格发现 3 份顶层文件；报告不复制正文。

## 证据边界

- 本报告只收录当前 checkout 的真实执行结果、自动化结果和浏览器结果。
- 真实链路使用临时 PostgreSQL 17：业务库与 Checkpointer 库独立，数据库和存储通过本轮进程环境覆盖；未连接远端数据库。
- 本轮真实 Worker 使用 `AI_MAX_COCREATION_QUESTIONS=1` 作为成本受控的边界测试，专门覆盖完成式 fallback；这不是对默认 12 轮提问预算的完整压力基线。
- M0 只验证资料整理、任务/attempt、标准共创、版本冻结和三视图包；不宣称 M2 Skill/Agent 执行、Judge 或评测报告已经实现。

## 真实组件 smoke

| 阶段 | 结果 | 证据 |
|---|---|---|
| Provider ToolStrategy smoke | PASS | `make ai-smoke`；真实 Provider 返回目标 `CoverageReview` 结构，输出仅包含 Provider/模型/结果标记 |
| 业务 PostgreSQL migration/readiness | PASS | 临时 PostgreSQL 17 上显式迁移与 schema check 通过 |
| 加密 Checkpointer setup/read | PASS | 独立 Checkpointer 数据库、AES key、严格 msgpack read/delete 通过；业务资产删除后仍可回查 |
| Worker startup/fail-closed | PASS | production Worker 在 claim 前完成模型、连接、Checkpointer schema 和工具面检查 |

## 当前代码真实 E2E

最终修复后的干净运行输出 `M0_REAL_AI_E2E_STAGE=complete`；在最后补上 operation row 锁定后又从全新临时 PostgreSQL 重新验证一次：

1. 上传 3 份顶层资料，展开后得到 5 个证据文件，批次从 `analyzing` 到 `ready_for_confirmation`。
2. 资料角色/可见性确认通过；老师确认 2 个任务，共 3 个 attempts。
3. 场景标准共创完成；两道题的判定依据共创均完成并由老师确认。每个 session 本轮 1 个问题后进入完成式结构化候选，未把 AI 候选直接当成确认事实。
4. 下一版本草稿加入 2 个任务；覆盖审查进入风险确认，老师明确确认后提交 freeze。
5. v1 版本包生成成功，ZIP 恰好包含 `manifest.json`、`runtime.json`、`judge.json`、`provenance.json`。
6. runner 机械验证通过：Manifest 整体 hash、三个分区的 bytes/hash、Manifest 与 ZIP 身份、runtime allowlist 和 runtime/judge/provenance 隔离均一致。

真实 runner 只打印阶段/计数/错误类型；临时日志扫描未发现凭证、Authorization、private reasoning 或样本正文输出。

## 浏览器真实回归

使用当前生产构建和隔离 API/存储完成：

- 账号 A 登录、进入场景、上传 EvalData 中的真实 Markdown 文件；页面观察到 `202` 后的“正在处理”，随后通过多次 `studio` GET 轮询进入“处理完成”；刷新后仍恢复同一服务端状态。
- 390px 窄屏下工作区导航收进 Dialog；Escape 关闭后焦点回到“切换工作区导航”按钮。
- 旧 `/workspaces/{id}/cases/new` 重定向到工作台；旧 `/cases/{id}` 重定向到题稿路由。
- 不存在题显示可恢复的 `RESOURCE_NOT_FOUND` 页面，不保留伪内容。
- 账号 B 访问账号 A 的私有场景显示 `FORBIDDEN`，没有渲染私有资料。
- 当前生产构建页面标题、API rewrite、静态 chunk 和前端 typecheck 均通过；旧开发进程造成的 chunk 500 已被识别并排除。

## 最终质量门

- `make test`：PASS，105 个后端测试；前端 typecheck 与 OpenAPI contract-check PASS。
- `make build`：PASS，Next.js production build PASS。
- `git diff --check`：PASS。
- `pnpm@11.21.0` 与 `allowBuilds: sharp: true` 已固定并验证。

## 失败与修复摘要

- 真实 batch 初次启用 Filesystem 时出现 `EvidenceValidationError`。修复为 `/evidence` 目录可列举、虚拟路径只映射已知 file ID，并在 adapter 做整批 + group-local scope 校验，保留 Service 二次防线；越界候选最多 repair retry 一次，仍失败则 fail-closed。
- 宽松 completion union 请求在兼容 Provider 上出现 `OpenAITimeoutError`，并产生非法 locator 形状。fallback 改为按共创 kind 请求单一 wire schema，source-only refs 进入严格业务 Schema。
- 对抗审查发现 operation command 跨 kind、lease reclaim 后旧 batch attempt、终态 draft command 和前端迟到/失权快照边界；均已补 CAS/冲突、lineage 回读、稳定 upload command、generation guard 和失权清空。

## 剩余风险与未宣称项

- 当前仓库 `.env` 的 `LANGGRAPH_AES_KEY` 经安全检查为 32 字节，长度满足 AES 配置；但 `.env` 中的 PostgreSQL 端口为 5432，而本轮隔离容器映射在 5433，本报告不把临时 5433 运行冒充原生 5432 环境已就绪。未修改用户 secret。
- 默认 `AI_MAX_COCREATION_QUESTIONS=12` 的长轮真实成本/延迟未做完整跑量；本轮已用预算 1 覆盖 fallback 边界并以有限 request timeout fail-closed。
- 本轮没有新增浏览器自动化测试文件；真实浏览器证据为 Playwright CLI 交互记录，仓库当前没有 Playwright CI suite。
- 临时 PostgreSQL、API/Worker、前端进程和存储根在收尾时按精确名称停止/清理；业务/Checkpoint 数据不作为产品数据保留。
