# M0 集成与真实样本验收设计

## Test layers

1. 单元/合同：各子任务自己的快速测试。
2. 合成跨层：固定 fixture、Fake Agent、真实 PostgreSQL/文件存储、无外部模型。
3. Provider smoke：合成短输入、显式运行、只输出能力和指标。
4. 真实样本：本地 Git-ignored 目录、人工确认、完整浏览器流程。

## Evidence policy

- 真实样本路径、正文、老师回答和版本包不进入日志、截图文件名、Git 或 CI artifact。
- 截图只证明视觉和可见状态；数据库/哈希/恢复由机械断言证明。
- 每项验收记录 input class、命令、成功标记、失败检查和证据位置。

## Recovery matrix

- OperationJob claim 前/后、Checkpoint interrupt 后、答案落库后、resume 后投影前、freeze staging/ready 前后分别故障注入。
- 使用 model/tool call 计数和 command id 证明无重复副作用。

## File ownership

- 独占：`tests/integration/**`、本地真实样本 runner、验收报告、README、最终 `.trellis/spec/**` 更新。
- 共享：Makefile、`.env.example`、开发 compose；只添加可复制命令和占位符。
- 业务缺陷返回 persistence/deep-agent/versioning/frontend 子任务修复。

## Exit rule

只有真实输入到可下载、可验证 v1 的完整路径通过，才可宣称 M0 跑通。任何 Preview、fixture-only 或静态文档结果都必须单独标注。
