# 凭证绑定与分发机制改造

## Goal

让 ai-eval-push 技能以脚本内硬编码占位符承载场景凭证：绑定=直接替换脚本内值，删除环境变量链路；平台侧凭证与场景严格 1:1 并支持明文可见/核对，使技能可打包分发给同事零配置使用。

## 结构与结果

父任务拆分为两个可独立验收的子任务，均已完成并合入 `main`：

1. **`09-04-skill-credential-binding`（技能侧，已归档）**
   `skills/ai-eval-push/scripts/push_eval_cases.py` 顶部 `BASE_URL` / `ACCESS_TOKEN` 以 `"***"` 占位符出厂；绑定=直接替换脚本内值；删除 `AI_EVAL_BASE_URL` / `AI_EVAL_ACCESS_TOKEN` / `AI_EVAL_CONFIG` 全部环境变量链路；SKILL.md、测试、验收 harness、前端签发提示词同步切换。仓库副本永远保持占位符，只绑部署副本。
   - 部署副本 `~/.agents/skills/ai-eval-push/` 已用新版替换并完成首次绑定验证（场景「汽车多品牌多品类文案」）。

2. **`09-04-platform-credential-one-to-one`（平台侧，已归档）**
   凭证与场景严格 1:1：创建/轮换合并为单一动作；数据库持久化明文（`token_plaintext`，撤销/替换即清空）供管理员小眼睛查看；迁移 0020 完成存量多凭证归一（保留最新、其余作废 `model-migration`）；admin CLI 合并为 `credentials replace`。

## 关键决策（需求访谈确认）

- 凭证落盘为裸明文（需求方明确接受该安全降级），撤销/替换时清空。
- 场景页默认掩码（前 7 后 4），小眼睛按需拉取完整明文；只展示当前有效凭证，无历史列表。
- 创建/轮换单按钮：无凭证=创建，有凭证=替换。
- 旧模型存量凭证无明文（仅哈希），界面以“不可查看”呈现，替换后恢复，绑定继续有效。

## 遗留（待需求方决定）

- 本地 `main` 与 `origin/main` 的推送时机。
- `~/.zshenv` 的 `AI_EVAL_CONFIG` 导出与 `~/.config/ai-eval-push.json`（新机制已不读取）的清理。
