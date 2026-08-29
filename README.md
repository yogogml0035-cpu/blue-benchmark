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

## 人工验收路径

一次走完 Walking Skeleton。后端是内存 Stub，重启 FastAPI 会清空账号和数据。

1. 打开 `http://localhost:3000/`，未登录时会跳到 `/login?returnTo=/workspaces`，顶部出现「需要登录才能打开这份卷宗」。
2. 切到「注册」，用 `teacher-a` / 任意 8 位以上密码建立账号，提交后进入 `/workspaces`。
3. 卷宗架此时是空的，创建表单是这一屏的焦点。填名称「客户 A 新闻稿」，点「建立私有卷宗」。
4. 在新卷宗卡片上点「收件」，填标题，把一个 `.txt` 或 `.md` 拖进投放区（内容随意，非空即可），点「收件并解析」。
5. 详情页自动请一次草案，停在 `waiting_for_input`：琥珀色追问单里只有一个问题。写下你认可哪个结果，提交。
6. 页面转到 `waiting_for_confirmation`：校样上每条主张左侧的墨线说明来源（墨＝输入事实、朱＝老师判断、蓝＝AI 候选、琥珀＝未知缺口），右侧边栏是它的引注。任意修改几个字段，页脚的完整性清单实时更新。
7. 七项清单全绿后点「确认并落章」，页面转 `confirmed`：印章块给出候选用例 ID、第 N 校、确认人和确认时间，下方是只读的最终快照，并明确声明它还不是回归集成员。
8. 刷新这一页，状态、进程条和快照都从服务端快照恢复，不依赖前端记忆。
9. 越权检查：退出，注册 `teacher-b`，把上一步的案例地址粘回地址栏 —— 得到 `403 FORBIDDEN`，页面不渲染任何案例内容。
10. 退件检查：以 `teacher-b` 建一个卷宗，上传一个空文件 —— 停在 `parse_failed`，只提供「修正后重新收件」，不提供无意义的重试。
11. AI 失败检查：上传一个含 `[stub:ai_failed]` 的文件 —— 停在 `ai_failed` 并给出 `retryable · true`；点「重试 AI」沿用同一个会话进入待确认。

## 状态预演

四个页面都带一条「状态预演」条（仅开发构建可见，生产构建整块不渲染），用 `?preview=` 把页面钉在某一个状态上，便于逐项验收 loading / empty / success / error / unauthorized：

| 页面 | 可预演状态 |
|---|---|
| `/login` | `loading` `empty` `success` `error` `unauthorized` |
| `/workspaces` | `loading` `empty` `success` `error` `unauthorized` |
| `/workspaces/{id}/cases/new` | 上面五个，另加 `forbidden` `not_found` |
| `/workspaces/{id}/cases/{caseId}` | 上面七个，另加 `question`（追问）`review`（校订） |

预演数据只用 `src/lib/api/generated.ts` 的类型构造，与后端合同漂移时会在 `pnpm typecheck` 阶段报错。

## 明确延后

数据库、迁移、真实文件存储/扩展格式解析、LangGraph Checkpoint、真实模型、Worker、完整权限协作、回归集和评测功能均不在本骨架内。

