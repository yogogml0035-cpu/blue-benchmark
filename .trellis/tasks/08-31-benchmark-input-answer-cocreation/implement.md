# 实施清单：对话式题目与标准答案共创

## Before start

- [ ] 取得父任务最终规划后的独立实施批准。
- [ ] 从已验证干净 main 创建 `codex/benchmark-input-answer-cocreation`；检查全部 worktree 和用户改动。
- [ ] 读取 backend/frontend/guides specs、父任务 design 和 `research/streaming-session-boundary.md`。

## Backend

- [ ] 增加前向迁移、ORM、Repository、Pydantic Schema 和 Service。
- [ ] 建立会话/消息/安全事件/题目草稿 CAS 与命令幂等。
- [ ] 重构 task analyzer/question co-creator 中文 Prompt、Schema、权限和 one-question HITL。
- [ ] Worker 流事件安全投影、SSE 端点、重连和快照恢复。
- [ ] 上游确认与变更失效；旧数据兼容和 legacy-needs-review。
- [ ] 后端/API/真实 Provider/权限/并发/恢复/泄漏测试。

## Frontend

- [ ] 生成 OpenAPI 类型后更新 Feature Service，不手写 DTO。
- [ ] 会话 transcript、composer、进度/动作摘要、候选题确认、上游审阅确认。
- [ ] generation guard、401/403/404 清空、409 刷新、SSE reconnect、窄屏 sheet 与键盘/焦点。
- [ ] 开发 Preview 覆盖 loading/empty/processing/waiting/review/failed/projection-pending/reset/confirmed。
- [ ] 更新 `.interface-design/system.md` 为最终实现事实。

## Gates

```bash
make openapi
make test
make build
git diff --check
```

- [ ] 使用 EvalData 做本地真实浏览器闭环，正文不进入 Git/日志/报告。
- [ ] 对权限、并发、幂等、恢复、泄漏、迁移和存储做对抗审查并修正。
- [ ] commit -> fast-forward main -> main 全量复验 -> archive -> 安全删支。

