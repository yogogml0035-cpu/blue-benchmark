# Technical Design

## Components

- `EvaluationSetListPage`：场景列表和创建入口。
- `EvaluationSetFolder`：稳定颜色、摘要、题目/连接状态。
- `EvaluationSetDetailPage`：元数据、CredentialPanel、QuestionList 插槽。
- `EvaluationSetFormDialog`：创建/编辑共用字段与错误映射。
- `CredentialPanel`：脱敏状态、签发/轮换/撤销。
- `AgentBindingPromptDialog`：瞬时明文提示词与 Clipboard fallback。

Feature service 是唯一 scene/credential API 调用入口；共享 API client 负责 HTTP，不在组件内解析机器码。

## Derived State

- 颜色：scene ID 稳定哈希映射到受控多色板，不持久化 color。
- 未签发：无 credential history。
- 已签发待验证：至少一个 active，active 均无 `last_used_at`。
- 已连接：至少一个 active 有 `last_used_at`。
- 已停用：有 history 但无 active。

## Secret Lifetime

issue/rotate 响应只进入 PromptDialog 局部 state。模板中 token 恰好一次；复制后仍不持久化。Dialog unmount 时清空引用，浏览器刷新自然丢失。禁止 Server Component、Route Handler、query 参数、local/session storage 和调试日志接触响应 body。

提示词保持跨 Agent：要求目标 Agent 先定位 `ai-eval-push` 的真实安装/项目调用路径，再将 API 地址和 token 写到仓库外私有配置，设置当前宿主可持续读取的 `AI_EVAL_CONFIG`，运行 connection，并只返回非敏感结果。

## Deletion

前端仅在 count=0 时展示删除，但无论 UI 状态如何都调用后端门禁。删除确认明确凭证失效；409 后刷新 scene，不能继续显示已删除假状态。

## Rollback

回退 UI 不删除已创建 scene；已签发明文不能恢复，用户通过现有 CLI 或 API 轮换。不得在回滚日志记录 token。
