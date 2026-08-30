# 生产 AI Worker 对抗加固实施计划

## Checklist

1. 激活本跟进任务并确认当前分支基于已验证 `main`。
2. 检查并完成 `adapters.py` 的 None 语义、`model.py` 的 model id 校验、Worker/setup 安全错误出口和对应回归测试。
3. 更新 backend code-spec，记录 Deep Agents 空列表启用 middleware 的 gotcha。
4. 运行真实 `make ai-smoke`、后端测试、`make test` 和 `make build`。
5. 提交、合并回 `main`，在合并后的 `main` 重跑质量门，归档本跟进任务并安全删除分支。

## Validation

```bash
git diff --check
cd backend && uv run pytest -q
make test
make build
make ai-smoke
```

`make ai-smoke` 使用真实配置，结果必须按 PASS/FAIL 诚实记录；失败时只修代码或报告新的真实 Provider 能力缺口，不伪造通过。
