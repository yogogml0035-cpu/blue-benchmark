# M0 Deep Agent 与共创实施计划

## Ordered checklist

1. 将 Spike 精确版本加入后端依赖并建立可单独运行的 capability smoke。
2. 建立 AI Profile、三个 Protocol、小 Pydantic Schema 和 Fake adapters。
3. 实现 EvidenceBackend、Filesystem replacement、ModelToolSurfaceMiddleware 和启动工具断言。
4. 接入 batch_analyzer，完成长文件分页、locator 回查和任务分组提案。
5. 接入加密 AsyncPostgresSaver、ask_teacher/respond 和 stable thread。
6. 实现 answer `202`、resume/reproject、accepted/produced pointer、CAS 和 continuity reset。
7. 实现场景合同、单题共创、主观 JudgmentPackage、标准升级提案和阻塞门。
8. 用 Fake 完成全状态机械测试，再运行当前 provider smoke；生成 OpenAPI。

## Validation

```bash
cd backend && uv run pytest -q
make openapi
```

真实 provider smoke 默认不进入普通 CI；它只使用合成输入，输出能力布尔值和错误类型，不输出正文、Checkpoint、凭证或 private reasoning。

## Handoff gate

- 两个真实任务候选可在 Fake/脱敏 fixture 上完成分组、合同和单题共创业务投影。
- 所有恢复路径都由 accepted pointer/revision 驱动，浏览器 DTO 无内部 ID。
- `m0-evaluation-versioning` 可以只依赖已确认合同/题/形成记录，不读取 Checkpoint 私有表。
