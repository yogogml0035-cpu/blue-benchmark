# Implementation Plan

1. 扩展 Auth Schema/Repository/Service/Router，加入 bootstrap；为密码校验/哈希整理单一可复用入口，并扩展 `admin_cli account reset-password`。
2. 扩展 Scenes Schema/Repository/Service/Router/CLI，加入元数据更新和原子空集删除；签发/轮换增加不可缓存响应头。
3. 新建 `0019_m0_web_review_contracts.py`，更新模型、Record、数据库清理和 schema-ready 合同。
4. 扩展 Question Schema/Service/Repository/Router 与 generation commit，落地 confirmed、next_action、reopen 和受保护 delete。
5. 更新 auth/scenes/question/migration/adversarial 测试，覆盖成功、授权、并发、陈旧 revision、状态错误和无泄漏。
6. 运行 `make openapi`，同步 README、CLI 使用说明和 backend/cross-layer specs。
7. 运行 `git diff --check`、`make db-migrate`、`make db-check`、`make test`、`make build`；独立验证 fresh/upgrade/downgrade。
8. 执行 `trellis-check`，提交稳定后 fast-forward 合并 `main`，在 `main` 重跑完整门禁后归档。

## Risky Files

- `backend/migrations/versions/0019_m0_web_review_contracts.py`
- `backend/app/features/question_library/service.py`
- `backend/app/features/scenes/repository.py`
- `backend/openapi.json`（只允许生成器修改）

## Stop Conditions

- PostgreSQL 和 SQLite 对 migration 或原子空删行为不一致；
- 旧 API 仍能绕过 `criteria_confirmed` 发布或绕过题目删除门禁；
- 测试/CLI 输出任何密码、Cookie 或明文凭证。
