# 跨层合同检查

## 当前数据流

```text
用户输入
  -> Next.js Feature Component
  -> frontend/features/*/services
  -> frontend/lib/api/client
  -> same-origin /api/* Rewrite
  -> FastAPI Router
  -> Feature Service
  -> 内存 Repository
  -> Pydantic Response / AppError
  -> 页面以服务端快照或 PageFault 渲染
```

当前链路到内存 Repository 和 Stub 生成结束。PostgreSQL、文件存储、LangGraph、真实模型、Worker 和评测执行是未来计划，未落地前不能加入“当前数据流”或验收结论。

## 合同事实源

- 后端运行时字段、枚举和校验：`backend/app/features/*/schemas.py`；
- 状态转换、授权和幂等：对应 Feature `service.py`；
- 机器可读 HTTP 合同：FastAPI 导出的 `backend/openapi.json`；
- 前端 DTO：生成的 `frontend/src/lib/api/generated.ts`；
- 前端传输和错误：`api/client.ts`、`api/pageFault.ts`；
- 前端 Case 展示语义：`case-builder/lib/caseState.ts`；
- 当前可运行边界和人工验收：`README.md`。

`docs/` 下的设计合同可以约束未来方向，但其中尚未出现在依赖清单、源码和测试里的能力必须标注为计划，不能覆盖当前源码事实。

## API 合同变更清单

修改字段、枚举、错误或接口时按顺序检查：

1. 后端 Schema、Router `response_model` / `responses` 和 Service 是否一致；
2. 后端 API 测试是否覆盖成功、失败、授权和重试；
3. 运行 `make openapi`，只接受生成器产生的 `openapi.json` / `generated.ts` 变更；
4. Feature Service 是否仍只消费生成 DTO；
5. 页面加载联合、`PageFault`、`STATE_META`、进度和预演 fixture 是否穷举新合同；
6. `make test` 通过；涉及路由或生产门控时 `make build` 通过；
7. 如用户路径改变，同步 README 的人工验收说明。

## 授权与数据泄露检查

跨层功能必须同时验证：

- 请求先有有效 Session，再检查 Workspace 所有者，再检查 Case 与 Workspace 关系；
- 403 页面不继续渲染旧缓存中的资源；
- 响应不包含密码哈希、Session Token、内部 `thread_id`、`parsed_text` 或其他账号标识；
- 前端扩展名、禁用按钮和路由 ID 都只是体验层，不替代后端校验。

## 状态机检查

Case 状态变化必须由后端 Service 完成，前端只显示返回快照。新增状态或动作时检查：

- 允许来源状态、目标状态和不允许组合的 409 机器码；
- 重复请求、陈旧问题和陈旧草稿的幂等/冲突规则；
- `last_error.stage` 与 `retryable` 是否和页面下一步一致；
- `confirmed` 是否仍只创建候选案例，不越级进入评测集；
- 刷新后是否能仅凭 GET 返回恢复页面，不依赖本地记忆。

## 证据等级

- `pytest` / typecheck / build 通过：对应自动化门通过；
- 预演状态可渲染：开发 fixture 与类型可用；
- 浏览器闭环实际完成：真实前后端交互已验收；
- 文档或 Mock 写明能力：只代表设计或说明，不能升级为运行证据。
