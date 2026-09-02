# Implementation Plan

- [ ] 更新 authoring/external schemas、repository、service 与数据库模型。
- [ ] 新增 Alembic migration，并补 upgrade/fresh DB 验证。
- [ ] 替换 Rubric schema、AI DTO、Fake/production adapter 与 Prompt。
- [ ] 替换发布、版本包和人工评分计算。
- [ ] 更新所有后端测试、fixtures、验收 runner 和 OpenAPI。
- [ ] 搜索并删除旧 Rubric 字段与全局阈值语义。
- [ ] 运行 `python -m compileall app scripts tests`、`pytest -q`、OpenAPI 漂移与迁移检查。
- [ ] 对权限、幂等、并发、泄漏、旧数据和每项及格进行对抗审查。
