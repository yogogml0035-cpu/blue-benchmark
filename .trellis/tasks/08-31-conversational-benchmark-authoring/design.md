# 技术设计：Benchmark 收题、发布与人工评分重构

## 1. Outcome

最终产品由四条清楚边界组成：

```text
本地 Agent + ai-eval-push
  -> 场景绑定外部收题 API
  -> 完整单题草稿
  -> 返回精确草稿链接并结束
老师进入网站
  -> 草稿查看/编辑 -> 确认题目并生成打分规则
  -> rubric 审阅 -> 确认规则并发布到评测集
  -> 当前正式评测集 + 自动不可变版本
  -> 可选外部待评结果人工评分与跨修订重评
```

平台不执行被测 Skill；未来取题、做题和结果回传单独进入 M1。

## 2. Authority Boundaries

| Layer | Owns | Must not own |
|---|---|---|
| Business teacher | 目标场景、任务要求、输入内容、标准答案、坏样本原因、rubric、发布与人工分数确认 | 技术 ID、模型配置、租户校验 |
| Local Agent / `ai-eval-push` | 当前上下文整理、文本转换、完整性追问、上传预览、显式确认和草稿链接 | 平台 AI、rubric、确认、发布、版本、评分 |
| FastAPI Services + PostgreSQL | 账号/Workspace、凭证、Schema、状态、幂等、题目修订、当前集合、版本和评分事实 | 自由推断老师意图 |
| Deep Agents | 平台内 rubric 候选与受限业务回复 | 确认、发布、权限、版本、分数 |
| OperationJob / Checkpointer | 后台租约/重试与 Agent 连续性 | 业务真相和外部凭证 |
| Version package | 不可变 runtime/judge/provenance 快照 | 从可变表临时重拼历史 |

## 3. Domain Model Direction

### Workspace

- 账号私有场景，核心字段为名称和问题描述。
- 不保存强制 Skill 身份；旧 ScenarioContract 历史继续只读。

### BenchmarkQuestionDraft / Revision

- Draft：可编辑题目标题、任务要求、输入文件内容、单一标准答案、可选坏样本、rubric 状态和 lifecycle。
- 外部 API 与网站手动创建的 Draft 复用同一编辑模型；外部 receipt/hash 保留为形成记录，后续网站修改推进 draft revision。
- 草稿通过一个服务端组合命令确认当前 revision 并持久化 rubric 生成意图；生成失败保留确认，重新编辑使确认与未发布规则失效。
- Revision：发布时不可变快照；坏样本和否定原因参与 content hash。
- 已发布 Revision 不可编辑；修改派生唯一 next-revision Draft，当前 active Revision 直到新草稿完整发布才切换。
- 逻辑题目状态：`draft | active | disabled | deleted`；历史 revision 永不物理删除。

### Current Evaluation Set / EvaluationSetVersion

- Workspace 当前集合由所有 active 逻辑题的最新发布修订组成。
- 新修订发布、停用、恢复、删除以确定性 delta 生成连续不可变版本；仅保存修改草稿不生成版本。
- 旧 WorkingSetDraft/freeze API 只为历史兼容保留或退役，不再是新 UI 主流程。

### EvaluationSubmission / HumanScore

- Submission 保存不可变正文与原始修订。
- Score 保存本次实际使用的题目修订；首次固定原修订，后续只允许在相同 `question_draft_id` 的已发布修订间变化。
- 每条历史评分按自己的 revision 还原 rubric，不复制待评结果正文。
- 新 Submission、首次 Score 和 Rescore 均经过逻辑题 lifecycle 写门禁；disabled/deleted 只允许历史读取，restore 后重新开放。

### ExternalAuthoringConnection

- 固定 user/workspace/scope 的场景绑定连接。
- 一次性 code 短时过期；长期 token 只存 hash，不设固定自动过期，支持撤销、重新绑定失效和 last-used 审计。
- scope 仅允许绑定信息读取和 draft:create。

## 4. Text-only Question Contract

Canonical payload：

- `title`：本地 Agent 概括并经老师预览确认的题目标题；
- `task_requirement`：老师本地交给 Agent 的原始提示词，逐字保存且不做 trim/摘要/改写；
- `input_files[]`：0..N 份 `text/plain | text/markdown` 相关输入文件；区分完整原文与老师确认的来源节选；
- `bad_samples[]`：0..N 份当前真实执行中被老师明确否定的结果、source ref、逐字 `teacher_feedback_texts[]` 和老师确认的 `reason_summary`；禁止合成；
- `reference_answer_text`：一份老师最终认可的标准答案。

平台拒绝非文本内容、绝对路径、租户 ID、发布状态、模型配置和客户端 rubric。非文本原资料只在本地转换并确认。

## 5. Rubric and Visibility

- Rubric Agent只读取当前用例已确认的任务要求、输入文件内容、标准答案和坏样本原因。
- Criterion 继续包含稳定 ID、purpose、max、给/扣分点、critical 模式、参考答案锚点和阈值。
- 坏样本用于提出扣分和硬失败候选，不使用答案相似度或字符串黑名单。
- `runtime` 只含做题允许看到的任务要求与输入文件内容；标准答案、坏样本和 rubric 属于 `judge`，确认历史属于 `provenance`。

## 6. Atomic Publish and Versioning

“确认规则并发布到评测集”链：

1. 校验题目确认、rubric draft revision、参考答案锚点、当前集合 revision 和 command hash；
2. 构建新题目 revision 和当前集合候选；
3. 生成 staging 版 manifest/runtime/judge/provenance/ZIP 并校验 hash；
4. 数据库事务提交题目 lifecycle、当前集合指针和版本记录；
5. 发布 ready marker；失败不暴露新题或新版本。

文件系统与数据库无法真正跨介质原子，继续使用 staging + content hash + ready marker + 可重复 reconciliation；读取端只认 ready 版本。
新流程不提交独立 rubric-confirmed 状态；任何校验、打包或事务失败都保持 rubric review。旧 confirmed 记录只做兼容读取。

## 7. External API

### Web Session endpoints

- 创建/查看/撤销场景绑定连接；只允许 Workspace owner。

### External endpoints

- 一次性连接兑换；
- 读取当前绑定显示信息；
- 上传一份严格 Schema 的单题草稿。

External principal 由 token 解出固定 user/workspace/scope。上传路径不信任客户端租户字段。上传只同步创建草稿，不启动 AI/rubric Job；成功返回精确可编辑 Web 草稿 URL，URL 仍由浏览器 Session 鉴权。External API 不提供草稿 GET/PATCH/DELETE。

## 8. Frontend Information Architecture

- 场景：名称、问题描述、连接本地 Agent。
- 评测用例：本地或 Web 草稿、任务要求、输入文件内容、标准答案、坏样本和 rubric 审阅。
- 发布：一次确认后进入当前评测集。
- 题目列表：active/disabled/deleted 生命周期操作。
- 版本：只读历史、题数、时间、变化摘要与下载，不再承担日常组集。
- 评分：保留独立待评结果工作台；跨修订重评显式选择目标规则并按各自 revision 展示历史。

## 9. Compatibility and Migration

- 只做前向增量迁移；不删除旧合同、WorkingSet、版本、题目、待评结果或评分表。
- v1/v2 历史包继续按原 reader 和原 bytes/hash 读取。
- 新自动版本使用明确 Schema 版本和 reader；旧包不重写。
- 旧浏览器 Cookie API继续工作；外部凭证使用独立认证边界。
- Feature Gate 可以分别关闭跨修订重评、自动发布或外部连接入口，不破坏历史读取。

## 10. Adversarial Invariants

- 跨账号或跨 Workspace 的连接、用例、修订、待评结果和评分均 fail-closed。
- 重放、并发发布和陈旧 revision 不得丢题、重复入集或覆盖历史。
- 停用/删除阻止所有新的待评结果与评分写入，但不得使旧待评结果、旧评分或跨修订历史无法读取和解释。
- 跨修订评分必须保持同一 `question_draft_id` 并使用目标 revision 的 criterion；不能跨题评分，也不能用当前最新规则解释旧分数。
- 凭证明文、任务要求、输入内容、标准答案、坏样本、系统提示和工具原文不得进入日志、错误、SSE、Git 或 URL。
- 版本包失败不留下半发布状态；runtime 永不泄漏 judge/provenance。

## 11. Delivery Order

1. Cross-revision rescoring.
2. Question lifecycle simplification and automatic versions.
3. External authoring API and connection UI.
4. Independent `ai-eval-push` repository, real API E2E, global install and private GitHub publication.
