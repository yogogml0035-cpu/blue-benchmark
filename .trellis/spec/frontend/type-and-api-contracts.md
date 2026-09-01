# 类型与 API 合同

## TypeScript 基线

`frontend/tsconfig.json` 开启 `strict`、`allowJs=false`、`noEmit`、`isolatedModules`。新代码必须保持严格类型通过，不以 `any`、`@ts-ignore` 或无依据的强制断言绕过合同。

组件 Props、页面加载状态和有限变体使用局部类型；跨层 DTO 只来自生成文件。

## OpenAPI 是跨层类型来源

`backend/openapi.json` 由 FastAPI 应用导出，`frontend/src/lib/api/generated.ts` 由 `openapi-typescript` 生成。两者都不能手工修补。生成入口：

```bash
make openapi
```

Feature Service 从生成的 `components` 取类型：

```ts
type LoginRequest = components["schemas"]["LoginRequest"];
export type Case = components["schemas"]["Case"];
```

参考 `authService.ts`、`workspaceService.ts`、`authoringService.ts`、`rubricService.ts` 和 `studioService.ts`。不要再手写一份 User、Workspace、QuestionDraft、Rubric、Version 或错误 DTO。

`apiFetch<T>` 只负责通用传输：同源 Cookie、JSON Header、204、错误形状和 `ApiError`。路径与 Feature 返回包装由对应 Service 声明；组件只能调用 Service，不能直接为 HTTP Body 做类型断言。

## 运行时边界

当前前端没有 Zod/Yup 等运行时校验库。请求输入由控件和后端 Pydantic 共同约束，响应失败经 `ApiError` 处理。不要把 TypeScript 类型当作服务端信任边界，也不要为了单个表单引入第二套 Schema 系统。

捕获的异常使用 `unknown`，通过 `cause instanceof ApiError` 或 `toPageFault(cause)` 收窄。有限枚举映射使用 `Record<Union, ...>`，这样后端生成类型新增状态时 `pnpm typecheck` 会暴露未同步分支；参考 `caseState.ts::STATE_META` 和 `DraftView.tsx::KIND_LABEL`。

## 合同变更顺序

1. 修改后端 Pydantic Schema / Router 响应；
2. 运行 `make openapi`，检查生成 diff，不手改生成文件；
3. 更新 Feature Service、状态映射、组件和预演 fixtures；
4. 扩展后端 API 测试；
5. 运行 `make test` 和必要的 `make build`。
