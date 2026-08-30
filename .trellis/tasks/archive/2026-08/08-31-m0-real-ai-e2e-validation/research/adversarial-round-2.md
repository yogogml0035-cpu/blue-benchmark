# 对抗审查 Round 2：跨层、并发、浏览器与配置漂移

审查对象：Round 1 修复后的当前 checkout，以及真实 E2E runner/生产构建。

## 发现与修复

| 发现 | 复现证据 | 最小修复 | 回归 |
|---|---|---|---|
| Operation command key 未区分 kind，freeze 可取到 coverage job | 临时 SQLite 直接用同 target/revision/command 复现 | `create_or_get` 遇跨 kind 显式 `OperationCommandConflict`，服务层返回 `COMMAND_ID_REUSED` | operation command-kind regression |
| lease reclaim 后旧 batch attempt 可替换新提案 | 两次 claim 同一 job，旧 attempt 提交未被原实现阻挡 | `replace_proposals` 在同一事务锁定并校验 operation id/attempt 与 running 状态；批次非分析态拒绝 | `test_late_batch_analysis_attempt...` |
| freeze 后重用 draft create command 会新建 draft | 终态 draft 后 active 查询为空，原实现重新 insert | 跨 draft 回查 create command，重放返回原 draft | `test_reusing_a_terminal_draft...` |
| 上传响应丢失后的同表单重试无稳定 command | 前端 Service 原来 command 可省略 | UploadPage 组件生命周期内生成并传递 command，Service 类型改为必填 | frontend typecheck、真实浏览器上传 |
| 失权或 A→B 迟到 GET 可保留/覆盖旧私有快照 | 代码审查定位 silent polling 保留 ready state 和缺少 generation | 401/403/404 清空快照；generation guard 丢弃旧响应；Question polling 同步处理 | 真实账号 B 403、刷新/路由回归 |
| projection_pending 只显示处理中 | UI 分支无恢复动作 | 显示“结果已保存，等待投影恢复”并提供 reproject/retry | 前端 typecheck、状态代码审查 |
| pnpm 版本跨机器漂移 | 本机 `pnpm --version` 为 11.21.0，项目未固定 | `frontend/package.json` 固定 `packageManager`，workspace 固定 `allowBuilds` | `make test`、`make build` |

## 未发现

- 公共 DTO 未暴露 storage key、绝对路径、thread/checkpoint、raw message 或凭证。
- freeze/download 服务端仍校验 Manifest、三分区、ready marker 与 ZIP 内容；runner 另行机械校验三分区 hash/bytes。
- 版本号、冻结 command、Turn 和成员写入已有 row lock/唯一约束；本轮没有观察到重复版本。

## 结论

Round 2 发现均已有最小修复和回归。当前 `.env` 的 Checkpointer key 长度已满足配置要求，但原生 PostgreSQL 连接仍需由部署者在 5432 启动并确认；代码不应为了绕过该配置而自动派生或回退到 SQLite。
