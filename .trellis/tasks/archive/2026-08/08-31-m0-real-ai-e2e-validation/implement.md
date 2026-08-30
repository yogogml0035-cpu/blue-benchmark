# M0 真实 AI E2E 验证与加固实施计划

## 1. 顺序

1. 记录当前 checkout、分支/worktree、归档需求、凭证存在性（不泄漏值）和现有自动化基线。
2. 建立 `codex/m0-real-ai-e2e-validation` 分支，激活本任务；补齐 `implement.jsonl`/`check.jsonl` 的规范与需求上下文。
3. 运行真实 Provider smoke；检查 AI Profile、ToolStrategy、模型返回类型和 secret-safe 输出。
4. 启动隔离 PostgreSQL；运行 `db-migrate`、`db-check`、`checkpoint-setup`，验证业务库/Checkpoint 库独立、加密 schema ready 和重启可读。
5. 先运行现有自动化和静态合同检查，再用真实 AI/真实 Worker 做 API 跨层 E2E；记录每个 operation kind、状态转移、attempt、业务 revision 和版本包哈希关系。
6. 用真实运行中的 API/Worker/Next.js 完成桌面和窄屏浏览器路径；执行刷新、重启、错误恢复、幂等、并发、权限和下载机械检查。
7. 第一轮对抗审查：从数据流/安全/运行时权限/Checkpoint 业务一致性攻击；复现可复现漏洞后在实际所有者层修复并回归。
8. 第二轮对抗审查：从边界、迟到结果、合同/版本 lineage、ZIP、配置漂移、pnpm/生产构建和浏览器焦点攻击；同样先复现再修复。
9. 运行 `trellis-check`、`make test`、`make build`、`git diff --check`；停止 dev server 后构建，检查没有秘密/真实样本/临时产物进入差异。
10. 提交单一稳定职责批次，切回 `main` fast-forward 合并，在 `main` 重跑质量门和目标 E2E，再按门禁归档 Trellis 任务并删除本任务分支。

## 2. 重点反例矩阵

| 反例 | 预期保护 |
|---|---|
| Provider 配置存在但返回文本/invalid tool call | smoke fail closed，不进入业务验收 |
| 业务库与 Checkpointer 同库或 schema 未 setup | setup/Worker 启动拒绝 |
| GET 轮询、重复 upload/answer/freeze | 无副作用、同一业务结果/版本 |
| 同 session 并发 resume、旧 revision 或迟到分支 | 409/superseded，不覆盖新 revision |
| Checkpoint ahead / 业务 projection behind | 只读 reproject，不重新调用模型 |
| Checkpoint 缺失/不兼容 | 保留已存答案，显式 continuity reset 或 retry |
| ZIP 穿越、符号链接、重复成员、超限 | 确定性拒绝且无半成品 |
| runtime 混入 reference/judge/provenance | freeze 阻塞或泄漏回归失败 |
| 第二账号、旧 cases 路由、窄屏焦点 | 403/重定向/焦点回收正确 |

## 3. 回滚点

- 环境：停止并删除精确命名的临时容器，清理临时 storage/log；保留失败日志的扫描结果，不删除用户文件。
- 代码：每次修复前记录失败测试和文件范围；仅回滚本分支本轮提交，不 reset/checkout 用户改动。
- 数据：使用一次性本地数据库和账号，冻结包只在临时 storage；不对远端或用户已有本地数据库执行 destructive 操作。

## 4. 交付证据

- `research/real-ai-e2e-report.md`：只含阶段、状态、计数、哈希是否一致、错误类型和剩余边界；样本来源固定记录为用户指定的 `/Users/hsikey/BenchMark/EvalData`，不复制正文。
- `research/adversarial-round-*.md`：每轮发现、复现、修复、回归命令。
- 若新增脚本，必须默认显式 opt-in，支持 secret-safe 输出，并在 `README`/Makefile 有准确入口；不把真实样本路径硬编码进默认测试。
