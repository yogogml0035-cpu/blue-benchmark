# Technical Design

删除前端源码与专属配置。根 Makefile 收敛为 `backend`、`worker`、`start-all`、`openapi`、`contract-check`、`test`、`build`、数据库与 AI smoke 命令，其中 `start-all` 只启动 API 和单 Worker，`build` 执行后端编译/导入验证。

`backend/openapi.json` 保留为机器合同；`scripts/verify_openapi.py` 对当前 FastAPI 动态 schema 和已提交文件做比较，不再生成 TypeScript DTO。

外部收题响应返回待处理题目、场景、评分维度生成状态和稳定 API 资源路径，不返回旧网站绝对 URL。浏览器同源保护替换为可配置允许来源；无 `Origin` 的 CLI/Skill Bearer 请求保持可用。

`backend/scripts/` 增加管理员 CLI，调用现有 Service 层完成场景创建和场景凭证的生成、轮换、撤销与状态查询。CLI 不直接拼装数据库 Row；明文 token 只在生成时显示一次。

删除前端规范后，更新共享跨层指南，把数据流改为 Client/Skill/Future UI -> API -> Service -> Repository。
