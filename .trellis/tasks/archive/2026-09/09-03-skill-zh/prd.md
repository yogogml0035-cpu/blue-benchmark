# 题目上传 Skill 文档中文化

## Goal

将 `skills/ai-eval-push/` 中面向使用者（中文业务老师及其本地 Agent）的文档从英文翻译为中文，使老师在自己的 Agent 环境中使用该 Skill 时获得一致的中文体验。

## Background

平台的业务老师是中文用户。`skills/ai-eval-push/` 是老师侧唯一直接使用的组件：本地 Agent 读取 `SKILL.md` 决定如何与老师交互（识别题目、预览确认、报告结果），`references/api-contract.md` 是 Agent 构造批次时的合同参考。这两份文档目前是英文，与中文用户场景不一致。

## Requirements

- `skills/ai-eval-push/SKILL.md` 正文与 frontmatter `description` 翻译为中文。
- `skills/ai-eval-push/references/api-contract.md` 翻译为中文。
- 翻译是语义完整的重写，不是逐句机翻；保持现有文档的信息量，不新增或删除行为约定。
- 机器合同相关内容保持原样：字段名（`task_prompt`、`client_case_id` 等）、错误码（`BATCH_CASE_INVALID` 等）、脚本失败前缀（`config-error`、`invalid`、`upload-failed` 等）、HTTP 路径、JSON 示例、命令行示例、长度限制数值。
- 在 `SKILL.md` 中明确一条约定：与老师的所有交互（预览、确认、结果报告）使用中文。
- 不修改 `scripts/push_eval_cases.py`、`tests/` 与后端代码；脚本输出文案保持英文（由隔离测试固定，Agent 负责转述给老师）。
- 同步检查仓库内其他文档对这两份文件的描述是否仍然准确。

## Acceptance Criteria

- [ ] `SKILL.md` 全文为中文（含 frontmatter `description`），机器标识符保留英文。
- [ ] `references/api-contract.md` 全文为中文，字段限制表、错误码表数值与原合同一致。
- [ ] 翻译后的 `SKILL.md` 工作流仍覆盖原有全部步骤与约束（识别、六类材料、隐私自检、预览确认、落盘校验、上传、失败处理、配置）。
- [ ] `skills/ai-eval-push/tests/` 全部通过（文档变更不影响脚本行为）。
- [ ] `git diff --check`、`make test` 通过。
- [ ] README 中「题目上传 Skill」一节的描述与翻译后的文档不冲突。

## Out of Scope

- 脚本 `push_eval_cases.py` 的输出文案与注释翻译（测试固定英文输出；如需中文化另开任务）。
- 后端接口错误信息的中文化。
- SKILL.md 行为逻辑的任何变更（仅语言转换 + 明确中文交互约定）。
