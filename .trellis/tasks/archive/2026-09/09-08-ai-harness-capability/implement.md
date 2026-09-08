# C1 实施与独立交付

状态：已获实施批准（2026-09-08，覆盖整棵任务树）。以下按开始条件逐项执行。

## 开始条件

1. 已获 C1 或整棵任务树的明确实施批准；最终父子计划已交付到已验证 main。
2. 检查所有 worktree 和主工作区，保持他人改动原样；从最新干净 main 创建 `codex/ai-harness-capability` 与外部 `blue-benchmark-wt/ai-harness-capability`，完成路径/分支/状态校验。
3. 复制 `.env` 后先覆盖独占测试资源与输出目录；核对原始语料目录只读、数据保护与有限预算，不使用主环境两库。
4. 更新本子任务实际 branch/worktree 字段，读取父共享设计、本子任务三文档、必要 skills/specs，再运行本子任务 `task.py start`，不启动父任务。

## 执行顺序

1. 新增专用探针与 `backend/tests/test_ai_harness_capability_probe.py`。先验证 dry-run、不受控网络阻断、受保护库拒绝、日志白名单和预算生效。
2. 通过现有 generator 的注入入口运行原生 Responses 模型，按父验证矩阵 L01 和 C1-AC2/3 验证当前完整能力，不改 `backend/app/` 或 `.env.example`。
3. 对探针自己的执行子进程做工具轮后中断和恢复，保持合同与预算一致，完成 C1-AC4；不启动业务 Worker，不重试原题。
4. 交付实际运行后的 `research/capability-verification.md`：完整配置身份、PASS/FAIL、可复跑命令、阶段计数及未覆盖项；私有原始产物仅在本子任务 gitignored storage，Git 中只有脱敏报告。
5. 不通过就保留证据并回到父计划，不把失败报告作为 C2 开工凭证。

## 验证入口

```bash
git diff --check
make test
make build
(cd backend && uv run python -m scripts.probe_ai_harness_capability)
(cd backend && uv run python -m scripts.probe_ai_harness_capability --execute)
```

最后一条依赖实施批准、明确隔离 checkpoint DSN、样本根目录和预算；脚本实施时将准确 CLI/环境合同写入 help 与验证报告，任何凭证实值均不写进文档。无条件 skip 或普通对话成功不满足 C1 验收。

## 独立集成与交接

- 质量门和真实能力通过后，提交探针/测试/安全报告，按根 AGENTS 串行合并并在 main 复跑 C1 完整门；记录交付 SHA。
- 核查 `git diff --name-only <C1-base>..HEAD` 仅有 C1 探针、测试与任务材料，没有生产装配或主配置切换。
- C1 全部验收完成后归档、清理本子任务工作区和分支；保留 main 上的源码与脱敏报告供 C2 使用。
- C2 的后续工作区不共享本子任务的未提交材料、密钥、运行中的进程或临时库；需要真实输入时从授权源重新构建。
- 回滚只涉及 C1 探针/测试和自有资源。C1 不替换生产语义，因此无需提前删除现有生产 Chat 路径；删除责任已经明确归 C2。
