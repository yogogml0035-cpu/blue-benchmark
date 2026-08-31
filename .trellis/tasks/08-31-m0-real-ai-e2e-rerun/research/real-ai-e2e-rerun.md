# M0 真实 AI E2E 重跑记录

日期：2026-08-31

## 输入与环境

- 样本严格来自 `/Users/hsikey/BenchMark/EvalData` 顶层恰好 3 份文件：1 份 Markdown、1 份 JSONL、1 份 ZIP；ZIP 展开后为 3 份 Markdown，共 5 份证据文件。
- API、单 Worker、runner 使用当前 `AI_RUNTIME_MODE=production` 和已配置 Provider；业务库与 Checkpointer 是同一临时 PostgreSQL 17 实例上的两个独立数据库，storage 为本轮临时目录。
- `AI_MAX_COCREATION_QUESTIONS=1` 是成本受控的 smoke/fallback 边界，不代表默认 12 轮的延迟、成本或质量压力基线。

## 首次失败与修复

首次真实执行已经通过迁移、Checkpointer setup、Provider 调用、上传/解包、批次分析和资料角色确认，但在相同任务分组命令重放处失败：首次创建按教师提交顺序返回，幂等回读查询没有 `ORDER BY`，PostgreSQL 不保证无序结果顺序。修复为保存 `grouping_order`、首次与回读遵守同一顺序，并补 API 回归；没有放宽 runner 断言。

## 最终真实链路

最终命令使用：

```bash
cd backend && uv run python scripts/accept_real_ai_e2e.py \
  --samples-dir /Users/hsikey/BenchMark/EvalData \
  --base-url http://127.0.0.1:8000
```

结果：

- `make ai-smoke` 真实结构化调用通过；
- 3 份顶层资料上传并展开为 5 份证据，批次完成真实 AI 整理；
- 资料角色确认、2 个任务/3 个 attempts、任务分组幂等、场景合同共创和两道题判定依据共创完成；每个共创均保留 1 个老师回答并由老师确认完成式候选；
- 下一版草稿、覆盖风险确认、冻结排队和 v1 版本包完成；包包含 4 个预期条目，Manifest、runtime/judge/provenance 三分区 bytes/hash 和下载身份一致，runtime allowlist 未包含评分依据、老师判断、形成记录或凭证；
- runner 输出 `M0_REAL_AI_E2E_STAGE=complete`，runner exit 0；本轮日志未命中实际 AI key、Checkpointer key、authorization、api_key、private_reasoning、thread/checkpoint 字段或样本文件名。

合并到 `main` 后，第一次标准 production Worker 重跑在第三道 `mega-judgment` start 进入清洗后的 `OPERATION_FAILED`；第二次用同一隔离配置的模块化诊断 Worker 越过该阶段并完整通过，随后第三次使用未包装的标准 production Worker 也完整通过。由此把第一次记录为真实 Provider/结构化调用瞬时失败，不把单次绿灯表述为长期稳定性；本轮没有观察到固定代码异常。

## 浏览器真实回归

单独隔离栈上，真实浏览器完成账号注册、私有场景创建、同三份文件上传，页面观察到上传 `202`、后台“正在处理”到“处理完成/确认资料用途”，刷新后仍恢复服务端快照。390px 窄屏导航进入 Dialog，Escape 后焦点回到“切换工作区导航”。旧 `/cases/new` 重定向到工作台，旧 case ID 重定向到题稿路由并显示 `RESOURCE_NOT_FOUND`；第二账号访问第一账号场景得到 `403` 且没有私有内容。

## 证据边界

runner 证明了文件已上传、已安全解包、进入真实 batch analyzer 的受限输入并形成最终包；随后任务分组是老师/runner 提交的业务确认，不证明真实模型逐行使用了每份文件。M0 仍不包含 M2 Skill/Agent 执行、Judge 或评测报告，也没有把本轮 1 轮预算外推为长轮基线。
