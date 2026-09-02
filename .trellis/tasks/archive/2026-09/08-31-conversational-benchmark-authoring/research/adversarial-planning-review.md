# 规划对抗审查

## Scope

审查父 PRD/design/implement 与三个子任务，覆盖权限、并发、幂等、恢复、泄漏、版本、迁移、旧数据、流事件、评分一致性和存储完整性。这里只审查规划，不验证尚未实现的代码。

## Findings and corrections

### 1. 原始 token 直通会在校验前泄漏正文或内部信息

- Failure：模型复述附件、绝对路径或系统提示后，SSE 已经发送，无法撤回。
- Correction：Provider token 不直通；公开回复完整缓冲并通过中文/泄漏/结构校验后再分段发布。进度由 Worker 确定性生成。
- Status：已写入 parent design 和 streaming research。

### 2. 把 Agent 放入 SSE 请求会绕过 Worker 恢复合同

- Failure：浏览器断线取消长调用，OperationJob/lease/projection-pending 失去权威。
- Correction：Worker 继续执行，SSE 只读取安全事件，断线先 GET snapshot 再续传。
- Status：已修正。

### 3. UI 禁用按钮不能阻止并发消息

- Failure：两个标签页同时 POST，产生同一 Checkpoint 分叉或附件串轮。
- Correction：后端 CAS + active_operation 409；消息先持久化再排队；无 mid-run queue。
- Status：已修正。

### 4. 多题会话容易交叉引用其他题反馈

- Failure：新闻稿修改意见进入邀请函题，生成错误规则。
- Correction：稳定 TaskPackage scope、question-specific feedback、EvidenceRef 二次校验；AI 只能读当前题。
- Status：已修正。

### 5. 最后一条 AI 回复被误当标准答案

- Failure：没有老师终版时模型自行挑候选，AI 候选成为业务真相。
- Correction：只认老师终版/明确认可；缺失时 HITL 追问，老师显式确认。
- Status：已修正。

### 6. 上游修改后旧 rubric 仍可发布

- Failure：题目/标准答案已变，评分项和锚点仍引用旧内容。
- Correction：上游 confirmed revision/hash；任何变化清空未发布 rubric 并回第一阶段；publish CAS 校验。
- Status：已修正。

### 7. 参考答案与 rubric 自相矛盾

- Failure：所谓高分参考答案低于 60 或命中关键失败仍被发布。
- Correction：参考答案逐项锚点、总分与关键项机械自检，不通过则阻塞发布。
- Status：已修正。

### 8. 总分掩盖事实/合规/泄漏硬失败

- Failure：文风和结构补分使事实错误答卷总分通过。
- Correction：100 分总分 + critical minimum/hard-fail 双层判定；关键失败不可补偿。
- Status：已修正。

### 9. 关键项数值和人工勾选可能矛盾

- Failure：分数达到最低线但老师另勾失败，或反之。
- Correction：minimum 模式由分数机械推导；hard-fail 模式只记录条件是否命中；两种配置互斥。
- Status：本轮审查已补入 parent/child 文档。

### 10. 修改发布规则会移动历史门槛

- Failure：同样 80 分代表不同规则，调优效果无法判断。
- Correction：发布修订不可变；修改创建新修订；评分绑定修订；重评新增 parent-linked 记录。
- Status：已修正。

### 11. 客户端可伪造总分或漏交低分理由

- Failure：前端发送 total/passed，或绕过条件式理由 UI。
- Correction：服务端只接收 criterion input，精确核对 ID 集合、范围和理由；total/critical/passed 全部推导。
- Status：已修正。

### 12. 评分提交并发会覆盖历史

- Failure：重复提交或重评更新同一 final row。
- Correction：command_id/payload hash 幂等；submitted score 拒绝 update/delete；重评新建记录并链接 parent。
- Status：已修正。

### 13. 待评文件留下孤儿或泄漏正文

- Failure：文件已写、DB 失败；日志/SSE/错误回显正文。
- Correction：单文件 1 MiB/UTF-8/MIME/hash，staging/ready；失败精确清理；流和日志只留 ID/字节/hash 前缀。
- Status：已修正。

### 14. 新版本包覆盖或重拼旧 v1

- Failure：schema 升级改变历史 hash/bytes，或把答案/评分泄漏到 runtime。
- Correction：新 schema/key/reader；v1 只读；runtime allowlist；judge/provenance 分区与 hash/ready 校验。
- Status：已修正。

### 15. 旧数据被错误自动升级

- Failure：旧 ScenarioContract/JudgmentPackage 信息不足却被转换为发布题。
- Correction：只有机械完整映射才生成 draft；否则 legacy-needs-review，由老师重新确认，不静默发布。
- Status：已修正。

### 16. 规划按技术层拆导致半成品分支

- Failure：先后端再前端，任一分支不可独立验收并污染 main。
- Correction：按三个业务阶段拆分，每个子任务包含完整 Backend -> OpenAPI -> Frontend -> Test 链，严格串行闭环。
- Status：已修正。

## Residual risks to verify during implementation

- 当前 Provider + ToolStrategy 下公开中文消息的实际事件形状和缓冲策略必须做真实 Spike，不能用文档代替。
- SafeStreamEvent retention/compaction 需要以断线恢复测试确定，不能让事件表无限增长或删掉仍需续传的窗口。
- 浏览器选择但未提交的 File 对象刷新后会丢失；UI 应明确这是未提交草稿，不承诺跨刷新保留。
- 旧 EvaluationSetVersion 与新 BenchmarkQuestionRevision 的映射只能在真实 migration/reader 测试后定稿。
- `.interface-design/system.md` 当前仍含与新决策冲突的旧目标条款；必须在子任务一实施分支同步，规划阶段不能把它标为已实现。

## Conclusion

规划维持三子任务方案。未发现需要扩大为 Skill 执行平台、AI Judge、WebSocket/Redis、多标准答案或并排评测的理由。剩余风险均可在对应子任务的实现/真实验证中封闭，不改变已确认的产品行为。

