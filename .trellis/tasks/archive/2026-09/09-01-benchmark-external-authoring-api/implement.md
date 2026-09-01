# 实施计划：Benchmark 外部收题 API

## Before Start

- [x] `benchmark-question-lifecycle-simplification` 已完成完整分支闭环。
- [x] 最终 API/payload 规划获得单独实施批准。
- [x] 从验证干净的 `main` 创建 `codex/benchmark-external-authoring-api`。
- [x] 读取 auth、workspace、authoring、storage、错误、OpenAPI 和跨层规范。

## Backend

- [x] 新增连接/凭证迁移、Repository、Service、Schema 与专用鉴权 dependency。
- [x] 实现 Web 创建/撤销、一次兑换、只读绑定状态和结构化草稿写入端口。
- [x] 扩展 Authoring Service 接收 canonical 单题 payload，不让 Router 直接写 Repository。
- [x] 确保外部上传只同步保存草稿并返回 `201 + draft URL`，不排队任何 AI/rubric OperationJob。
- [x] 复用 Web Authoring 编辑合同；保存外部上传 receipt/hash，网站 PATCH 推进 draft revision，外部 API 不暴露草稿读取/更新/删除端口。
- [x] 实现文本/Markdown、标准答案、坏样本原因、bytes/数量、幂等、staging/ready 和错误矩阵。
- [x] 增加 `task_requirement` 逐字保真测试：多行、前后空白、中文标点、显式 Skill 调用和重复 command 均不被改写。
- [x] 增加标准答案逐字保真，以及坏样本不含 system/tool/private trace 的 allowlist 测试。
- [x] 增加完整文件、老师确认节选、来源标记、静默截断拒绝和真实坏样本来源测试；老师反馈原话必须逐字，摘要需确认，Skill 合成坏样本或用摘要覆盖原话必须失败。
- [x] 覆盖老师反馈过于笼统时的继续追问、补充原话保存和放弃该坏样本三种路径。
- [x] 添加账号/Workspace 隔离、token hash、主动撤销、重新绑定失效、Workspace/账号失效、连接码过期、并发重放、日志泄漏和故障清理测试。
- [x] 增加场景改名仍绑定稳定 ID、per-token 频率/并发/payload 限制和安全 413/429 测试。
- [x] 生成并校验 OpenAPI；提供真实 E2E 客户端 fixture，但不包含永久凭证或业务正文。

## Frontend

- [x] 在场景设置中提供“连接本地 Agent”、连接状态和撤销入口。
- [x] 一次性连接信息只展示必要内容，不进入 URL、日志或持久前端状态。
- [x] 外部上传成功后的普通草稿审阅页继续使用 Web Session；401/403 清空私有快照。
- [x] 精确链接打开可编辑草稿，保存后仍留在正常网站流程；不展示或依赖外部 token。
- [x] 匿名访问经登录后返回同一草稿；return-to 只允许同源受保护路由。
- [x] 覆盖空态、已连接、已撤销、已重新绑定、连接码过期、复制/说明、键盘和窄屏状态。

## Validation

```bash
make openapi
make test
make build
git diff --check
```

- [x] 使用临时凭证和真实本地 HTTP 服务完成 connect -> status -> push -> exact draft link -> Web view -> revoke。
- [x] 断言 push 后没有 rubric/AI job，只有老师进入网站并执行后续动作才生成规则。
- [x] 对伪造 Workspace、重放 code/token、跨账号、正文泄漏、非文本 payload、并发 command 和存储失败做对抗检查。
- [x] 对依赖前文但未提供输入内容的用例做 Skill 端阻塞测试，禁止本地 Agent 静默补写任务要求。
- [x] 断言外部 token 无法读取或修改草稿；网站编辑保留原上传 receipt 并正确推进 revision。
- [ ] 合并后在 `main` 重跑质量门，归档任务并安全删除精确任务分支。

## External Skill Handoff

- [ ] API 合同冻结并合并后，在 `/Users/hsikey/BenchMark/BenchMark/ai-eval-push` 初始化独立 Git/Trellis 规划。
- [ ] 用真实 OpenAPI 构建 `ai-eval-push`；其运行在上传后立即结束并返回草稿链接，不轮询平台 AI，再完成安全扫描、E2E、全局安装和私有 GitHub 仓库发布。
- [ ] Skill 禁止隐式触发；连接 token 保存到 OS keychain 或用户私有 0600 配置，不进入源码目录、命令回显、`.env` 或 Git。
- [ ] 不在本任务中写入或发布外部 Skill 源码。

## Rollback

- Feature Gate 可关闭外部连接和写入；撤销所有 active token，不删除已创建的普通题目草稿。
