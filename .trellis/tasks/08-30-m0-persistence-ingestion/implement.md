# M0 持久化与上传基础实施计划

## Ordered checklist

1. 先更新父任务拥有的过时架构合同，明确计划/已实现状态，不改产品行为。
2. 锁定 PostgreSQL/Repository 依赖，加入迁移与 schema-ready 命令。
3. 迁移 auth/workspaces，保持 API 与错误回归。
4. 建立 storage adapter、服务端键、哈希、staging/ready 和清理合同。
5. 建立 case_builder ingestion 领域表和安全多文件/ZIP 解析。
6. 建立 OperationJob/AgentRunAttempt、单消费者、租约、重试、CAS 与 Fake handlers。
7. 建立 StudioProjection、上传 `202` 和纯读轮询。
8. 生成 OpenAPI，完成后端与跨层回归。

## Validation

```bash
cd backend && uv run pytest -q
make openapi
```

必须单测路径穿越、符号链接、特殊文件、zip bomb、数量/大小/层级限制、部分失败、重复命令、租约回收、重启恢复、陈旧 revision、迟到结果和 GET 无副作用。

## Handoff gate

- 数据库/存储/OperationJob 合同稳定，Fake handler 可驱动全部状态。
- OpenAPI 已生成，后续子任务不得手写第二份 DTO。
- 无 Deep Agent、评测版本或前端实现混入本提交。
