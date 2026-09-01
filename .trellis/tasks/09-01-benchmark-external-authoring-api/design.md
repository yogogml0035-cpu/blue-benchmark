# 技术设计：Benchmark 外部收题 API

## 1. Architecture

```text
平台 Web Session
  -> 创建一次性连接码
本地客户端
  -> 兑换场景绑定凭证
  -> POST 结构化单题草稿
平台 External Authoring API
  -> 鉴权/幂等/Schema 校验
  -> Authoring Service 创建草稿
  -> 同步返回精确 Web 草稿 URL
老师点击 URL
  -> 在网站继续草稿审阅、生成 rubric 与发布
```

Skill 是客户端工作流；服务端 API 与领域 Service 才是权限和业务事实源。

## 2. Auth Model

新增独立 `authoring_connections` 所有权，不复用浏览器 Session 表：

- connection：user/workspace、client identity、scope、code hash/code expiry、token hash、revoked_at/reason、last_used、created_at；长期 token 不设置固定 expiry。
- Web Session 端口创建一次性 code；exchange 端口消费 code 并返回一次 token。
- API middleware/dependency 将 token 解析为可信 `ExternalAuthoringPrincipal`，包含固定 user/workspace/scope。
- 上传路径不含可变 `workspace_id`，或路径中的 ID 必须与 principal 完全一致；推荐无 workspace 路径。

## 3. API Direction

- `POST /api/workspaces/{workspace_id}/authoring-connections`：Web Cookie，创建一次性连接信息。
- `POST /api/external/authoring-connections/exchange`：兑换 token。
- `GET /api/external/authoring-connection`：只返回绑定账号/场景显示信息和状态。
- `POST /api/external/evaluation-case-drafts`：Bearer/专用头，同步创建一个评测用例草稿并返回 `201 Created`。
- `DELETE /api/workspaces/{workspace_id}/authoring-connections/{id}`：Web Cookie 撤销。

External API 不提供 question draft GET/PATCH/DELETE；创建后的内容管理复用浏览器 Session 下的 Authoring API。

最终路径以现有路由规范与 OpenAPI 评审为准；机器错误码稳定，正文不进入 detail。

## 4. Payload

Canonical JSON 使用最小严格 Schema：

- `schema_version`, `command_id`
- `title`：本地 Agent 概括、老师预览确认的题目标题
- `task_requirement`：老师本地交给 Agent 的原始提示词，逐字保存，不 trim/摘要/改写
- `input_files[]`：stable client id、显示名称、`text/plain | text/markdown`、`content_mode=full|teacher_confirmed_excerpt`、`content_text`；节选另存来源文件名
- `bad_samples[]`：stable id、真实执行 source ref、逐字 `content_text`、逐字 `teacher_feedback_texts[]`、老师确认的 `reason_summary`
- `reference_answer_text`：老师最终认可结果的逐字完整正文，不允许 Skill 改写

服务端只规范化结构边界，验证 UTF-8 bytes/数量/总大小，并对包含原始 `task_requirement`、完整文件/节选标记和真实坏样本的 canonical payload 计算 hash；不得改写、摘要或截断正文。未在最小 Schema 中声明的扩展字段、宿主路径、账号、Workspace、发布状态和评分规则均拒绝。

## 5. Domain Integration

- External Router 只处理凭证与 HTTP 形状，调用现有/简化后的 Authoring Service 创建 `BenchmarkQuestionDraft`。
- 新草稿状态进入 rubric 生成前的可审阅状态；上传事务不得创建 AI/rubric OperationJob。
- 老师点击返回链接后，通过 Web UI查看并编辑草稿，再依次执行“确认题目并生成打分规则”和“确认规则并发布到评测集”。
- 网站后续流程首先调用“确认题目并生成打分规则”组合命令；External Router/Token 无权调用该命令。
- 外部上传 receipt 保存 canonical payload hash/来源；网站编辑只推进普通 draft revision，不改写原始 receipt。
- 外部客户端不能调用 publish、disable、delete、score 或版本下载。

## 6. Idempotency and Recovery

- 唯一键至少包含 connection/workspace + command id；payload hash 不复制正文到 OperationJob。
- 内容存储采用 staging/ready/hash；DB 失败精确清理，重启回收只触及外部 authoring namespace。
- 同 command 同 payload 回读原草稿和 URL；不同 payload 冲突。上传本身不等待或轮询 AI 操作。

## 7. Leakage and Threat Model

- 一次性 code 与 token 使用高熵随机值，数据库只存 hash，比较使用常量时间方法。
- token scope 固定、可撤销、按场景隔离；日志只留 connection/draft ID、bytes、hash 前缀和状态。
- 重新绑定同一本地连接时原子撤销旧 token；Workspace 删除或账号失效后鉴权层也必须拒绝残留 token。
- Workspace 名称只用于展示，稳定 ID 决定绑定；状态端点每次返回当前名称。
- 对 external draft:create 设置 per-token 频率/并发/payload 限制，429/413 响应不含正文。
- payload 中的所有文字视为不可信数据，不可改变系统提示或执行工具。
- 审阅 URL 使用普通资源路由与浏览器 Session 鉴权，不含 token。
- 登录 redirect 使用受校验的同源 return-to，并在登录后恢复精确草稿路由。

## 8. Compatibility and Rollback

- 外部 API 是新增边界，不改变浏览器 Cookie API。
- 可通过 Feature Gate 关闭连接创建和外部写入；已创建草稿仍按普通 Web 流程可读。
- token 撤销或重新绑定不会删除已创建草稿；历史由正常题目生命周期管理。
