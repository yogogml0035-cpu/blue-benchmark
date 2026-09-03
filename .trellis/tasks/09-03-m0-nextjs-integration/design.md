# Technical Design: M0 Next.js 前后端交互

## 1. Design Principles

1. FastAPI 和业务数据库继续拥有全部业务事实；Next.js 只负责呈现、未保存草稿和调用 API。
2. OpenAPI 是跨层唯一机器合同；前端生成类型，不手写重复 DTO。
3. AI 只起草候选，老师的显式保存才形成可发布规则。
4. 凭证、删除和重新发布等高风险动作由后端门禁，不能只靠隐藏按钮。
5. AURA 视觉是设计权威，静态原型中的假数据和错误领域模型不是实现权威。
6. M0 只优化当前本机、单管理员、约 20 个评测集、单集约 200 道题的桌面工作流。

## 2. Runtime Topology

```text
Chrome / Safari
  http://localhost:3000
          |
          | same-origin /api/* + HttpOnly cookie
          v
Next.js 16 App Router (frontend, port 3000)
          |
          | next.config rewrite, BACKEND_URL
          v
FastAPI (127.0.0.1:8000)
          |
          +--> SQLAlchemy/Alembic business database
          |
          +--> operation_jobs <--> exactly one production Worker <--> real AI Provider

Local Agent
  ai-eval-push Skill --Bearer scene credential--> FastAPI external endpoints
```

Next.js 不增加业务 BFF、Server Action 数据副本或第二份认证系统。浏览器 API 请求使用相对 `/api`；`next.config.mjs` 将其代理到 `BACKEND_URL`，Cookie 因此保持浏览器同源。

配置：

- `BACKEND_URL=http://127.0.0.1:8000`：仅 Next.js 服务端 rewrite 使用；
- `NEXT_PUBLIC_AGENT_API_BASE_URL=http://127.0.0.1:8000`：只用于生成给本地 Agent 的提示词，不含秘密；
- 本地 HTTP 保持 `SESSION_COOKIE_SECURE=false`；生产默认仍为 true，不因本任务改变。

## 3. Backend Contract Changes

### 3.1 Auth

新增：

```http
GET /api/auth/bootstrap
200 { "registration_available": true | false }
```

该端点匿名可读，只投影 `count_users() == 0`，不返回管理员资料。注册接口和数据库唯一 `admin_slot` 继续处理并发首注。

管理员 CLI 新增：

```text
cd backend && uv run python -m scripts.admin_cli account reset-password
```

CLI 使用 `getpass.getpass()` 两次读取新密码，复用认证层长度校验与 PBKDF2 哈希，更新唯一管理员并在同一事务删除其全部 Session。不存在管理员、两次输入不一致或校验失败时不改变数据库。

### 3.2 Evaluation Set (`scene`)

新增：

```http
PATCH /api/scenes/{scene_id}
{ "name": "...", "description": "..." | null }
-> SceneView

DELETE /api/scenes/{scene_id}
-> 204
```

更新由 Scenes Service 统一校验空白、长度、同名和不存在。删除使用事务内原子条件：只有当前无题目时删除 Scene；级联移除凭证和零题批次回执。若并发上传已经创建题目，删除必须返回 `409 SCENE_NOT_EMPTY`，不得先删凭证再留下题目。

CLI 可复用同一 Service 增加 scene update/delete，作为备用运维入口，不拥有另一套规则。

### 3.3 Question Review Facts

新迁移 `0019_m0_web_review_contracts.py` 为 `eval_questions` 增加：

```text
criteria_confirmed BOOLEAN NOT NULL DEFAULT FALSE
ever_published     BOOLEAN NOT NULL DEFAULT FALSE
```

升级回填：

- 当前 `status='published'`：两者均为 true；
- 其他历史记录：两者均为 false，保守要求重新确认。

迁移同步覆盖 fresh DB、0018 -> 0019 升级、downgrade 和 `check_schema_ready()`。不修改历史迁移文件。

响应变化：

- `QuestionListItem` 增加 `criteria_confirmed`；
- `QuestionDetailResponse` 增加 `criteria_confirmed`、`delete_confirmation_required`；
- `delete_confirmation_required` 由 `ever_published` 派生，不直接暴露内部历史字段；
- `NextAction` 改为：`wait_for_generation`、`retry_generation`、`review_criteria`、`publish`、`published`。

状态写入：

- 批量上传、新一轮材料保存、AI 结果提交：`criteria_confirmed=false`；
- `PATCH /criteria` 成功：整体覆盖最终列表并置 `criteria_confirmed=true`；
- 发布：要求非空 criteria 且 confirmed=true，成功置 `ever_published=true`；
- AI 初稿未经老师保存时发布返回 `409 CRITERIA_NOT_CONFIRMED`。

### 3.4 Reopen Review

新增：

```http
POST /api/questions/{question_id}/review-reopen
{ "command_id": "...", "content_revision": 1 }
-> QuestionDetailResponse
```

仅允许 `published -> pending_review`。操作清空 `published_at`，保留材料、维度、revision 和 `criteria_confirmed=true`；`ever_published` 保持 true。错误状态返回 `409 REVIEW_REOPEN_NOT_AVAILABLE`，陈旧 revision 返回现有 `STALE_REVISION`。

不生成新维度、不增加状态值、不创建版本或快照。重复请求看到已非 published 后返回 409，前端随后刷新当前详情。

### 3.5 Protected Hard Delete

保留现有路径，增加 JSON 请求体：

```http
DELETE /api/questions/{question_id}
{
  "content_revision": 1,
  "confirmation_title": null
}
```

Service 规则：

- revision 不匹配：`409 STALE_REVISION`；
- generating：`409 RUBRIC_GENERATING`；
- published：`409 PUBLISHED_REOPEN_REQUIRED`；
- `ever_published=false` 且 pending_review/generation_failed：允许；
- `ever_published=true` 且已经重新打开：`confirmation_title` 经 NFC + trim 后必须与当前标题完全一致，否则 `422 DELETE_CONFIRMATION_MISMATCH`。

删除后由外键清理题目相关 OperationJob/Attempt；不得删除同场景其他题目或批次回执。

### 3.6 Credential Response Headers

签发和轮换端点在返回一次性明文时设置：

```http
Cache-Control: no-store
Pragma: no-cache
```

响应体合同不增加 token 历史字段。状态接口继续永不返回明文。

## 4. Final Question State Machine

| Current facts | User-visible state | Allowed primary action | Result |
|---|---|---|---|
| `generating` | 正在生成 | 等待 / 手动刷新 | pending_review 或 generation_failed |
| `generation_failed` | 生成失败 | 重试；也可手工建立维度 | generating 或 pending_review+confirmed |
| `pending_review`, confirmed=false | 待选择维度 | 选择/修改/新增并保存 | pending_review+confirmed |
| `pending_review`, confirmed=true | 待发布 | 继续改维度 / 发布 | pending_review 或 published |
| `published` | 已发布 | 重新打开审改；编辑材料并重新生成 | pending_review 或 generating |

材料修改优先于维度状态：一旦“保存并重新生成”成功，旧 criteria 清空且 confirmed=false。单独标题编辑不改变状态、criteria 或 confirmed。

## 5. Frontend Project Structure

```text
frontend/
├── package.json / pnpm-lock.yaml / tsconfig.json
├── next.config.mjs / playwright.config.ts / vitest.config.ts
├── public/
├── e2e/
└── src/
    ├── app/
    │   ├── (auth)/login/page.tsx
    │   ├── (auth)/register/page.tsx
    │   ├── (app)/layout.tsx
    │   ├── (app)/evaluation-sets/page.tsx
    │   ├── (app)/evaluation-sets/[sceneId]/page.tsx
    │   └── (app)/evaluation-sets/[sceneId]/questions/[questionId]/page.tsx
    ├── components/{shell,ui}/
    ├── features/{auth,evaluation-sets,questions}/
    └── lib/{api,format,ids}/
```

Feature 内保持 `components/`、`services/` 和少量本地状态 Hook。共享层只容纳确实跨页面复用的壳层、表单控件、对话框、状态标记和 API 基础设施。

依赖按 2026-09-03 稳定快照固定精确版本：Next.js 16.3.4、React 19.2.8、TypeScript 7.0.2、Playwright 1.62.1、openapi-typescript 7.13.0、lucide-react 1.40.0。实施时若同一主版本存在已知兼容问题，允许记录证据后固定到可验证补丁版本，不使用 `latest` 或浮动范围。

不引入 Tailwind、CSS-in-JS、通用 UI 组件库或全局状态框架。CSS Custom Properties + CSS Modules 负责视觉；原生 fetch 与有限 Feature Hook 负责数据，不提前建设通用缓存层。

## 6. Typed API Boundary

- `pnpm generate:api` 从 `../backend/openapi.json` 生成 `src/lib/api/generated.ts`。
- `src/lib/api/client.ts` 是唯一 fetch 包装器：相对 `/api`、JSON 解析、204、统一 `AppError`、认证失效和 AbortSignal。
- 所有 mutation 明确传 `content_revision` 与稳定客户端 `command_id`；命令 ID 用 `crypto.randomUUID()` 生成，一次提交重试复用同一值，新的用户动作生成新值。
- GET 使用 `cache: 'no-store'`；一次性凭证响应只在调用组件的局部内存中存在。
- 401 由认证边界统一处理；409/422 留给 Feature 在操作上下文展示，不做全局“成功”乐观状态。

## 7. Authentication UX

根路由先请求 bootstrap 和 `/auth/me`：

- 有有效会话 -> `/evaluation-sets`；
- 无会话且 registration_available -> `/register`；
- 无会话且已有管理员 -> `/login`。

受保护 layout 在客户端恢复会话期间显示稳定骨架；401 只跳转一次。`returnTo` 仅接受站内相对路径，防止开放重定向。

登录粒子背景从原型算法重建为确定性 Canvas：使用固定种子保证截图稳定，只在 resize 后重绘；不持续占用动画帧。`prefers-reduced-motion` 下保持静态。PNG 只用于视觉对照，不进入最终背景。

## 8. Evaluation Set And Credential UX

### 8.1 List

- `AppShell` 保留 232px / 80px 可折叠侧栏，内容区使用固定桌面最小宽度。
- 评测集颜色由 `scene_id` 的稳定哈希映射到受控多色板，不增加数据库 color 字段，也不在刷新后随机变化。
- 文件夹卡显示名称、描述、题目数和连接状态；三点菜单只包含编辑和条件允许的删除。

### 8.2 Detail

页面分为评测集概要、凭证管理带和题目列表，不在大卡片内继续嵌套卡片。

连接状态从 `credentials` 派生：

- 无凭证历史：未签发；
- 有 active 且全部 `last_used_at=null`：已签发待验证；
- 有 active 且至少一个有 `last_used_at`：已连接；
- 无 active 但有历史：已停用。

### 8.3 One-time Prompt

签发/轮换成功后生成一段提示词，模板函数接受 `scene_id`、scene name、agent API base URL 和 token。token 只出现一次。组件不把文本写入路由、query、localStorage/sessionStorage、React Query 或服务端日志。

复制优先 `navigator.clipboard.writeText()`；失败时保持文本选中区域和“请手动复制”的内联反馈。成功后按钮变为稳定尺寸的“已复制”。关闭时清空组件 state；未成功复制即关闭需二次确认。

## 9. Question List And Workbench

### 9.1 List

后端继续一次返回当前评测集内最多约 200 项。前端以不可变派生数据完成：

1. Unicode/casefold 风格的标题包含搜索；
2. 单一状态筛选；
3. `updated_at` 降序，时间相同用 `id` 保持稳定；
4. 行点击进入详情，行内主动作不与导航事件冲突。

### 9.2 Two-column Detail

```text
┌──────────────────────── material column ────────────────────────┐ ┌──── review column ────┐
│ title metadata                                                   │ │ status / next action  │
│ task prompt                                                      │ │ generation progress   │
│ reference examples                                               │ │ candidate criteria     │
│ bad cases + bound feedback                                       │ │ pass score controls    │
│ reference answer                                                 │ │ save / publish         │
│ collapsed memory materials                                       │ │ reopen / retry         │
└──────────────────────────────────────────────────────────────────┘ └───────────────────────┘
```

左栏与右栏各自滚动；右栏主要操作区 sticky，但不遮挡内容。材料阅读态和编辑态使用同一 DOM 顺序，避免切换时布局重排。

### 9.3 Candidate Draft Model

前端草稿项：

```ts
type CriterionDraft = {
  id: string;
  criterion: string;
  pass_score: number;
  selected: boolean;
  source: "ai" | "manual";
};
```

`selected` 和 `source` 只存在浏览器当前草稿，不进入 API。

- `criteria_confirmed=false`：服务端 criteria 投影为 AI 候选，全部 `selected=false`；
- `criteria_confirmed=true`：服务端 criteria 是已保存权威列表，全部 `selected=true`；
- 手工新增 ID 为 `manual-<uuid>`，仍满足后端 ID 正则；
- 保存只提交 selected 项并去掉 `selected/source`；0 项禁用，超过 20 项拒绝；
- 成功后用服务端响应替换草稿；失败保留本地编辑。

分数控件采用数值输入配合步进按钮或滑杆，始终显示 `N / 10`，键盘可操作并限制整数 0–10。完整 `criterion` 不能被单行截断为唯一阅读方式。

### 9.4 Unsaved Changes

材料或维度草稿变脏后：

- 应用内导航先弹确认；
- `beforeunload` 覆盖刷新/关闭；
- 保存中禁止重复提交；
- 409 stale 保留草稿并提供“查看最新内容”，不自动 merge 或覆盖。

## 10. Loading And Error Behavior

- 页面级加载使用稳定骨架，不用空白页或中心大 Spinner 改变布局。
- 生成中右栏按固定节奏轮询；页面 hidden 时暂停，返回 visible 时立即刷新。
- 生成失败显示 `last_error.message` 和重试；不展示 provider raw error。
- 404 区分评测集与题目不存在，并提供回到上一级。
- 删除、轮换、重新打开和发布都使用 AURA 风格确认 dialog，明确对象和结果。
- toast 只补充成功提示；字段错误、冲突和不可恢复风险留在对应面板。

## 11. Visual System

基础 token 来自原型但收敛为语义变量：page、nav、surface、surface-elevated、line、text、muted、action-purple、focus-blue、success、danger 和文件夹多色板。

- 全部正文 `letter-spacing: 0`；AURA 字标若需要分隔感，用独立字符布局和 `gap`，不用负字距。
- 工作台标题使用紧凑业务尺度，不把营销式 72px 标题复制到详情和面板。
- 卡片只用于评测集重复项与真正的工具面；页面 section 不包装成层层浮卡。
- 图标统一 lucide；图标按钮有 tooltip 与可访问名称。
- 动画只服务于状态变化、侧栏、选择和弹窗，使用 transform/opacity，支持 reduced motion。

## 12. Test Strategy

### Backend

- auth bootstrap、并发首注和本机密码重置；
- scene update、同名、空集删除、非空/并发上传拒绝和凭证级联；
- migration fresh/upgrade/downgrade 与 schema check；
- AI 生成 confirmed=false、criteria patch -> true、未确认发布拒绝；
- reopen 状态、错误来源状态、陈旧 revision；
- ever-published 删除门禁、标题匹配、生成中和发布中拒绝；
- 一次性凭证 no-store headers、授权与泄漏回归；
- OpenAPI 漂移。

### Frontend Unit/Component

- API 错误解析和认证路由；
- scene color、连接状态、题目搜索/筛选/排序；
- Agent 提示词只包含一个 token 且安全指令完整；
- candidate 初始未选、手工 ID、1–20 校验、保存 payload；
- 未保存离开保护、Safari clipboard fallback、状态面板映射。

### Browser

- Chromium 完整：首注/登录、评测集 CRUD、凭证一次性提示词、Skill 上传、生成轮询、材料编辑、维度选择/新增/保存、发布、重开、删除门禁。
- WebKit 核心：登录、评测集、复制 fallback、维度审改、发布。
- `1280x720` 两引擎无溢出；Chrome `1440x900` 截图逐页审查 AURA 一致性。
- 检查 Canvas 非空、侧栏/弹窗/双栏不重叠、长标题/长材料/20 维度等极限内容。

### Real AI Acceptance

在独立临时业务库和独立端口启动 API、恰好一个 production Worker、Next.js；使用真实 Provider 和合成安全材料：

```text
浏览器首注 -> 建评测集 -> 签发并取得提示词
-> 按提示词形成仓库外临时 Skill 配置 -> connection
-> Skill 批量上传 -> Web 观察真实动态 2–6 维度
-> 老师选择 + 手工新增 -> 保存 -> 发布
-> 重新打开 -> 调整 -> 保存 -> 再发布
```

验收输出只记录阶段、状态、数量、资源 ID 和最终 PASS 标记；不得输出材料正文、密码、Cookie、token、提示词全文或模型原始响应。

## 13. Delivery And Rollback

按依赖拆成五个顺序子任务，每个从已验证 `main` 创建独立 `codex/<slug>` 分支，完成测试、提交、fast-forward 合并、`main` 复验和分支清理后再开始下一个：

1. 后端 Web 合同与安全门禁；
2. Next.js 基础、AURA 系统和认证；
3. 评测集与凭证管理；
4. 题目列表与双栏审改；
5. 本地启动、跨浏览器与真实 AI 集成验收。

回滚按相反顺序逐子任务回退。数据库 migration downgrade 只在确认没有依赖新字段的写入后执行；前端回滚不能留下调用已回退 API 的生成类型。任何子任务失败都保留其分支，不把半完成状态带入下一个子任务。
