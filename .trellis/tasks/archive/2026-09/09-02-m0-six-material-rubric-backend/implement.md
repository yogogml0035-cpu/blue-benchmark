# Implementation Plan

- [x] 建立当前题目聚合、六类材料、两字段维度、状态和内部 revision 数据模型。
- [x] 实现原子批量收题、场景凭证隔离、命令幂等与统一题库查询 API。
- [x] 新增 Alembic migration，并补 upgrade/fresh DB 验证。
- [x] 替换 Rubric schema、AI DTO、Fake/production adapter 与 Prompt。
- [x] 实现自动生成、逐题失败/重试、“保存并重新生成”和直接覆盖发布状态。
- [x] 更新所有后端测试、fixtures、验收 runner 和 OpenAPI。
- [x] 搜索并删除旧 Rubric 字段与全局阈值语义。
- [x] 搜索并删除旧手动 ingestion/co-creation、人工评分/重评的路由、模型、Operation kind、配置、脚本、测试与文档。
- [x] 运行 `python -m compileall app scripts tests`、`pytest -q`、OpenAPI 漂移与迁移检查。
- [x] 对权限、幂等、并发、泄漏、旧数据和每项及格进行对抗审查。
