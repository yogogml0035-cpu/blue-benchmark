# Implement — 题目详情自由编辑与全站字体改版

工作目录：`/Users/hsikey/Company/blue-benchmark-wt/question-detail-free-edit`（分支 `codex/question-detail-free-edit`，基线 `main@38a8031`）。`.env` 已复制。每个阶段一个 commit 批次，阶段门通过才进下一阶段。

## 阶段 1：后端凭证 label 整条删除

- [ ] 删除 `SceneCredentialIssueRequest.label`（`backend/app/features/scenes/schemas.py:77-81`）、`_validate_label`（`service.py:180-190`）及调用点、`SceneCredentialStatusView.label`、`SceneConnectionStatusView.label`（`service.py:141,278`）。
- [ ] 删除 `SceneCredentialRow.label`（`backend/app/lib/database/models.py:96`）；检查 `BUSINESS_SCHEMA_HEAD` 常量是否需同步。
- [ ] 新增迁移 `0022_drop_scene_credential_label`（幂等守卫：列存在才 drop；downgrade 加回）。
- [ ] 前端 `credential-panel.tsx`：删名称行/「未命名凭证」兜底（`:134`）、aria-label 兜底改 `token_preview`（`:176`）；`generated.ts` 类型待阶段 1 末再生成后自然收敛。
- [ ] 测试：改写/删除 label 相关断言；新增"签发请求带 label 字段 → 422"与"迁移后列不存在"回归。
- [ ] 验证：`make openapi` → `make frontend-generate-api` → `make test`（后端 + 前端单测）。
- [ ] commit: `feat(scenes): drop dead credential label field across stack`

## 阶段 2：后端接口解耦

- [ ] `schemas.py`：新增 `QuestionMaterialsPatchRequest`、`CriterionPatchRequest`（结构见 design D2）；`QuestionDetailResponse` 加 `criteria_basis_stale: bool`。
- [ ] `service.py`：
  - 新 `update_materials(question_id, payload)`：资格门（复用现 save_and_regenerate 的状态门与 `_ensure_not_frozen`）→ CAS 原地更新可选字段 → 不动 revision/criteria/队列 → 返回 `get_detail`。
  - 新 `patch_criterion(question_id, criterion_id, payload)`：定位 criteria_json 项 → 字段更新 → 不动 selected/confirmed/候选 → 返回 `get_detail`。
  - 新 `regenerate(question_id, payload)`：save_and_regenerate 的生成半段（revision+1、清空维度、enqueue "regenerate"、status=generating）→ `OperationAcceptedResponse`。
  - 新 `compute_basis_stale(row)`（design D4），接入 `get_detail`。
  - 删除 `save_and_regenerate`、`QuestionSaveRegenerateRequest`、router 的 `/save-regenerate` 条目。
- [ ] 测试：三新接口正向（落库内容、revision 不变、无新 operation、basis_stale 标记翻转）+ 否定（404/409/资格门/旧 save-regenerate 404）+ 并发 CAS。真实 AI 链路测试按现有约定走真实生成（不 mock）。
- [ ] 验证：`make openapi` → `make frontend-generate-api` → `make test`。
- [ ] commit: `feat(questions): split material autosave from rubric regeneration`

## 阶段 3：前端题目详情页重构

- [ ] `api.ts`：删 `saveRegenerate`/`QuestionSaveRegenerateRequest`；增 `updateMaterials`/`patchCriterion`/`regenerate` 封装。
- [ ] `page.tsx`：删页面级编辑模式与「编辑材料」；header 加「重新生成」（确认弹窗）；`criteria_basis_stale` 透传。
- [ ] `materials-panel.tsx`：模块容器 hover 边框高亮 + 铅笔按钮 + 双击；就地 textarea；失焦自动保存（无变化跳过；spinner/失败重试）；用例标题行内编辑。
- [ ] `criteria-editor.tsx`：删三处 readOnly/disabled 门控；内容失焦字段级保存；勾选仅绑定；提醒条渲染。
- [ ] 布局：标题行合并（标题左、生成过程按钮右）、两列首行顶对齐。
- [ ] 自动保存并发防护：模块级"保存中再失焦"排队（串行 promise chain），避免乱序覆盖。
- [ ] 验证：`pnpm -C frontend lint`、`pnpm -C frontend build`（生产构建，本机 dev server 不可靠）。
- [ ] commit: `feat(frontend): free-edit materials with autosave and standalone regenerate`

## 阶段 4：全站字体 token

- [ ] `globals.css`：新增 `--font-size-*` token（design D5 映射）；body 16px / line-height 1.7。
- [ ] 全仓 CSS Module `font-size: Npx` → var() 替换（映射表）；`auth-form.module.css` clamp 排除；逐 diff 过目。
- [ ] 显式 line-height 逐处过目；溢出破版逐处修（表格/徽章/状态条优先）。
- [ ] 验证：`pnpm -C frontend build` + 全页面截图回归（复用 zz-spec 临时配置打法，跑完删除临时文件）。
- [ ] commit: `feat(frontend): site-wide font-size tokens, base 16px, line-height 1.7`

## 阶段 5：全量验收与收尾

- [ ] 质量门：`git diff --check`、`make test`、`make build`。
- [ ] E2E：生产构建 + `E2E_PORT` 换端口跑全套（改动相关 spec 必过；不再存在的注册/旧编辑模式断言同步改写）。
- [ ] 截图视觉验收：题目详情（阅读/编辑态、提醒条、重新生成弹窗）、凭证面板、列表页、登录页。
- [ ] 定向检索（design D7 清单）逐项确认无可执行旧路径；验收脚本（`accept_*.py`、`real-acceptance.mjs`）如引用旧接口/label 同步改写。
- [ ] 文档同步：README/server-setup 等涉及「编辑材料/保存并重新生成/凭证名称」的段落改为新口径。
- [ ] 对抗审查（每阶段 implement 后 check，最后全量 check 一轮）。

## 回滚点

- 每阶段 commit 即回滚边界；0022 迁移 `alembic downgrade -1`。
- 阶段 2 未过门禁时不得进入阶段 3（前端类型依赖新 openapi）。
