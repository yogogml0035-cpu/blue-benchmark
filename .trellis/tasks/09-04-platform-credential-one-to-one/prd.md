# PRD：平台凭证 1:1 模型与明文可见

## 背景与目标

平台的场景上传凭证目前允许一个场景同时持有多张有效凭证，明文只在签发响应里出现一次，数据库仅存哈希。需求方（管理员）的使用模型是：**一个场景的凭证由团队共享，且管理员事后需要能看到、核对并重新取用当前凭证**（用于绑定新的技能副本、分发给同事）。

本任务把凭证模型改为：

1. 凭证与场景**严格一对一**：任一时刻一个场景最多一张有效凭证。
2. **创建/轮换合并为单一动作**：没有凭证时是“创建凭证”，已有凭证时是“替换凭证”（旧凭证立即作废，新凭证生效）。
3. **凭证明文持久化并可查看**：数据库存储明文（需求方明确接受该安全降级，裸明文即可）；场景页默认掩码显示，点小眼睛展开完整明文。
4. **只展示当前有效凭证**：被替换/撤销的旧凭证不在界面出现，无历史列表。
5. 签发时的**一次性提示词保留**（管理员把凭证交给 Agent 绑定的入口），提示词内容沿用任务 1 改好的绑定指引。

## 旧语义（不再支持）

- `POST /api/scenes/{id}/credentials` 的“可重复签发、多张并存”语义删除；该路径改为单一的创建/替换动作。
- `POST /api/scenes/{id}/credentials/rotation` 端点删除（其语义并入单一动作）。
- 场景详情响应中的 `credentials` 列表字段删除，替换为 `credential`（单个，可为空）。
- admin CLI `credentials issue` / `credentials rotate` 两个子命令合并为 `credentials replace`。
- “明文只显示一次、绝不存储”的旧安全文案全部更新为新模型表述。
- 前端凭证面板的多凭证列表、独立的“轮换凭证”按钮删除。

## 新行为

### 后端

1. `SceneCredentialRow` 新增 `token_plaintext` 列（可空）：签发时写入明文；凭证被撤销/替换时清空为 NULL（作废凭证不保留明文）。
2. 单一服务动作 `create_or_replace_credential(scene_id, label)`：作废该场景全部有效凭证（reason=`replaced`），创建新凭证（哈希 + 明文同存），返回含明文的一次性视图。
3. `GET /api/scenes/{id}`：返回 `credential`（当前有效凭证的掩码状态视图；无凭证时为 null）。已撤销凭证不返回。
4. 新增 `GET /api/scenes/{id}/credential`：返回当前有效凭证的**完整明文**（管理员查看用，`no-store` 响应头）；无有效凭证时 404 `NO_ACTIVE_CREDENTIAL`。
5. `DELETE /api/scenes/{id}/credentials/{credential_id}` 保留（紧急停用能力，1:1 下即停用唯一凭证）。
6. 认证链路（`require_scene_principal` 按哈希查凭证）行为不变；外部 `connection` 接口不变。
7. 存量迁移：场景有多张有效凭证时保留最新一张、其余作废（reason=`model-migration`）；**历史凭证的明文无法恢复**（旧模型只存哈希），其 `token_plaintext` 为 NULL，界面显示“签发于旧版本，明文不可查看；替换凭证后恢复可看”，绑定继续有效。

### 前端

8. 凭证面板：单张当前凭证卡片——掩码形态 `sep_Ab3d…Xy9z`（前 6 后 4，从可看明文派生；旧凭证无明文时显示占位文案），小眼睛按钮切换明文显隐（明文按需从新端点取，不随状态接口下发），签发时间/最近使用时间，撤销按钮。
9. 头部单按钮：无凭证时“创建凭证”，有有效凭证时“替换凭证”（带确认对话框，说明旧凭证立即失效）。操作成功后弹出一次性提示词对话框（现有 `AgentPromptDialog` 保留）。
10. 连接状态派生逻辑适配单凭证模型（无凭证=未签发；有效未用=已签发待验证；有效已用=已连接；仅存撤销记录=已停用——1:1 下“已停用”仅在撤销后出现）。

### admin CLI

11. `credentials replace --scene-id <id> [--label ...]`：执行创建/替换，输出新凭证；提示文案改为“明文已可在场景页查看”。`credentials revoke` / `credentials status` 保留，`status` 输出改为单凭证视图。

## 验收标准

1. 全新场景点“创建凭证”→ 生成凭证，状态接口返回单个 `credential`，掩码视图不含明文。
2. 再点“替换凭证”→ 旧凭证立即失效（用旧 token 上传返回 401 `CREDENTIAL_INVALID`），新凭证生效；场景详情仍只返回一张有效凭证。
3. `GET /api/scenes/{id}/credential` 返回的明文与签发时一次性返回的 token 一致；响应头 `Cache-Control: no-store`；无有效凭证时 404。
4. 状态接口与列表接口的响应正文绝不包含任何明文凭证（测试断言）。
5. 存量多凭证场景迁移后只余一张有效凭证；旧模型凭证（无明文）在界面以“不可查看”形态呈现且绑定可用。
6. admin CLI `credentials replace` 可用；`issue`/`rotate` 子命令不存在。
7. `make test`、`make build` 全绿；`backend/openapi.json` 与前端生成类型同步（`make contract-check`、`frontend-check-api`）。
8. 全仓库定向检索：`credentials/rotation`、`rotateCredentials`、`issue_credential`（旧函数名）、多凭证列表形态的 UI 代码无残留（任务文档除外）。

## 范围边界

- 技能侧硬编码绑定机制由姊妹任务 `09-04-skill-credential-binding`（已完成并合入）承担。
- 凭证加密存储明确不做（需求方选择裸明文）。
- 凭证使用审计、多管理员权限细分不在本任务范围。
