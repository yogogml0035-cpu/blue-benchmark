# Technical Design

## Data model

`BenchmarkQuestionDraftRow` 增加 `memory_materials_json`；`BenchmarkQuestionRevisionRow.question_snapshot_json` 包含已确认记忆材料。采用 JSON 列保持与输入文件和坏样本相同的聚合边界，不新建无独立生命周期的表。

记忆材料 DTO：`id`、`source_label`、`content_text`、可选 `summary`。服务端校验唯一 ID、非空 UTF-8、长度、禁止路径/凭证/内部字段。

## Rubric replacement

`RubricCriterion` 仅保留稳定 `id`、`name`、`description`、`pass_score`。`MAX_CRITERION_SCORE=10` 是后端常量。`RubricContent` 只持有非空 criteria，不再持有全局 `pass_threshold`。

删除所有旧字段验证与兼容读取。已存在的草稿、发布修订和人工评分使用旧 JSON 时不做透明兼容；迁移清空这些开发期表中的旧业务数据，同时保留账号、场景和外部连接。

## Scoring

评分项保留 `criterion_id`、`score`、可选理由。每项范围 `0..10`。`passed = all(score >= pass_score)`；展示总分为 `round(sum(score) / (len(criteria) * 10) * 100)`。低于本项门槛时要求理由。

## Publication and packages

发布快照保存三字段 rubric 与六类材料。`judge.json` 包含标准答案、记忆材料和 rubric；`runtime.json` 不包含标准答案、记忆、坏样本或规则，避免把判断依据泄漏给未来被测 Agent。历史包 hash 和不可变读仍沿用现有机制。

## AI boundary

Rubric Adapter 的输入模型增加记忆材料，输出结构替换为三字段。Prompt 要求维度说明可执行、基于已确认材料、不得使用标准答案字面相似度。所有输出仍经 Pydantic 和公共文本安全校验。

## Migration and rollback

新增 Alembic revision 增加草稿记忆列并清理旧 rubric/revision/score/version 相关开发数据，避免旧 JSON 与新代码混读。回滚恢复列和旧表数据结构，但被清理的开发数据不承诺恢复；实施前不触碰生产数据。
