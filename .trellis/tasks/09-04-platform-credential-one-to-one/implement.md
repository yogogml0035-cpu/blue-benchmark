# Implement：平台凭证 1:1 模型与明文可见

分支 `codex/platform-credential-one-to-one`，worktree `../skill-eval-platform-wt/platform-credential-one-to-one`（已建、已验、`.env` 已复制）。

## 执行顺序

1. **模型 + 迁移**
   - `models.py`：`SceneCredentialRow` 加 `token_plaintext`（Text 可空）。
   - 新建 `migrations/versions/0020_credential_one_to_one.py`（幂等守卫；加列 + 存量归一）。
   - `app/lib/database/session.py`：`BUSINESS_SCHEMA_HEAD` 升到 0020，`check_schema_ready` 必备列加 `token_plaintext`（实施中发现，已补入 design）。
   - `cd backend && uv run alembic upgrade head` 验证；`python -m scripts.check_schema` 验证与模型一致。
2. **repository**
   - `create_credential(..., plaintext)` 写入新列；`revoke_credential` / `revoke_scene_credentials` 置 `token_plaintext=NULL`；`SceneCredentialRecord` 增 `token_plaintext`；新增 `get_active_credential(session, scene_id)`（取唯一有效凭证）。
3. **service + schemas**
   - `create_or_replace_credential` 取代 issue/rotate；`revoke_credential`、`get_scene_or_404`（单凭证）、新增 `get_active_credential_plaintext`；`_credential_record` 映射。
   - `schemas.py`：`SceneCredentialStatusView.token_preview`；`SceneStatusResponse.credential`；新增 `SceneCredentialPlaintextView`。
4. **router**
   - `POST /credentials` 切到 `create_or_replace_credential`；删 `/rotation`；新增 `GET /{scene_id}/credential`（`no-store`）。
5. **admin CLI**：`replace` 取代 `issue`/`rotate`；`status` 单凭证。
6. **openapi + 前端生成类型**：`make openapi`、`cd frontend && pnpm generate:api`。
7. **前端**：`api.ts`（`createOrReplaceCredential`/`revealCredential`，删 rotate）→ `connection.ts` 单凭证 → `credential-panel.tsx` 重写（单按钮 + 掩码 + 小眼睛）→ `page.tsx` 适配 → `prompt-dialog.tsx` 文案。
8. **测试**：按 design 测试计划改写；`test_migration.py` 加 0020 用例。
9. **验收脚本**：`accept_skill_push_evaldata.py` 调用改 `create_or_replace_credential`。
10. **质量门**（见下）。
11. **提交 + 合并 + 复验 + 收尾**。

## 质量门

```bash
cd backend && uv run pytest -q
make test
make build
git diff --check
# 旧语义清扫：
git grep -n "credentials/rotation\|rotateCredentials\|rotate_credentials\|issue_credential" -- ':!.trellis' 
git grep -n "credentials\":" backend/app frontend/src | grep -v credential  # 列表字段残留
```

## 检索范围（完成门禁）

- `credentials/rotation`、`rotateCredentials`、`rotate_credentials`、`issue_credential`：除 `.trellis/` 任务文档外零命中。
- `SceneCredentialIssuedView` docstring、CLI 帮助、前端“明文仅显示一次”类文案：全部更新为新模型。

## 回滚点

每步独立可退；合并前整体回滚 = 放弃 worktree 分支。迁移回滚见 design。
