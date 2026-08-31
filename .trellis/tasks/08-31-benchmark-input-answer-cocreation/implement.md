# 实施清单：对话式题目与标准答案共创

## Before start

- [x] 取得父任务最终规划后的独立实施批准。
- [x] 从已验证干净 main 创建 `codex/benchmark-input-answer-cocreation`；检查全部 worktree 和用户改动。
- [x] 读取 backend/frontend/guides specs、父任务 design 和 `research/streaming-session-boundary.md`。

## Backend

- [x] 增加前向迁移、ORM、Repository、Pydantic Schema 和 Service。
- [x] 建立会话/消息/安全事件/题目草稿 CAS 与命令幂等。
- [x] 重构 task analyzer/question co-creator 中文 Prompt、Schema、权限和 one-question HITL。
- [x] Worker 安全事件投影、SSE 端点、重连和快照恢复；投影失败可走无模型 reproject。
- [x] 上游确认与变更失效；旧资料角色保守映射并要求重新确认，旧 TaskPackage 不自动升级。
- [x] 后端/API/真实 Provider/权限/并发/恢复/泄漏测试。

## Frontend

- [x] 生成 OpenAPI 类型后更新 Feature Service，不手写 DTO。
- [x] 会话 transcript、composer、进度/动作摘要、候选题确认、上游审阅确认。
- [x] generation guard、401/403/404 清空、409 刷新、SSE reconnect、窄屏 sheet 与键盘/焦点。
- [x] 开发 Preview 覆盖 loading/empty/processing/waiting/review/failed/projection-pending/reset/confirmed。
- [x] 更新 `.interface-design/system.md` 为最终实现事实。

## Gates

```bash
make openapi
make test
make build
git diff --check
```

- [x] 使用 EvalData 做本地真实浏览器闭环，正文不进入 Git/日志/报告。
- [x] 对权限、并发、幂等、恢复、泄漏、迁移和存储做多轮对抗审查并修正。
- [ ] commit -> fast-forward main -> main 全量复验 -> archive -> 安全删支（提交门待本轮确认）。

## Verification record (2026-09-01)

- `make db-migrate && make db-check`: pass，business schema head 为 `0008_authoring_question_prompt`。
- `make openapi && make test`: pass，143 backend tests、前端 typecheck、OpenAPI contract check 全部通过。
- `make build`: pass；`git diff --check`: pass。
- `make ai-smoke`: pass，真实 Provider 返回 `AI_PROVIDER_SMOKE=PASS`。
- `LANGGRAPH_STRICT_MSGPACK=true ... worker --once`: pass，生产 Worker 启动并无 serializer allowlist 警告。
- 真实浏览器：生产 API + 单 Worker + `next start`，显式使用 `/Users/hsikey/BenchMark/EvalData` 三个文件；最终结果 `1 passed`，约 12.1 分钟，5 道候选题全部确认、5 份老师标准答案、无未完成或失败 job，刷新回读通过。
- 真实失败也已封闭：模型缺失问题 ID、页面单次轮询、视口外 sticky 输入、输入范围问题和新 Checkpoint 类型 allowlist 均有回归修正；失败/诊断产物已移入 macOS 废纸篓。

## Scope note

- 已接入题级独立 `question_cocreator`：它只整理题目输入并提出安全追问，绝不生成或确认标准答案；老师显式标注的终版才写入参考答案。
- 旧 `TaskPackage` 不自动转换为新题稿；信息不足的历史资产仍由后续兼容任务决定是否以 `legacy-needs-review` 重新确认。
- 本子任务不实现 rubric、发布、待评答案或人工评分；这些由父任务后续两个子任务从本分支的确认快照继续。
