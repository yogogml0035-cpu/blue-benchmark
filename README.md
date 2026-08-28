# Skill Eval Platform

这是 Case Builder Walking Skeleton：`frontend/` 是 Next.js App Router，`backend/` 是 FastAPI。当前阶段只提供内存 Stub，不连接数据库、不保存上传原件、不调用真实 AI。

## 本地运行

需要 Node.js、pnpm、Python 3.12+ 和 uv。分别打开两个终端：

```bash
cd backend
uv sync --dev
uv run uvicorn app.main:app --reload --port 8000
```

```bash
cd frontend
pnpm install
pnpm dev
```

成功标志：

- 后端健康检查：`http://127.0.0.1:8000/healthz` 返回 `status=ok`；
- OpenAPI：`http://127.0.0.1:8000/api/docs`；
- 前端：`http://localhost:3000/login`；
- 前端请求只使用同源 `/api/*`，由 `next.config.mjs` Rewrite 转发到 FastAPI。

## 生成接口类型

```bash
make openapi
```

命令先从 FastAPI 生成 `backend/openapi.json`，再用 `openapi-typescript` 生成 `frontend/src/lib/api/generated.ts`。生成文件不手改。

## 验证

```bash
make test
```

默认上传可解析 TXT/Markdown 后会进入一次追问，再进入待确认草案；文件内容加入以下 Stub 标记可复现其他分支：

- `[stub:waiting_for_confirmation]`：生成后直接进入待确认；
- `[stub:ai_failed]`：第一次 AI 生成进入 `ai_failed`，再次点击重试后进入待确认；
- 空文件或只有空白：进入 `parse_failed`；
- 用另一个注册账号访问第一个账号的空间或案例：返回 `403 FORBIDDEN`。

确认草案只生成 `candidate_case`，不会加入回归集，也不会触发评测。

## 明确延后

数据库、迁移、真实文件存储/扩展格式解析、LangGraph Checkpoint、真实模型、Worker、完整权限协作、回归集和评测功能均不在本骨架内。

