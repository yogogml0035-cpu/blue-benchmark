# M0 评测版本与版本包实施计划

## Ordered checklist

1. 建立 evaluation_sets Feature、表、Repository/Service/Schema/Router 和测试骨架。
2. 实现场景合同修订、影响审查和 review_required 状态转换。
3. 实现唯一 WorkingSetDraft、成员操作、连续版本与历史只读。
4. 接 coverage reviewer，保存覆盖快照和老师风险确认。
5. 实现 freeze `202`、OperationJob handler、staging/canonical Manifest/三分区 builder。
6. 加分区 allowlist、哈希、ready marker、原子发布与幂等重试。
7. 实现历史、Manifest API 和下载；生成 OpenAPI。

## Validation

```bash
cd backend && uv run pytest -q
make openapi
```

额外机械测试对 runtime 解包扫描全部 judge/provenance 字段名和合成秘密标记；任何命中都使 freeze 失败。

## Handoff gate

- 后端可在无前端情况下从已确认题冻结 v1、下载并验证包，再派生/冻结 v2。
- 历史版本和整体哈希在后续编辑后保持不变。
- 前端只需消费生成 DTO 和 StudioProjection，不推导冻结规则。
