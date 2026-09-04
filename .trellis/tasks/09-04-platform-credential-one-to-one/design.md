# Design：平台凭证 1:1 模型与明文可见

## 一次性切换边界

新语义（1:1 + 明文可看）整体替代旧语义（多凭证并存 + 明文一次性），不保留兼容层：`/credentials/rotation` 端点、`issue_credential`/`rotate_credentials` 双函数、`credentials: list` 响应字段、CLI `issue`/`rotate` 子命令全部删除。

## 数据模型

`SceneCredentialRow` 新增一列：

```python
token_plaintext: Mapped[str | None] = mapped_column(Text, nullable=True)
```

- 签发时与 `token_hash` 同时写入（哈希仍用于认证查找，认证路径不变）。
- 撤销/替换时置 `NULL`：作废凭证不保留明文（缩小静态暴露面，也保证界面语义“只有当前凭证可看”）。
- 旧模型存量行该列为 `NULL`（明文从未存储、不可恢复），用 `revocable=True` 的现有行语义自然区分“可查看/不可查看”。

## 迁移 `0020_credential_one_to_one.py`

遵循现有迁移的幂等守卫风格（inspector 判重，见 0019）：

1. `scene_credentials` 加 `token_plaintext` 列（TEXT，可空）。
2. 存量 1:1 归一：对每个场景，若有效凭证（`revoked_at IS NULL`）多于一张，保留 `created_at` 最新一张，其余置 `revoked_at=now、revoked_reason='model-migration'`。SQLite/Postgres 均用逐行 UPDATE 实现（数据量小，不追求单语句）。
3.  downgrade：删列（SQLite 用 batch_alter_table）；归一化不逆向（撤销不可逆，符合 PRD）。

## 服务层（`features/scenes/service.py`）

```python
def create_or_replace_credential(scene_id, label) -> SceneCredentialIssuedView:
    # 场景存在性检查 → revoke_scene_credentials(reason="replaced")
    # → create_credential(hashed, plaintext, label) → 返回一次性视图
```

- 删除 `issue_credential` 与 `rotate_credentials`（调用方全部切到 `create_or_replace_credential`：router、admin CLI、验收脚本、测试助手）。
- `revoke_credential` 保留，撤销时同步清空 `token_plaintext`（repository 层 `revoke_credential` 与 `revoke_scene_credentials` 均置 NULL）。
- `get_scene_or_404`：`credentials` 列表 → `credential: SceneCredentialStatusView | None`（仅当前有效凭证；无则 None）。`SceneStatusResponse` 同步改字段。
- 新增 `get_active_credential_plaintext(scene_id) -> SceneCredentialPlaintextView`：无有效凭证抛 `AppError(404, "NO_ACTIVE_CREDENTIAL", ...)`；有效凭证 `token_plaintext` 为 NULL（旧模型存量）时抛 `AppError(409, "CREDENTIAL_PLAINTEXT_UNAVAILABLE", "该凭证签发于旧版本，明文不可查看；请替换凭证。")`。
- `SceneCredentialStatusView` 增加派生字段 `token_preview: str | None`：有明文时 `sep_` 前 7 位 + `…` + 后 4 位；无明文时 None（前端显示“不可查看”文案）。掩码视图**永远不含完整明文**。

## API 合同（`features/scenes/router.py` + `schemas.py`）

| 变更 | 端点/字段 |
|---|---|
| 语义改变 | `POST /scenes/{id}/credentials` → 创建或替换（201，返回一次性明文视图，`no-store`） |
| 删除 | `POST /scenes/{id}/credentials/rotation` |
| 新增 | `GET /scenes/{id}/credential` → `{credential_id, token}`，`no-store`；404/409 见上 |
| 修改 | `SceneStatusResponse.credentials: list` → `credential: SceneCredentialStatusView \| None` |
| 修改 | `SceneCredentialStatusView` 增 `token_preview` |
| 保留 | `DELETE /scenes/{id}/credentials/{credential_id}`（撤销，现同步清明文） |

`SceneCredentialIssuedView` 的 docstring 从“plaintext is never stored”改为“plaintext is persisted for admin viewing; response is one-time for handoff convenience”。

OpenAPI：`make openapi` 重新生成 `backend/openapi.json`；前端 `pnpm generate:api` 同步 generated 类型。

## admin CLI

- `credentials issue` / `credentials rotate` → 合并为 `credentials replace`（调用 `create_or_replace_credential`）。输出后的 stderr 提示改为：“明文已持久化，可稍后在场景页查看；仍建议现在交给 Agent 完成绑定。”
- `credentials revoke` 保留；状态查询沿用 `scenes status`（`SceneStatusResponse.credential` 已改为单凭证视图）。

## 数据库合同守卫

`app/lib/database/session.py::BUSINESS_SCHEMA_HEAD` 与 `check_schema_ready()` 的 `scene_credentials` 必备列清单同步升到 0020（加入 `token_plaintext`）；否则 `make db-check` 拒绝新 head。

## 前端

### `api.ts`
- 删除 `rotateCredentials`；`issueCredential` 更名 `createOrReplaceCredential`（同一端点）。
- 新增 `revealCredential(sceneId)` → `GET /api/scenes/{id}/credential`，返回 `{credential_id, token}`。
- `SceneStatusResponse` 类型经 generated 更新为单 `credential`。

### `credential-panel.tsx`（重写）
- Props：`credential: SceneCredentialStatusView | null`（不再是数组）。
- 头部单按钮：`credential == null || status !== "active"` → “创建凭证”；有有效凭证 → “替换凭证”（确认对话框文案沿用轮换警示：旧凭证立即失效、已绑定 Agent 需重新绑定）。
- 凭证卡片：掩码预览（`token_preview`，None 时显示“签发于旧版本，明文不可查看”）、签发/最近使用时间、小眼睛切换按钮。
- 小眼睛交互：点开 → 调 `revealCredential` 取明文并展示（组件内存，关闭/卸载即弃）；再次点击收起。409（旧凭证不可查看）时按钮禁用并给文案。
- 撤销按钮与确认对话框保留（停用唯一凭证）。

### `connection.ts`
- `deriveConnectionStatus` 入参从数组改为单个 `SceneCredentialStatusView | null`：null→`unsigned`；active 且已用→`connected`；active 未用→`issued`；revoked→`disabled`。
- `logic.test.ts` 对应用例改写。

### `page.tsx`
- `status.credentials` → `status.credential`；`active_credential_count` 文案保持（0/1）。

### `prompt-dialog.tsx`
- 保留。关闭时“凭证只能通过轮换重新生成”文案改为“替换凭证”表述。

## 测试计划

- `test_scenes.py`：`test_scene_lifecycle_and_credential_plaintext_rules` 重写为 1:1 语义（创建→状态单凭证→替换→旧 token 401→`GET /credential` 明文一致→撤销→`GET /credential` 404）；新增掩码/`no-store`/列表接口无明文断言；删除 rotation 端点用例。
- `test_migration.py`：0020 加列幂等 + 多有效凭证归一（保留最新）+ 单凭证场景不动。
- `test_batch_upload.py` / `helpers.py`：`issue_credential` 助手沿用同一端点（语义变为创建/替换，调用处无需改签名）。
- 前端 `logic.test.ts`：`deriveConnectionStatus` 单凭证化；`buildAgentBindingPrompt` 不动。
- 验收脚本 `accept_skill_push_evaldata.py`：`scene_service.issue_credential` 调用改 `create_or_replace_credential`。

## 回滚方式

`git revert` 本任务提交 + `alembic downgrade -1`（删列；归一化不可逆但无数据丢失风险——被归一凭证本就将被新模型作废）。

## 风险

- 明文列使数据库备份等价于凭证库（需求方已确认接受）。撤销清明文缓解静态残留。
- 旧凭证不可查看可能令管理员困惑——界面文案明确指引“替换凭证”。
