# 实施清单：待评文本提交与人工评分

## Before start

- [ ] 子任务二已完整闭环；从最新 main 创建 `codex/benchmark-human-scoring`。
- [ ] 读取父任务/本任务规划、backend/frontend/evaluation-set specs。

## Backend

- [ ] Submission/Score/ScoreItem 迁移、Repository、Schema、Service、Router。
- [ ] 文本/文件验证、staging/ready/hash、归属、修订绑定和命令幂等。
- [ ] 逐项/理由/关键项/总分/通过的服务端确定性校验。
- [ ] immutable final、parent-linked re-score 和历史读取。
- [ ] 权限、并发、幂等、伪总分、泄漏、失败清理测试。

## Frontend

- [ ] OpenAPI 生成类型与 scoring Feature Service。
- [ ] 粘贴/单文件入口、双区/窄屏评分页、条件式理由和自动结果。
- [ ] loading/empty/invalid/draft/submitted/re-score/unauthorized/forbidden/not-found Preview。
- [ ] 键盘、焦点、44px 命中、错误关联和 reduced-motion。

## Gates

```bash
make openapi
make test
make build
git diff --check
```

- [ ] EvalData 派生的脱敏/本地答卷走通真实浏览器评分，不提交正文。
- [ ] 对正文泄漏、历史覆盖、重评串线、旧/新修订和存储残留做对抗审查并修正。
- [ ] commit -> fast-forward main -> main 全量复验 -> archive -> 安全删支。

