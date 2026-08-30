# 修复 Worker runpy 启动警告

## Goal

移除 `python -m app.lib.operations.worker` 启动时由包级提前导入引起的 `RuntimeWarning`，保持现有 `app.lib.operations` 重导出 API 和 Worker 行为不变。

## Confirmed Facts

- `backend/app/lib/operations/__init__.py` 当前直接导入 `app.lib.operations.worker`。
- `worker.py` 作为 `-m` 模块执行前，Python 已先加载包 `__init__`，因此产生“模块已在 `sys.modules` 中”的 runpy warning。
- 现有调用方需要 `OperationWorker`、`ProjectionPendingOperation` 和 `fake_worker` 的包级导出；不能直接删除这些名称。

## Requirements

- 将上述 Worker 符号改为惰性重导出，包初始化不主动加载 `worker` 子模块。
- 保持 `from app.lib.operations import OperationWorker` 等现有导入可用，并避免引入循环导入。
- 增加真实子进程回归测试，执行 `python -m app.lib.operations.worker --help`，断言退出成功且 stderr 不含 `RuntimeWarning`。
- 不改变 OperationJob、Worker handler、生产 Provider/Checkpointer 或 Fake 语义。

## Acceptance Criteria

- [ ] 模块启动不再输出 runpy `RuntimeWarning`。
- [ ] 包级三个兼容导出仍可导入且指向原类型/函数。
- [ ] `cd backend && uv run pytest -q`、`make test`、`make build` 和 `git diff --check` 通过。

## Out of Scope

- 不重构 Worker 入口、数据库连接、Provider 配置或业务逻辑。
- 不删除或批量修改其他启动 warning。
