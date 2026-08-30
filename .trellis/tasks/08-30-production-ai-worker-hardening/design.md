# 生产 AI Worker 对抗加固设计

## Boundary

只修复真实 smoke 证明的运行时语义和启动错误安全边界。业务 Feature、OperationJob 状态、Provider 协议和 Checkpointer schema 不变。

## Design

- `adapters.py::_graph` 向 `create_deep_agent` 传 `skills=None`、`memory=None`、`store=None`；不能传空列表，因为 Deep Agents 0.7.11 以 `is not None` 判断是否安装 middleware。
- `model.py::runtime_model_identity` 在 Provider/model/base URL 归一化后，额外拒绝 `AI_MODEL` 中的 `:`、ASCII 控制字符和 DEL；这样 `provider:model` 注册键不会产生多段或换行。
- Worker 与 `setup_checkpointer.py` 在已知 `CheckpointError`/`ModelConfigurationError` 之外捕获启动异常，只打印类型；已知错误保留稳定诊断文本，均从 `SystemExit(2)` 返回。
- 规格文档和测试记录这一非显然的 `None` 语义，防止未来把空列表当作禁用开关。

## Rollback

所有修改均是局部回归修复；回滚本跟进提交不会触碰上一任务的生产数据或 Checkpoint。真实 Provider smoke 若暴露新的协议能力问题，保持 fail-closed，不能降级 Fake/自由文本。
