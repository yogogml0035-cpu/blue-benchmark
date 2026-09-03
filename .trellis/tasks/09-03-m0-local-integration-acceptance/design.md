# Technical Design

## Local Commands

根 Makefile 负责：

- `backend`、`frontend`、`worker`：单服务调试；
- `start-all`：API + 一个 production Worker + Next dev，统一 trap 清理；
- `openapi`、`contract-check`：后端 schema 与前端 generated types；
- `test`：后端 pytest + 前端 typecheck/unit；
- `build`：后端 compile/import + Next production build；
- `test-e2e` 与显式 `accept-real-web`：浏览器和真实 AI 门禁。

启动输出明确 `http://localhost:3000`、API health 和 docs。端口被占用时先解析进程身份，不杀不属于本任务的进程。

## Deterministic E2E

Playwright 使用独立测试数据库与测试服务端，串行执行。普通 CI-style E2E 可使用 Fake Worker验证状态形状，但报告必须明确 Fake；真实验收另跑 production Worker。

保存桌面截图、trace-on-failure 和控制台/请求错误摘要；artifact 路径被 gitignore。增加测试后扫描 `sep_`、Cookie 名和合成材料正文，防止秘密进入报告。

## Real Acceptance

runner 创建临时目录、独立 SQLite URL 和非默认端口，继承 Provider 配置但不打印。它启动 API、一个 production Worker、Next production build/start，等待身份化健康条件，然后驱动 Chromium 完成父 AC15。

Agent 提示词步骤由 runner 安全解析新签发响应并在临时仓库外写配置，调用现有 Skill `connection` 与 `push`；不在命令行或输出打印 token。结束后显式终止子进程并保留仅非敏感结果。

实际 Safari 用同一隔离数据或重新建立安全测试数据，手工/自动辅助核对约定核心流程；Playwright WebKit 不能被表述为实际 Safari 的唯一证据。

## Documentation And Specs

README 从“纯后端”改为当前全栈本地运行事实。新增 `.trellis/spec/frontend/` 索引与 API、组件/样式、测试规则，并更新 backend/shared 文档中的 future UI/无 Node 旧描述。

## Rollback

验收 runner 和 Makefile 可独立回退；临时数据库/配置只删除 runner 自己创建并精确记录的路径。不得清理用户现有数据库、全局配置或无关进程。
