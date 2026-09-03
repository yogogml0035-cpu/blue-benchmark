# Technical Design

## Ownership

- Auth bootstrap/password reset：`features/auth`。
- 评测集更新、空集删除、凭证响应头：`features/scenes`。
- 维度确认、重开、删除状态机：`features/question_library`。
- 数据字段：`lib/database/models.py` + 新 Alembic revision。
- Router 只声明 HTTP；Service 负责规则；Repository 负责原子读写。

## API And Data

- `GET /api/auth/bootstrap` -> `{registration_available}`。
- `PATCH /api/scenes/{scene_id}` -> 更新后的 `SceneView`。
- `DELETE /api/scenes/{scene_id}` -> 204；非空 `409 SCENE_NOT_EMPTY`。
- `POST /api/questions/{id}/review-reopen` + `QuestionCommandRequest`。
- `DELETE /api/questions/{id}` + `QuestionDeleteRequest(content_revision, confirmation_title?)`。
- Question list/detail 增加 `criteria_confirmed`；detail 增加派生 `delete_confirmation_required`。
- `NextAction` 使用 `review_criteria` 与 `publish` 两个明确值。

新 migration：

- `criteria_confirmed`: published 回填 true，其余 false；
- `ever_published`: published 回填 true，其余 false。

`ever_published` 仅作为删除门禁，不形成用户可浏览历史。Scene 空删使用单事务和数据库约束抵御并发上传，不先分步撤销凭证。

## State Rules

- generation commit 始终写 confirmed=false；
- criteria patch 写 confirmed=true；
- publish 要求 confirmed=true 并置 ever_published=true；
- reopen 只做 published -> pending_review，保留 confirmed/criteria；
- save-regenerate 清空 criteria、confirmed=false，保留 ever_published；
- delete 以当前状态、ever_published、revision 与确认标题共同裁决。

## Password Reset

CLI 使用 `getpass` 两次读取，Service 校验密码并哈希，Repository 在同一事务更新唯一管理员和删除其 Session。测试 monkeypatch 输入，不在 assertion failure 中打印密码。

## Compatibility

外部上传 Skill 的批量 payload 与 Bearer 权限不变。管理员 OpenAPI 是有意扩展/收紧；仓库内所有调用者和测试同步更新，不保留可绕过人工确认或删除门禁的旧路径。

## Rollback

先回退依赖新字段的 API，再 downgrade migration。若已存在依赖 confirmed/ever_published 的新写入，不自动 downgrade；保留分支并报告数据状态。
