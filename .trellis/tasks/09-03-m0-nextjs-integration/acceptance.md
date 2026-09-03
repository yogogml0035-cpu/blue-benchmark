# M0 Next.js 前后端交互 — 最终验收记录

验收日期：2026-09-03
验收范围：合并后的 `main`（五个子任务全部合并归档 + 最终清理）。

## 子任务闭环

| 子任务 | 内容 | 状态 |
|---|---|---|
| m0-web-backend-contracts | 后端 Web 合同与安全门禁（0019 迁移、确认门禁、重开、受保护删除、密码重置） | 已合并归档 |
| m0-nextjs-shell-auth | Next.js 壳层、类型化 API 边界、AURA 认证 | 已合并归档 |
| m0-evaluation-set-credentials-ui | 评测集文件夹、凭证生命周期、一次性提示词 | 已合并归档 |
| m0-question-review-ui | 题目列表、双栏审改工作台 | 已合并归档 |
| m0-local-integration-acceptance | 本地三进程集成、真实 AI Web 验收 | 已合并归档 |

每个子任务均完成"独立分支 → 质量门 → 提交 → fast-forward 合并 → main 复验 → 归档 → 删除分支"闭环；每个子任务经 2 轮以上对抗式审查并修复。

## AC 逐项证据

- **AC1（首注/登录/会话，真实 Cookie）**：`e2e/01-auth-register.spec.ts`、`e2e/02-auth-login.spec.ts`（chromium + webkit + chromium-minimum）——空库首注、注册关闭、用户名/邮箱登录、会话跨刷新保持、登出、受保护路由 401 反弹带 returnTo。全部通过。
- **AC2（本机密码重置）**：`backend/tests/test_auth_web_contracts.py` 5 处 reset-password 测试——隐藏输入、不泄露、重置后旧密码/会话失效、新密码可登录。通过。
- **AC3（评测集创建/改名/空删）**：`e2e/03-evaluation-set-credentials-ui` 创建/改名/空删；后端 `test_scenes.py` 非空删除 409、同名 409、凭证级联失效。通过。
- **AC4（凭证签发/轮换/撤销 + 一次性提示词）**：`e2e/03`（签发/轮换/撤销、轮换后旧凭证 401）；后端 `test_scenes.py` no-store 头、状态接口不含明文；提示词 token 恰一次、关闭清空、不进 URL/存储；秘密扫描确认无泄漏。通过。
- **AC5（题目仅经上传 Skill）**：无手工建题端点；`e2e/03`/`04` 均经 `/api/external/question-batches` 上传；无跨评测集入口。通过。
- **AC6（20 评测集 + 列表搜索/筛选/排序）**：`e2e/03` 20 卡片网格两视口；`frontend/src/features/questions/list-ops.ts` 归一化搜索/单状态筛选/稳定排序（单测）；对抗审查实测 200 行无溢出。通过。
- **AC7（双栏详情两视口无溢出）**：`scripts/screenshot-workbench.mjs` 于 1280x720/1440x900 截图，judge 视觉验收通过（双栏、记忆折叠、无溢出）；`e2e/04` 双栏交互。通过。
- **AC8（材料编辑/保存重生成/陈旧保护）**：`e2e/04` + 后端 `test_question_library_api.py`（保存重生成作废旧维度、陈旧 revision 409 保留草稿）；`material-draft.ts` 单测（仅改标题走 updateTitle）。通过。
- **AC9（真实 AI 动态 2–6 候选，初稿未选）**：`make accept-web` 真实 Provider 生成 3–4 项（2–6 内）；`e2e/04` 候选首次全未选、0 项不能保存/发布；Fake 仅作确定性测试不作真实验收。通过。
- **AC10（维度选择/修改/新增 + 0–10 + 1–20）**：`e2e/04`（勾选/保存）；`criterion-draft.ts` 单测（1–20、ID 唯一、0–10 整数、≥8 字符）。通过。
- **AC11（保存/发布分离 + 重开）**：`e2e/04` 保存→发布→重开→再发布；重开保留材料/维度、清发布态；无版本历史。通过。
- **AC12（删除门禁）**：`e2e/04` + 后端删除测试——生成中禁删、未发布确认删、已发布先重开、曾发布需标题二次确认、不可恢复。通过。
- **AC13（Chrome 完整 + Safari/WebKit 核心 + 视口）**：`pnpm test:e2e` 41 项（chromium 完整 25 + chromium-minimum 8 + webkit 8）；judge 对登录/注册/评测集/工作台截图（1280x720 与 1440x900）视觉验收通过。通过。
- **AC14（全质量门）**：`git diff --check`、`make test`（后端 83 + 前端 73）、`make build`、`make contract-check`、`make frontend-check-api`、`make frontend-e2e`、Skill 隔离测试（38）全部通过。通过。
- **AC15（隔离库真实链路）**：`make accept-web` 输出 `M0_WEB_ACCEPTANCE=PASS`——隔离临时库 + 单 production Worker + 真实 Provider，网页首注→评测集→凭证提示词→上传→真实动态维度→保存→发布→重开→再发布；输出仅阶段/计数/ID，无密码/Cookie/token/提示词全文/材料正文。通过。

## 质量门最终结果（合并后 main）

- `git diff --check`：通过（含最终 EOF 清理）。
- `make test`：后端 83 + 前端 73 单测通过，OpenAPI 合同与生成类型无漂移。
- `make build`：后端编译/导入 + 前端生产构建通过。
- `make frontend-e2e`：41/41 通过，无孤儿进程。
- `make accept-web`：`M0_WEB_ACCEPTANCE=PASS`，无孤儿进程。
- Skill 隔离测试：38 通过。
- 秘密扫描：无真实 `sep_` token、无硬编码 AI_API_KEY/生产库密码入库（测试夹具假值除外）。

## 最终对抗审查与清理

经多轮对抗式审查（安全/并发/合同/可访问性/文档一致性/集成与清理），修复了：会话代际竞态、条件更新门禁、一次性凭证清理、Makefile 进程清理（exec）、提示词注入净化、死代码与 EOF 卫生等。最终清理删除后端 5 处死代码、前端 1 处重复实现，统一 9 个文件 EOF 换行。

## 本地边界

平台仅面向当前本机：单管理员、单生产 Worker、本地数据库；不含公网部署、HTTPS、Docker/CI/CD、移动端。
