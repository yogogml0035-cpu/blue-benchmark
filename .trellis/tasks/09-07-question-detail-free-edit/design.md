# Design — 题目详情自由编辑与全站字体改版

## D1 核心决策：保存与生成彻底解耦，`content_revision` 语义保持"生成轮次版本"

- `content_revision` 只在开新生成轮时推进（重新生成 +1；generation-retry 沿用现状不推进）。
- 材料自动保存：原地更新六件套文本，**不推进 revision、不动 criteria、不入队任何生成**。
- 依据失配检测与 revision 无关：直接用文本匹配（见 D4），材料改动不推进 revision 也不影响检测正确性。
- 并发模型：单管理员内部工具，last-write-wins；请求带 `content_revision` 仅用于跨生成轮的 stale 防护（与 retry/publish 现有 CAS 一致）。

## D2 接口契约

### 新增 `PATCH /api/questions/{question_id}/materials`

请求 `QuestionMaterialsPatchRequest`（extra=forbid）：

```
content_revision: int (ge=1)          # CAS，等于当前值才接受
task_prompt?: str                      # 以下全部可选，None=不更新
reference_answer?: str
reference_examples?: list[ReferenceExampleIn]    # 显式传=整列表替换
bad_cases?: list[BadCaseIn]
memory_materials?: list[MemoryMaterialIn]
```

- item 模型复用现有 `ReferenceExampleIn`（含 client_ref_id/source_name）/`BadCaseIn`/`MemoryMaterialIn`，校验（strip、长度、id 唯一）全部继承。
- 行为：`_ensure_not_frozen` + 与现 save_and_regenerate 相同的状态资格门（生成中禁止编辑）；CAS `expected_revision=content_revision` 原地更新，**revision 不变**；不入队。
- 响应：`QuestionDetailResponse`（新增 `criteria_basis_stale` 字段，见 D4）。

### 新增 `PATCH /api/questions/{question_id}/criteria/{criterion_id}`

请求 `CriterionPatchRequest`（extra=forbid）：

```
content_revision: int (ge=1)
criterion?: str          # 评分标准文本
pass_score?: int         # 0–10
score_anchors?: list[ScoreAnchorIn]   # 分数表现说明整组替换
```

- 按 `criterion_id` 在 `criteria_json` 列表内定位（id 即 `CriterionView.id`/候选 `client_ref_id`）；找不到 → 404。
- 只更新出现字段；**不改 selected 标志、不动 `criteria_confirmed`、不丢未入选候选**；`criterion_basis`/`pass_score_basis` 本任务不可编辑（与现状一致）。
- 资格门与 materials 相同；CAS 同上；revision 不变。
- 响应：`QuestionDetailResponse`。

### 新增 `POST /api/questions/{question_id}/regenerate`

- 请求复用 `QuestionCommandRequest`（command_id + content_revision，与 retry/publish 同款）。
- 行为 = 现 `save_and_regenerate` 的生成半段：资格门 → `new_revision = content_revision + 1` → 清空 `criteria_json`/`criteria_confirmed` → `enqueue_generation(command_id=derived_command_id("regenerate", question_id, str(new_revision), payload.command_id))` → status=generating。
- 响应：`OperationAcceptedResponse`（与 retry 一致）。

### 删除 `POST /api/questions/{question_id}/save-regenerate`

- 删 router 条目、`service.save_and_regenerate`、`QuestionSaveRegenerateRequest`；其材料校验职责由 `*In` 模型在新接口自然继承；其"仅标题"轻量分支已由现有 `/title` 接口承担（保留）。
- 前端删 `saveRegenerate` 封装与 `QuestionSaveRegenerateRequest` 类型。

### 标题自动保存

- 用例标题沿用现有 `PATCH /{question_id}/title`（`QuestionTitleRequest`：command_id + content_revision + title），前端失焦调用。command_id 前端生成 uuid。

### R1 凭证 label 删除

- `SceneCredentialRow.label`（`models.py:96`）、`SceneCredentialIssueRequest.label`、`_validate_label`、`SceneCredentialStatusView.label`、`SceneConnectionStatusView.label` 全删。
- 迁移 `0022_drop_scene_credential_label`：upgrade 用幂等守卫（先查 information_schema 列存在再 drop，防全新库重放报错）；downgrade 加回列。检查 `BUSINESS_SCHEMA_HEAD` 常量是否需要随表结构同步（0020 有先例）。
- 带多余 `label` 字段的旧请求体因 extra=forbid 会 422——可接受（无真实调用方传过 label，前端从不传）。

## D3 前端结构

### page.tsx（题目详情页）

- 删除：`editingMaterials`、`materialDraft`、`startEditMaterials`、`handleSaveMaterials`、材料保存确认弹窗、「编辑材料」按钮。
- 新增：header「重新生成」按钮（「删除题目」旁，确认弹窗文案："将作废当前全部评分维度候选与已确认结果，基于已保存材料重新生成。确定继续？"）→ `regenerate()` → 现有生成轮询/刷新流程。
- 数据流：`detail`（含 `criteria_basis_stale`）为唯一权威； MaterialsPanel/CriteriaEditor 通过回调上报保存，成功后以响应 detail 就地更新。

### MaterialsPanel

- 每个模块（题目/标准答案/每个参考文本/每个 bad case/每条记忆）包一层模块容器：阅读态默认；hover 时边框高亮 + 右上角浮现铅笔 icon button；容器 `onDoubleClick` 同样进入编辑态。
- 编辑态：就地 `textarea`（复用 AutoGrowTextarea）；失焦时值未变则静默退出，变了则调用保存；保存中显示行内 spinner，失败显示"保存失败 · 重试"（点击重发）。
- 保存映射：题目/标准答案 → materials PATCH 单字段；参考文本/bad case/记忆 → materials PATCH 整列表（前端持有全列表，替换单项后整体提交）。
- 用例标题：header 标题点击 → 行内 input，失焦走 `/title`。

### CriteriaEditor

- 删除 `readOnly={!d.selected}` / `disabled={!d.selected}` 门控（评分标准 textarea、通过分 input、锚点行）。
- 勾选框只改本地草稿 selected；内容失焦 → `PATCH /criteria/{id}`（服务端成功后同步本地）。
- 「保存维度」按钮与确认弹窗保留（最终确认 + 丢弃未入选候选语义不变）。
- `criteria_basis_stale === true` 时，标题行下方渲染提醒条："材料已修改，部分维度依据引用的原文已过期，建议重新生成或检查依据。"

### credential-panel.tsx

- 删除名称行（`itemLabel`）与「未命名凭证」兜底；停用按钮 aria-label 用掩码 token（`token_preview`）。

### 布局

- 右列标题行改 flex：`评分维度`（左）+「查看完整生成过程」ghost 按钮（右）同行；核对两列首行顶对齐（margin/padding 归零对齐）。

## D4 依据失配检测

- 服务端函数 `compute_basis_stale(row) -> bool`：`locator_texts = build_locator_texts(build_generation_input(row))`（现 patch_criteria 校验同款）；遍历 `criteria_json` 全部项的 `criterion_basis`/`pass_score_basis` 的 claims citation（locator/quote），任一文本无法在 `locator_texts` 中命中 → True。
- 调用点：`get_detail`、materials PATCH 响应、criterion PATCH 响应（后两处直接复用 get_detail）。无 `criteria_json` 时恒 False。

## D5 字体 token 体系

`globals.css` `:root` 新增（与现有颜色/圆角 token 同区域）：

```
--font-size-xs: 13px;   /* 原 11px */
--font-size-sm: 14px;   /* 原 12px */
--font-size-md: 15px;   /* 原 13px */
--font-size-base: 16px; /* 原 14px，body 基准 */
--font-size-lg: 17px;   /* 原 15px */
--font-size-xl: 18px;   /* 原 16px */
--font-size-2xl: 20px;  /* 原 18px */
--font-size-3xl: 22px;  /* 原 20px */
```

- `body { font-size: var(--font-size-base); line-height: 1.7; }`。
- 全仓 CSS Module 内 `font-size: Npx` 按映射表替换为对应 var()；`auth-form.module.css` 的 `clamp(30px,3vw,43px)` 与登录页大字排除；替换后人工过目 diff，防止命中非字号 px（padding 等不受影响，只匹配 font-size 行）。
- 组件内显式 `line-height` 逐一过目：正区块跟随 1.7，紧凑控件（按钮/徽章）保持原值。
- 溢出修复：全页面截图回归（登录/评测集列表/凭证面板/题目详情各状态/批量/后台），发现破版逐处修。

## D6 回滚

- 代码：git revert（任务分支未合并前直接丢弃分支）。
- 数据库：`alembic downgrade -1`（0022 带 downgrade）；label 恒 NULL 无数据损失，downgrade 无回填需求。
- 新接口对旧前端无用例依赖（同分支同步发布）。

## D7 完成前定向检索清单

`save-regenerate`、`saveRegenerate`、`QuestionSaveRegenerateRequest`、`editingMaterials`、`materialDraft`、`编辑材料`、`未命名凭证`、scenes 域 `label`、`_validate_label`；另查验收脚本（`accept_skill_push.py`、`accept_real_ai_rubric.py`、`frontend/scripts/real-acceptance.mjs`）与 README/部署文档是否引用旧接口或 label。剩余命中必须逐项确认不可执行。
