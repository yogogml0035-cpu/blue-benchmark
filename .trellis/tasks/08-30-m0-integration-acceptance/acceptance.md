# M0 集成与真实样本验收报告

日期：2026-08-30

## 已执行证据

- `make test`：通过 51 个后端测试、前端 TypeScript 检查，以及后端 OpenAPI 与前端生成类型一致性检查。
- `make build`：停止前端 dev server 后串行通过 Next.js 生产构建。
- `cd backend && uv run python scripts/accept_real_samples.py --samples-dir ../.local-samples/m0`：通过三份本地 Git-ignored 样本的结构检查、导入、两任务分类、三次 attempts、两题共创、冻结 v1、分区 hash 与 runtime 隔离检查。
- Playwright 真实浏览器：使用运行中的 FastAPI、单个 Worker 和 Next.js，完成登录、建场景、上传三份样本、资料角色确认、任务拆分、场景标准共创、刷新后回答恢复、两题定稿、题池加入、覆盖审查轮询、冻结和版本下载；另验证窄屏工作台导航、Escape 关闭/焦点回收、旧 `/cases` 重定向和第二账号 `403`。
- 下载包机械检查：ZIP 仅含 `manifest.json`、`runtime.json`、`judge.json`、`provenance.json`；分区 hash 存在，runtime 未出现判定字段或 provenance marker。
- `git diff --check`、子任务和父任务 `task.py validate`：通过。真实样本目录仍被 `.gitignore` 排除。

## 对抗式审查及修正

1. 跨任务合同传播：合同只写回首题会阻塞同场景第二题。确认合同时传播到 workspace 内所有已确认任务，并增加回归。
2. 合同升级与旧判定依据：旧依据可能被误当成当前依据，或被严格门挡住影响复核。未复核时严格阻塞；草稿完成 `reviewed`/`no_conflict_confirmed` 后，才允许该草稿以老师复核作为放行证据。
3. 覆盖操作状态：同一草稿曾可排多个覆盖审查；`confirmed=false` 曾写入确认时间；无 warning 时 UI 曾强制填写风险说明。分别改为活动操作冲突、否定确认不产生 `confirmed_at`、无风险可直接冻结，并加入回归。
4. 版本 ZIP 篡改：重复 `manifest.json` 可能通过名称集合检查。现在要求 ZIP 恰好四个且名称唯一。
5. 浏览器主路径：场景列表旧上传链接、场景标准入口、任务拆分、版本题池加入和后台轮询曾断裂；补齐真实业务入口、原生分组控件、`has_contract` 合同状态、加入/移出题和 operation polling。
6. 窄屏和键盘：顶栏用户名造成 12px 横溢出；导航 Escape 不关闭且焦点不回收。增加用户名截断和 modal 导航焦点/键盘行为，Playwright 以 `scrollWidth == innerWidth` 复核。
7. 运行配置：根 `.env`、`STORAGE_ROOT=./storage` 在 API/Worker 不同工作目录下可能指向不同位置，且示例密钥名与 Settings 不一致。Settings 统一读取仓库根 `.env`、相对存储根，示例改用 `LANGGRAPH_AES_KEY`。
8. 验收环境：Next dev 与 production build 共享 `.next`，并行会造成模块缺失。收尾门要求停止 dev server 后再 build；生成缓存损坏时仅移动到明确临时目录恢复。
9. 题池和标准升级旁路：题池改为读取 workspace 内全部已确认题，跨批次回归通过；批准标准升级提案复用合同传播并使旧判定依据失效。
10. 已确认资料边界：TaskPackage 引用文件后拒绝原地修改 role/visibility；合同升级后旧题允许移出下一版，但未复核题不能加入或冻结。
11. 输入极值：分组确认保留 attempts，跨组 key/label 在提交前限制到后端长度；ZIP 重复条目 fail-closed；合同确认传播在 PostgreSQL 路径锁定任务行。

## 尚未验证或明确不属于本次声明

- 本地真实样本 runner 和浏览器使用 Fake adapter；生产 PostgreSQL 业务库、加密 PostgreSQL Checkpointer 和真实 provider smoke 未在本轮执行，不能以本报告宣称其已部署或已连通。
- 当前仓库没有自动 Checkpoint 清理消费者；本轮只验证已完成共创 thread 删除后业务投影可读，并保留活动会话不主动删除。生产清理任务需要另立实现和验收。
- M2 的 Skill/Agent 执行、judge 运行、在线评测和报告不在 M0 验收范围。
- 当前前端没有提交 Playwright 测试套件；浏览器证据是本轮真实人工/CLI 交互，不等同于 CI 自动化。
- 本轮浏览器使用的是临时 SQLite/本地存储中的真实样本验收数据；已验证真实页面交互，但没有把真实样本固化为可重复的 CI 浏览器 fixture。
- 当前运营前提仍是不建设 DLP、脱敏预览或按片段授权；上传材料必须由受训内部老师确认可交给平台 AI。

结论：在默认 Fake/本地存储路径下，M0 的真实输入到可下载 v1 的跨层闭环已通过；覆盖充分性、真实 provider 能力和 M2 运行可靠性仍不能由本报告外推。
