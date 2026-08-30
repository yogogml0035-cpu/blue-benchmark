# 生产 AI Worker 对抗加固

## Goal

修复真实 Provider smoke 暴露的 Deep Agents 空 memory middleware，并强化生产 Worker 的启动错误边界与模型标识校验，确保真实 AI 路径在 smoke 后继续进入可执行状态。

## Confirmed Facts

- 真实 `make ai-smoke` 曾在 Deep Agents 0.7.11 的 `MemoryMiddleware.before_agent` 报 `NotImplementedError`：传入 `memory=[]` 会启用 middleware，不能表达禁用。
- 当前 M0 明确禁用 Store/Memory，模型只应读取只读 Evidence backend。
- Provider model id 被用于 `provider:model` HarnessProfile key；包含 `:` 或控制字符会使 profile key 歧义或污染终端日志。
- Worker 和 Checkpointer setup 入口必须报告安全错误，不把 SDK/DSN 异常链输出到终端。

## Requirements

- Deep Agent graph 使用 `skills=None`、`memory=None` 明确关闭空来源 middleware；Store 保持 `None`。
- `AI_MODEL` 拒绝冒号和控制字符，Provider 注册键保持单一、可审计。
- Worker 与 Checkpointer setup 对未分类启动异常只输出异常类型并返回非零；已知配置错误继续输出稳定、不含凭证的消息。
- 为上述缺口保留回归测试；不改变模型 Provider 选择、Checkpointer 生命周期、业务投影或 Fake 测试合同。

## Acceptance Criteria

- [ ] 真实 Provider smoke 不再因 `MemoryMiddleware`/`download_files` 缺失失败；graph 构造参数断言 Skills/Memory/Store 均禁用。
- [ ] 非法 model id、Provider/SDK/连接异常均 fail-closed，输出不含 API key、URL 密码、原始回复或 traceback。
- [ ] 原有 provider 构造、生产 Worker、Checkpointer、Fake 和业务测试继续通过。
- [ ] `make test`、`make build`、`git diff --check` 通过；真实 `make ai-smoke` 在当前配置下通过或明确暴露新的真实端点能力错误。

## Out of Scope

- 新增 Store/Memory、厂商专用 reasoning adapter、Provider fallback 或业务 API/前端修改。
- 重新设计上一任务的生产接线或数据库 schema。
