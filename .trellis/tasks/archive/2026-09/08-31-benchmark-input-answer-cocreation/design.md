# 技术设计：对话式题目与标准答案共创

## Dependency and ownership

本子任务是父任务第一个实施单元，无业务前置子任务。独占新 AuthoringConversation/Message/SafeStreamEvent/QuestionDraft 合同与会话 UI；顺序扩展 UploadBatch、TaskPackage、CoCreationSession、AI runtime、OperationWorker 和 OpenAPI。不得实现 Rubric/发布/人工评分。

## Backend shape

- 保留 Workspace、UploadBatch/EvidenceFile、TaskPackage、OperationJob 和现有 Checkpointer。
- 新增 AuthoringConversation、AuthoringMessage、SafeStreamEvent、BenchmarkQuestionDraft。
- 会话是用户可见聚合；现有 CoCreationSession 继续作为每题内部 Agent thread，不向浏览器暴露。
- conversation/question revision 使用 CAS；active OperationJob 由数据库约束和 Service 双重检查。

## Agent shape

- `task_analyzer`：fresh attempt，0..N 分组，只读证据工具。
- `question_cocreator`：每题稳定 thread，只读证据 + ask_teacher，一次一个问题。
- 明确禁用 task/write_todos/write/edit/delete/execute、subagent、Skills、Memory、Store 和网络。
- 全中文 Prompt；证据标为不可信；老师确认权、标准答案来源和题间隔离写入静态合同。

## Safe streaming

- Worker 使用 graph stream，但只发布 Pydantic allowlist 安全事件。
- Provider token 不直通；公开消息完整缓冲、中文/路径/敏感字段/结构校验后再分段发送。
- SSE 支持 Last-Event-ID；断线只影响体验，GET snapshot 是事实源。
- 处理中 composer 只保留本地草稿和 File 对象，POST 端口同时 fail-closed 拒绝并发。

## Frontend

- 复用现有浅色 token、Button、AutoTextarea、Field、Note、Sheet、StatePanel、Skeleton。
- 会话页使用 transcript 而非气泡：AI 正文、老师弱表面、可折叠进度行、底部 composer。
- 候选题在轻量轨/sheet 中确认，不建永久第三列。
- 更新 `.interface-design/system.md` 中已被新需求替代的“不做聊天流/token stream”和导航条款。

## Migration and rollback

- 只增加表/列；旧 CoCreationSession、ScenarioContract/JudgmentPackage 和版本包只读保留。
- 旧 TaskPackage 信息不足时标记 legacy-needs-review，不自动生成标准答案。
- 功能未完整时不暴露新入口；回滚可继续使用旧轮询 UI。

