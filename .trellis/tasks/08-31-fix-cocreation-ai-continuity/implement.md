# 实施计划：共创阶段连续性与 Worker 运行模式隔离

## 1. 准备与边界

- 从已验证且干净的 main 创建 codex/fix-cocreation-ai-continuity。
- 运行 task.py start 后确认任务分支和 base_branch=main。
- 读取 backend/frontend spec；所有跨层合同变更先改 Pydantic/OpenAPI，当前方案预期不改 HTTP Schema，因此不应手改生成文件。

## 2. 实施顺序

1. 扩展 StandardCoCreator 的内部 adapter 入口，传入已确认场景合同；在 Service 中完成合同归属、状态和 revision 校验，并在 Repository 防止题级门禁削弱场景门禁。
2. 更新真实 DeepAgent 的 start/resume/reproject prompt，明确继承合同和题级补充边界；更新 Fake adapter 的分阶段测试行为。
3. 增加 PostgreSQL 长驻 Worker advisory lock，接入 run_forever 和 CLI --once；保留测试直接调用 run_once() 的行为。
4. 禁止 Fake Worker 连接 PostgreSQL 业务库，防止显式 fake 环境误消费真实队列。
5. 增加前端题级阶段的业务解释，确保页面只基于服务端 session 快照展示阶段，不复制合同内容或状态判断。
6. 为合同传递、共享门禁、重复问题、Fake/Production 互斥、旧/陈旧 session 和恢复路径补回归测试；必要时更新 README 的单 Worker 启动说明。

## 3. 验证门

### 代码与自动化

    git diff --check
    cd backend && uv run pytest -q
    cd ../frontend && pnpm typecheck
    cd .. && make contract-check
    make test
    make build

若没有前端源码变更，可记录 make build 仍执行；若修改题页文案/交互则必须执行。

### 运行时证据

- 用无密钥/无正文输出的测试替身捕获真实 adapter 的消息，断言题级 start 含合同且场景 start 不含合同。
- 用两个连接模拟同一 PostgreSQL 数据库 advisory lock：第一个持锁，第二个在 claim 前失败；释放后第二个可获得锁。
- 检查当前开发进程，只保留一个与 .env AI_RUNTIME_MODE 一致的长驻 Worker；不要让 AI_RUNTIME_MODE=fake 的旧 Worker继续消费生产队列。
- 如果执行真实 provider smoke，只报告阶段标记，不输出模型正文、证据正文、凭证、thread 或 checkpoint。

## 4. 对抗式审查与修正

在主测试通过后，逐项攻击：

- 让旧合同 session 在合同更新后 resume；应拒绝或进入连续性重置。
- 并发 start/answer/confirm；应保持一个活动 session、一个 accepted 分支和幂等结果。
- 让第二个 Fake/Production Worker 启动；应在 claim_next 前被锁挡住。
- 让模型返回重复/越权 EvidenceRef 或把合同当指令；应沿用 canonical scope 校验和不可信内容边界。
- 删除/缺失 Checkpoint、投影失败、重试和进程重启；应沿用 continuity reset/projection_pending，不重新投机恢复。
- 检查公开 DTO、错误响应、版本 runtime/judge/provenance，确认没有新增合同、回答、凭证或内部运行信息泄漏。

发现问题后只修当前行为缺口，重新运行完整质量门；未满足门禁则保留分支，不合并和不删除。

## 5. 收尾

- 更新相关 spec/README，仅记录已验证的 Worker 单消费者与合同传递规则。
- 在任务分支提交稳定职责批次。
- 切换 main fast-forward 合并，重新运行 git diff --check、make test、make build。
- 确认 git log main..codex/fix-cocreation-ai-continuity 为空、工作树干净、无 worktree 使用后，安全删除本地任务分支；不删除 main、origin/main 或 origin/HEAD。
- 完成 Trellis 归档和会话记录后交付当前事实、修复文件、验证证据和仍未验证的真实 Provider/浏览器事项。
