# 旧 M0 语义删除清单

## 已确认删除的业务链

1. 网页手动上传原始文件、解析文件用途、AI 分组和共创建题。
2. Working Set 手动组集、覆盖审查和版本包冻结链。
3. 待评结果上传、人工评分和跨修订重评。

## 当前源码中的主要删除候选

- `case_builder` 的 legacy case、ingestion、task package 和 co-creation 路由、服务、仓储与 Schema。
- 原文件上传、ZIP 解包、文件用途确认、解析状态和 evidence 对象存储。
- `evaluation_sets` 的 working-set、coverage 与 v1/v2 version-package 组装逻辑。
- `human_scoring` 整个 Feature 及 submission/scoring 存储回收逻辑。
- 对应数据库 Row、Alembic 迁移后的旧表、OperationJob kind、AI Adapter、测试和验收脚本。
- README、Makefile、OpenAPI 和 Trellis spec 中只描述旧链路的内容。

## 保留判断

只有新链路真实使用的通用基础设施可以保留，例如数据库 session、OperationJob 租约/重试机制和 AI Provider adapter 基础。保留时必须去掉旧业务名称与旧路由依赖，不能把“以后可能有用”作为保留完整旧 Feature 的理由。

## 数据迁移原则

用户已明确不兼容历史数据。迁移应删除旧业务表或清理旧记录，新代码不读取旧 JSON、不双写、不提供旧 API。迁移与回滚仍需可执行，但回滚只恢复 schema 能力，不承诺恢复已删除的开发期业务数据。
