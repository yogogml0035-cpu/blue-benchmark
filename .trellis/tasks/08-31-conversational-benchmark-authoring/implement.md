# 实施计划：对话式 Benchmark 出题与人工评分

## Parent task rule

本父任务负责需求、子任务顺序、跨子任务合同和最终集成验收，不作为日常业务代码实施分支。三个子任务按顺序各自完成完整分支闭环；任何子任务未合并并在 main 复验通过前，不启动下一项。

## 0. 实施前共同门禁

- [ ] 确认用户已在最终规划摘要之后单独批准实施。
- [ ] 检查 `git status --short --branch`、全部 worktree、main 与 origin/main；不覆盖当前两个 planning 任务或用户改动。
- [ ] 读取 `.trellis/spec/backend/index.md`、`.trellis/spec/frontend/index.md`、跨层合同和各子任务 design/implement。
- [ ] 确认当前锁定 Deep Agents/LangGraph 版本的 stream、HITL、ToolStrategy 和 Checkpointer API；不按最新文档臆测已安装版本。
- [ ] 每个子任务从验证干净的 main 创建 `codex/<task-slug>`，运行 `task.py start` 后设置 branch/base_branch。

## 1. 子任务一：对话式题目与标准答案共创

目标分支：`codex/benchmark-input-answer-cocreation`

- [ ] 增加 AuthoringConversation/Message/SafeStreamEvent/QuestionDraft 所需迁移与 Repository，不删除旧表。
- [ ] 建立单活跃会话、消息幂等、candidate 0..N、split/merge/discard 和资料角色/优先级合同。
- [ ] 重构 task analyzer/question co-creator 的中文 Schema、提示词、工具面和上游显式确认。
- [ ] Worker 使用 Deep Agents stream 投影安全事件；实现 SSE 重连与 GET snapshot 权威恢复。
- [ ] 实现 provider token 缓冲/验证后公开、中文门禁、路径/内部字段/正文泄漏 fail-closed。
- [ ] 前端把“当前”重构为会话 transcript、候选题轨、composer 和第一阶段确认；更新 `.interface-design/system.md` 为已批准目标，不宣称未实现状态。
- [ ] 迁移/兼容旧 CoCreationSession 与 TaskPackage 只读路径，旧路由不保留第二套编辑器。

质量门：

```bash
make openapi
make test
make build
git diff --check
```

额外验收：断线重连、刷新、Worker 重启、waiting-for-teacher 附件补充、并发发送 409、迟到事件丢弃、流中敏感标记扫描、390px 窄屏与键盘/焦点。

完成后：commit -> fast-forward main -> main 重跑全部质量门 -> Trellis 归档 -> 精确安全删除本地/远端任务分支。

## 2. 子任务二：打分规则共创与题目发布

前置：子任务一已经 main 复验、归档和删支。

目标分支：`codex/benchmark-rubric-publishing`

- [ ] 增加 Rubric/QuestionRevision 结构、稳定 criterion ID、100 分求和、默认/自定义阈值和双层判定校验。
- [ ] 实现 rubric co-creator 独立稳定 thread、中文提示词、相关反馈隔离和标准答案逐项锚点/理由。
- [ ] 上游修改机械清空未发布 rubric；发布先完整校验/hash，再原子创建不可变修订。
- [ ] 实现 derive-next-draft、新修订和旧修订只读；AI 不能确认关键项、阈值或发布。
- [ ] 升级版本包 schema，同时保留 v1 reader；runtime 继续机械排除答案、规则、评分和形成记录。
- [ ] 前端在同一会话进入规则审阅，逐项编辑给分/扣分/关键项/锚点，提供发布确认和修订历史。

质量门同子任务一；额外验收：满分不等于 100、参考答案不过线、关键项失败、criterion ID 变化、重复发布、并发修订、打包失败、历史 v1/v2 读取和上游变更失效。

完成后执行同一分支闭环，再启动子任务三。

## 3. 子任务三：待评文本提交与人工评分

前置：子任务二已经 main 复验、归档和删支。

目标分支：`codex/benchmark-human-scoring`

- [ ] 增加 EvaluationSubmission/HumanScore/HumanScoreItem 迁移、Repository、Service、Schema 和 API。
- [ ] 只接受粘贴主文本或单个 `.md/.txt`，复用 1 MiB、UTF-8、MIME、hash、ready marker 和账号/Workspace/题目归属校验。
- [ ] 答卷固定绑定已发布 QuestionRevision；不收集 Skill 版本、运行配置或调用轨迹。
- [ ] 服务端校验逐项整数分数、低于锚点/关键失败理由、关键项和 100 分双层结果；禁止客户端提交总分/通过结论作为事实。
- [ ] final score 不可更新；重评创建 parent-linked 新记录，历史可还原。
- [ ] 前端实现独立双区评分工作台、窄屏单列流程、条件式理由、自动总分/关键项结果和历史只读页。

质量门同前；额外验收：越界题目、旧/新修订绑定、超大/非 UTF-8/伪扩展文件、低于锚点无理由、关键失败无理由、总分伪造、重复 command、重评不覆盖、不同账号 403、答卷正文不进日志/流/版本 runtime。

## 4. 父任务最终集成验收

- [ ] main 干净，三个子任务提交都被 main 包含，所有 task branch 相对 main 无未合并提交。
- [ ] `make openapi && make test && make build && git diff --check` 全绿。
- [ ] 使用 `/Users/hsikey/BenchMark/EvalData` 做显式本地真实资料验收，不复制样本正文进 Git。
- [ ] 浏览器走通：创建会话 -> 上传/手动输入 -> 多题确认 -> 标准答案补充 -> 显式确认 -> rubric -> 发布 -> 粘贴/上传待评文本 -> 人工评分 -> 新修订重评。
- [ ] 真实 Provider 验证中文问题、HITL、流式安全投影、断线/刷新/重启恢复；Fake 路径只做确定性自动化，不冒充真实 AI。
- [ ] 下载历史 v1 包保持原 hash/bytes；新包 runtime/judge/provenance 隔离通过。
- [ ] 对权限、并发、幂等、恢复、泄漏、迁移、旧数据、流事件与存储完整性再做一轮父任务对抗审查并修正。
- [ ] 同步 README、Trellis specs 和 `.interface-design/system.md` 为最终源码事实；规划文档保留目标/决策历史。
- [ ] 归档父任务；不得运行父任务作为实现分支，也不得批量删除其他分支。

## Risky files and rollback points

- `backend/app/lib/database/models.py` 与新迁移：只前向增加；每个子任务单独 migration，失败时不 drop 历史列。
- `backend/app/features/case_builder/**`：避免在旧 Service 内叠第二套状态机；新增业务所有权时保持 Feature 内分层。
- `backend/app/lib/ai_runtime/**`：保留当前 permission/ToolStrategy/accepted checkpoint 测试，流式改造不得绕过安全投影。
- `backend/app/lib/operations/**`：保持 lease heartbeat、单 Worker 和 ownership/CAS。
- `backend/app/features/evaluation_sets/**`、`lib/version_packages/**`：新 schema 不覆盖 ready v1 文件。
- `frontend/src/features/workspaces/**`、`case-builder/**`：按生成 DTO 改造，旧 routes 只重定向；不要并行维护两套生产编辑器。
- `frontend/src/lib/api/generated.ts` 和 `backend/openapi.json`：只由 `make openapi` 生成。

