# Technical Design

Skill 采用简短 `SKILL.md` + 确定性 Python 客户端脚本 + API 合同 reference。Agent 负责从当前上下文组织候选和向老师确认；脚本只负责读取配置、严格校验 JSON、生成或复用 `command_id`、执行 HTTP 请求和归一化错误。

本机配置优先从 `AI_EVAL_BASE_URL`、`AI_EVAL_ACCESS_TOKEN` 环境变量读取；可选用户级配置文件必须位于仓库之外并要求安全权限。仓库只提供无秘密示例。

真实上传前，Agent 必须展示六模块预览并获得当轮明确确认。脚本不接收 workspace ID；场景只能由 Bearer token 决定。

记忆材料只接收 Agent 已实际读取并选择的片段，保存安全来源标签、原文和可选摘要；脚本执行路径/秘密扫描并拒绝风险内容。
