# 技术设计：前端工作台交互与 UI 真实验收修复

## Change boundary

最小行为差距有四处：预演 fixture 仍触发 `useSession`；工作台把低频 Agent 连接设置置于当前下一步之前；全局主动作 token 与批准的设计系统漂移；rubric 将内部评分项 ID 直接显示给业务老师。审计还确认旧 Case Builder 前端文件已没有活动路由引用，属于可删除的死代码。

行为实际所有者分别是 `useSession`、`StudioPage`/`StudioShell` 的组合、`globals.css` 与 rubric `CriterionEditor`，而不是通过测试或单个按钮拦截。变更范围限定为：

- `frontend/src/features/auth/hooks/useSession.ts` 及带预演状态的调用方：增加显式 `skip`，预演返回匿名哨兵状态但不发请求；
- `StudioPage`、`StudioShell`、`CurrentSection` 和 `AgentConnectionPanel`：复用一次 Session，把连接卡放到当前主流程之后；
- `frontend/src/app/globals.css`、rubric 组件：恢复 `--action` 主动作和隐藏内部 ID；
- 现有前端预演 E2E：把无真实 API 请求和页面顺序写成断言；
- `backend/scripts/accept_real_ai_e2e.py`、`accept_external_authoring.py`：本地验收 HTTP 客户端直连 loopback，避免系统代理造成测试前置假失败；
- 删除已无活动引用的旧 Case Builder 展示组件、旧 service、旧状态映射、旧 fixture 及其专用 CSS。

明确不做：不改 FastAPI 路由/OpenAPI/数据库/Worker 业务实现或版本包；不引入全局状态库、React Query、第二套组件库或真实 AI mock；不删除后端仍被测试和新服务依赖的历史数据/读路径。

## Runtime design

`useSession({ skip: true })` 在 effect 中直接收敛为匿名状态，避免把预演伪装成真实登录。带 `preview` 的页面在调用 Hook 时传入 `skip: Boolean(preview)`；所有会读业务资源的 effect 已经以 `preview` 先返回，因此不会继续调用 Service。真实页面保持原有 `loading → authenticated/anonymous/failed` 语义。

工作台由 `useStudioData` 作为唯一 Session 所有者，`StudioShell`、`CurrentSection` 和连接卡消费同一个结果。`StudioShell` 不再自己发起第二次 Session 请求；连接卡移到 `CurrentSection` 的主内容之后，并只在 `StudioPage` 已经进入 ready projection 时挂载。这样 loading/error 状态不会显示设置卡，也不会额外暴露私有内容。

## Visual design

- 现有浅色中性系统不变；`--action: #1d1d1f` 作为唯一主操作填充色，`--accent` 继续用于链接/焦点/当前导航/进度。
- 连接卡回到普通 `sheet` 深度，只用低对比边界，不以蓝色边框和蓝色影子争夺“当前”焦点。
- rubric 评分项保留稳定 DOM `id` 和 test locator，但公开副标题仅显示“评分项 01”，不渲染 API 内部 ID。
- 删除重复 CSS 声明；不新增动画，不改变现有 reduced-motion 退化。

## Failure and recovery

预演后端关闭时应完全没有网络错误；真实页面仍由 Session/Service 处理未授权、失败和恢复。主流程加载失败时不渲染连接操作，避免在一个失效页面继续发起另一个私有请求。真实本地验收脚本关闭 `httpx` 的环境代理继承，保证 loopback 请求直达当前 API；不改变服务端 CAS、幂等、Worker 或版本状态。

## Verification

先跑预演 Playwright 并监听请求/console，再跑 typecheck、完整 `make test`、`make build`；之后启动隔离的 PostgreSQL、Checkpointer、真实 Provider Worker，使用 EvalData 跑真实浏览器链路和冒烟。最后对权限、旧响应、重复提交、窄屏、内部 ID 泄漏和死引用做对抗复查。
