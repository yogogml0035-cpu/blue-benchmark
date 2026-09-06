# C1 设计：可重建的真实样本合同

## 依据与边界

- 继承 .trellis/tasks/09-05-m0-rubric-anchors-evidence/prd.md 和 research/real-sample-validation.md；原始根目录为 /Users/hsikey/Company/skill-eval-platform/.local-samples/m0。
- 使用仓库现有 Python 脚本/pytest 风格；JSONL 使用结构化解析，不用长度阈值、最后一条助手消息等启发式冒充老师认可。
- 本任务代码落在 backend/scripts 下的样本准备模块与对应 backend/tests；不改现有真实验收 runner 的生产调用链，该切换归 C3。

## 输出合同

- 六材料 batch 保持现有上传输入语义；命令 ID 可按运行生成，稳定 case ID 和来源关系可复验。评分结果的新增字段不属于本输入合同。
- manifest 记录 corpus hash、case ID、来源组、消息定位、有效材料时点、字段来源、清洗/提炼说明；真实正文不提交 Git。
- expectations 记录独立检查项、支持来源和适用边界；真实反馈与 Agent 推定分开，未知数字门槛不伪造成老师标准。
- derived cases 记录父 case、变异字段和预期失败原因；不得覆盖真实 case 或修改原件。

## 提取与重建

1. 校验根路径、六个源文件与 hash，过滤 .DS_Store；缺失即失败。
2. 解析 JSONL 角色、内容块、父消息/工具关联；Markdown 按编号回合与导出注记分层识别，保留实际文本边界。
3. 按任务和时点挑选完整材料，处理被替代要求与源文件版本缺口；去除主机路径/凭证，不改变业务要求。
4. 按父任务已核查的终稿/反馈定位生成输入及独立断言，写入当前任务 worktree 的 storage/acceptance 下。
5. 输出脱敏摘要和来源覆盖；重建不需要访问已归档任务的工作区，也不需要重新让模型猜选取范围。

## 所有权与不变量

- 不在本任务复制一套生产 RubricGenerator，不新增 runtime schema 或临时兼容 DTO。
- 可提交稳定的选择规则、解析代码、断言规则与脱敏元数据；原文 fixture 由使用方按同一规则重建。
- 本地源文件中的 XX 等原有占位内容照实保留；它与脚本因缺少答案而伪造占位兜底不同，不补写未给出的事实。
- 清理仅限本任务生成的临时产物，原始目录不可写。

## 风险

- 不完整材料只能限定断言范围或报证据不足，不能为了凑齐 case 改写 golden。
- 后续任务消费入口和输出字段变更必须同步取样规则和测试；不提交只存在于本机目录的不可复现交接。
