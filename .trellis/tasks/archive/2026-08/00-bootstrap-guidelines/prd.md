# Bootstrap Guidelines：项目开发规范回填

## 目标

基于当前 `backend/`、`frontend/`、测试、生成合同和项目文档，将 `.trellis/spec/` 从通用模板改成可供后续开发任务直接使用的项目规范。

## 范围

- 修改 `.trellis/spec/backend/`、`.trellis/spec/frontend/`、`.trellis/spec/guides/`；
- 更新本任务的 `prd.md` 和 `task.json`；
- 业务代码、项目 README / docs、生成文件、依赖和 Git 历史均不在修改范围；
- 不执行数据库、LangGraph、真实 AI、Worker、评测集等未来计划。

## 仓库分析结论

### 当前已实现

- 后端是 Python 3.12+ / FastAPI，`auth`、`workspaces`、`case_builder` 按 Feature-first 组织为 Router、Service、Repository、Schema。
- Repository 只使用进程内 `dict`，服务重启会清空用户、Session、场景和案例。
- Case Builder 同步解析 TXT/Markdown，用固定 Stub 标记覆盖提问、待确认和 AI 失败重试分支。
- 后端 Pydantic / FastAPI OpenAPI 是接口合同来源，前端通过 `openapi-typescript` 生成 `generated.ts`。
- 前端是 Next.js 15 App Router + React 19 + TypeScript strict；路由页保持薄，Feature Client Component 管理交互。
- 前端请求经 Feature Service -> `apiFetch`，会话经 `useSession`，错误经 `PageFault`，Case 展示语义集中在 `caseState.ts`。
- 自动化质量门是后端 pytest 和前端 typecheck；生产构建可单独验证。当前没有数据库测试、前端测试、lint 或 Playwright 脚本。

### 未来计划，不作为当前规范

- PostgreSQL、SQLAlchemy、Alembic、持久化 Session 和文件存储；
- 真实模型、LangChain、LangGraph Checkpoint；
- Worker、任务队列、实时推送；
- 正式评测集、评测执行、版本历史和多人协作；
- 更多文件格式、OCR 和生产认证强化。

这些内容可在 `docs/初始化项目开发规格.md`、`docs/architecture.md`、`docs/features/case-builder.md` 和 ADR 中找到设计依据，但必须等独立实现任务落地后再更新为现行规范。

## 规范树调整

### Backend

- `index.md`：后端导航、开发前检查和质量检查；
- `structure-and-boundaries.md`：Feature 分层、跨 Feature Service 边界和命名；
- `stub-state-and-contracts.md`：内存数据、状态机、上传、认证归属，以及现状/计划隔离；
- `errors-and-api-responses.md`：AppError、统一错误形状、业务失败和系统失败；
- `quality-and-tests.md`：当前工具门、TestClient 模式和 Review 清单。

删除没有当前实现依据的 `database-guidelines.md`、`logging-guidelines.md`，以及其余模板文件；数据库和日志未来落地时再新增项目规范。

### Frontend

- `index.md`：前端导航、开发前检查和质量检查；
- `structure-and-boundaries.md`：App Router、Feature、Service、共享层边界；
- `components-and-styling.md`：组件、异步交互、可访问性、全局 token 与 CSS Module；
- `hooks-and-fetching.md`：`useSession`、Effect 读取和 Hook 提取条件；
- `state-model.md`：会话、服务端快照、瞬时状态、URL 与 Case 派生状态；
- `type-and-api-contracts.md`：strict TypeScript、OpenAPI 生成 DTO 和合同变更顺序；
- `quality-and-verification.md`：当前自动化、预演、人工验收和证据等级。

原有六个空模板文件已经由上述真实边界文件替代。

### Guides

- `code-reuse.md`：列出本仓库已有的合同所有者和避免第二套实现的规则；
- `cross-layer-contracts.md`：说明当前真实数据流、OpenAPI 同步、授权和状态机检查；
- `index.md`：只导航以上两个本项目指南。

删除旧指南中与本项目无关的 Trellis CLI、跨平台模板、事件日志和版本文档案例。

## 完成清单

- [x] 后端规范来自当前源码、测试和依赖清单。
- [x] 前端规范来自当前路由、Feature、Service、组件、样式和生成合同。
- [x] 每份规范包含真实文件路径、实际模式和明确反模式。
- [x] 当前实现与未来计划已显式分开。
- [x] 不适用模板文件与无关样例已删除。
- [x] Backend、Frontend、Guides 的 `index.md` 已按新文件集重写。
- [x] 验证 `.trellis/spec/` 无占位文本、空标题、旧链接或索引漂移。
- [x] 验证后端 pytest、前端 typecheck 和非任务范围文件未被修改。

## 验证记录

- 规范审计：模板标记、尾随空白、旧索引链接均无命中；Backend、Frontend、Guides 的索引文件集比对通过；Markdown 相对链接存在性检查通过。
- Trellis 任务：`task.json` JSON 解析通过，`task.py validate 00-bootstrap-guidelines` 通过；任务没有 JSONL 上下文清单，验证器按当前文档型任务跳过。
- 后端：`PYTHONDONTWRITEBYTECODE=1 uv run pytest -q -p no:cacheprovider` -> `4 passed`。现有 FastAPI TestClient 依赖发出 1 条 `httpx` / `httpx2` 弃用警告，不影响通过，本任务未修改依赖。
- 前端：`pnpm exec tsc --noEmit --incremental false` -> 通过，无错误输出。
- 范围：对 `.trellis/spec/**` 与本任务目录之外的文件做测试前后 SHA-256 比对，37 个文件全部一致。

## 生命周期说明

本任务当前保持 `in_progress`，因为 Trellis 的正常流程由开发者审核后执行 `task.py archive 00-bootstrap-guidelines`，归档命令才会将状态改为 `completed` 并移动目录。本次只完成规范内容，不绕过归档流程手改完成状态。
