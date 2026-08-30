# 前端结构与依赖边界

## 当前结构

前端是 Next.js 15 App Router + React 19 + TypeScript 5.8，业务代码位于 `frontend/src/`：

```text
src/
├── app/                         # 路由、Metadata、参数解析、Suspense 组合
├── components/
│   ├── shell/                  # 全站壳层
│   └── ui/                     # 跨 Feature 的小型 UI 原语
├── features/
│   ├── auth/{components,hooks,services}/
│   ├── workspaces/{components,preview,services}/
│   └── case-builder/{components,lib,preview,services}/
└── lib/
    ├── api/{client,generated,pageFault}.ts
    ├── preview/preview.tsx
    └── format.ts
```

绝对导入使用 `@/src/lib/api/client`、`@/src/features/auth/services/authService` 这类完整路径，来自 `tsconfig.json` 的 `@/* -> ./*`。同一目录的 CSS Module 使用相对导入。

## App Router 页面

`src/app/**/page.tsx` 保持薄：定义 Metadata、解析异步 `params`、用 `Suspense` 提供版面一致的 `PageFallback`，然后组合 Feature 入口组件。当前路由族是：

- `app/(auth)/login/page.tsx` -> `AuthPanel`；
- `app/(app)/workspaces/page.tsx` -> `ScenarioShelf`；
- `app/(app)/workspaces/[workspaceId]/page.tsx` -> `StudioPage`，通过 `section=current|questions|versions` 承载场景工作台；
- `app/(app)/workspaces/[workspaceId]/upload/page.tsx` -> `UploadPage`，作为上传入口；
- `app/(app)/workspaces/[workspaceId]/questions/[questionId]/page.tsx` -> `QuestionPage`，承载场景标准和单题判定的聚焦共创；
- `app/(app)/workspaces/[workspaceId]/versions/[versionId]/page.tsx` -> 只读版本详情和下载；
- 旧 `/cases/new` 重定向到工作台，旧 `/cases/{caseId}` 重定向到聚焦题页。

页面文件默认是 Server Component。需要事件、Effect、浏览器导航或本地状态的实现放入 Feature Client Component，并在文件首行写 `"use client"`。不要把整个路由树无差别改成 Client Component。

## Feature 内部分工

- `components/`：页面级业务 UI 和 Feature 内可复用视图；
- `services/`：该 Feature 唯一 HTTP 调用入口，只调用 `src/lib/api/client.ts::apiFetch`；
- `hooks/`：确实被复用或承担明确边界的状态逻辑，当前只有认证会话 `useSession`；
- `lib/`：Feature 自有的纯状态/展示映射，当前 `case-builder/lib/caseState.ts` 集中 Case 状态语义；
- `preview/`：仅开发构建使用、且由 OpenAPI 生成类型约束的预演 fixture。

不要从一个 Feature 的组件深层导入另一个 Feature 的内部组件或局部状态。已存在的跨 Feature 使用是显式业务依赖，例如 Workspace / Case 页面使用认证的 `useSession` 与 `UserChip`。

## 共享代码边界

只有跨 Feature 且语义稳定的代码进入 `src/components/` 或 `src/lib/`：

- 请求、API 错误：`lib/api/client.ts`；
- 页面级 HTTP 故障：`lib/api/pageFault.ts`；
- 日期、字节、界面截短：`lib/format.ts`；
- Button、Field、Note、StatePanel、Skeleton 等视觉原语：`components/ui/`；
- 顶部导航：`components/shell/DeskRail.tsx`。

单页面的一次性逻辑先保留在 Feature 内，不要提前建设全局 store、通用表单框架或组件库。

## 不要这样做

- 不要创建 `app/api` 代理；同源 `/api/*` 已由 `next.config.mjs` Rewrite 到 FastAPI。
- 不要在组件里直接 `fetch`、手写 Cookie 逻辑或复制 API 错误解析。
- 不要在前端实现数据库、LangGraph 或后端授权规则。
- 不要为尚未实现的 M1 知识库、M2 Skill/Agent 执行、评测运行或多人协作创建空路由或空 Feature。
