# Technical Design

## Architecture boundary

系统保留 FastAPI 单体、SQLAlchemy/Alembic 业务数据库、文件存储、OperationJob Worker 和受限 AI Runtime。业务数据库继续是题目、记忆材料、评分规则、发布修订和评分结果的唯一业务事实源；Checkpointer 只负责 AI 执行连续性。

当前 Next.js 前端及其生成类型、Playwright、Preview 和构建脚本全部删除。未来前端只依赖 `/api/openapi.json` 和后端 API，不直接读取数据库。

## Evaluation-case material contract

外部收题请求升级为新 schema，包含：

- `title`
- `task_requirement`
- `input_files[]`
- `memory_materials[]`
- `bad_samples[]`，其中每个坏样本内绑定 `teacher_feedback_texts[]` 与 `reason_summary`
- `reference_answer_text`

`memory_materials[]` 每项保存稳定客户端 ID、安全显示来源、原始内容和可选摘要。服务端限制数量、单项长度、总 payload，拒绝路径、凭证和内部运行字段。空数组表示此次任务未使用记忆。

外部凭证决定 `workspace_id`，请求不得传入或覆盖场景。相同连接和 `command_id` 的相同 payload 返回同一草稿；不同 payload 返回冲突。

草稿和已发布题目快照都必须保存记忆材料。发布历史不可变。

## Rubric contract

Rubric 内容只包含 `criteria[]`。每项：

```json
{
  "id": "stable-machine-id",
  "name": "维度名称",
  "description": "可执行的评分说明",
  "pass_score": 7
}
```

- 固定满分为系统常量 `10`，不进入老师可编辑字段。
- `pass_score` 为整数 `0..10`。
- AI 生成初稿；老师可增删改；最终确认与发布由业务 Service 控制。
- 评分提交为每项 `0..10` 分。任一项低于自身 `pass_score`，整题失败。
- 原始总分为各项得分之和；展示总分按 `round(raw / (count * 10) * 100)` 换算。零维度不可确认或发布。
- 删除旧 `max_score`、给分点、扣分点、关键项、参考答案预期评分和全局 `pass_threshold` 语义。数据库旧 JSON 不做兼容读取；迁移清理开发数据或将旧草稿/修订标记为不可继续使用，具体采用最小且可验证的破坏式迁移。

## AI generation

Rubric Agent 输入使用老师确认的题目快照、参考输入、记忆材料、真实坏样本/反馈和标准答案。输出严格验证为三字段模型。维度说明必须包含可观察的判断依据，禁止参考答案字面相似度规则。

## Frontend removal

删除：

- `frontend/`
- 根级 Node/pnpm 配置与锁文件（若只服务该前端）
- Makefile 中 frontend、typecheck、build、前端生成类型与 Playwright 入口
- README 中旧前端启动、路由和浏览器验收说明
- 后端仅用于拼接旧前端 URL 的响应字段与设置
- `.trellis/spec/frontend/` 中已失效的实现规范

保留：

- FastAPI OpenAPI JSON
- 后端 OpenAPI 导出与漂移检查
- 所有未来前端需要的 API
- 真实 HTTP/API 验收脚本

`make test` 变为后端测试 + 后端 OpenAPI 漂移检查；`make build` 若保留则定义为后端可导入/编译检查，否则从公开命令中删除并同步文档。

## Skill

根目录 `skills/ai-eval-push/` 包含：

- `SKILL.md`：触发边界、材料提取、隐私限制、预览确认和上传流程；
- `scripts/`：确定性读取配置、校验 JSON、查询连接状态和 POST 草稿；
- `references/`：API payload 与错误处理合同；
- `agents/openai.yaml`：简洁 UI 元数据。

配置从环境变量或用户级私密配置读取，不在仓库生成真实凭证。Skill 默认自动发现，但任何真实上传都必须在调用当轮得到老师对结构化预览的明确确认。

## Rollback and migration

- 在任务分支完成迁移和测试，旧前端删除可通过 Git 恢复。
- 数据模型是明确的 M0 替换，不保留旧 Rubric 兼容分支。
- 迁移后运行 fresh DB 全链路和 upgrade-from-previous-head 检查。
- Skill 真实联调使用临时场景/凭证；测试结束撤销凭证并不输出秘密。
