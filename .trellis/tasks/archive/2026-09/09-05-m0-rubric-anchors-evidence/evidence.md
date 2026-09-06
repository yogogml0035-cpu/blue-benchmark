# 父任务总验收记录（M0 评分维度：分档辅助、可核查依据与生成链路重构）

日期：2026-09-06。验收基线：main@64d1003（C5 归档提交），最终收尾提交见本文件合入记录。

## 1. 子任务交付矩阵（全部完成、归档、main 包含）

| 子任务 | 交付 | main 提交链 | 归档证据 |
| --- | --- | --- | --- |
| C1 真实样本与基线 | m0_samples 提取模块（hash 门禁、F/M 两组证据完整 case、6 派生反例、15 独立预期） | 97a595b → f777492 | archive/2026-09/09-06-m0-rubric-real-samples/evidence.md |
| C2 持久运行基础 | deep_runtime 原语（受限装配/事件归一/PG 检查点会话/线程锁/无模型清理）+ 0.7.13 锁定 + 真实探针 | cdf7aee → e68e9a1 | archive/2026-09/09-06-m0-rubric-deep-runtime/evidence.md |
| C3 业务一次性切换 | 完整评分项合同、生产接入、持久消息/SSE、审改 UI、受理式完整删除、旧语义删除 | 9ceb902…5f1b465 → dcc1a64 | archive/2026-09/09-06-m0-rubric-atomic-cutover/evidence.md |
| C4 系统验收与加固 | 故障注入矩阵（失租/跨题/部分清理崩溃/晚订阅）、真实 Worker 击杀重启恢复、运行身份证据 | 2d2616e/b8df472/9db7eb4 → 7b59736 | archive/2026-09/09-06-m0-rubric-system-validation/evidence.md |
| C5 本地切换与交付 | reset_local_data 安全重置工具（27 定向测试）、两库一次性切换执行、生产栈交付 | 2aef270/d09f13d/e22d8fe → 64d1003 | archive/2026-09/09-06-m0-rubric-local-release/evidence.md |

所有声称 SHA 经 `git merge-base --is-ancestor` 独立复核包含于 main；基线链自洽（C1→C2→C3→C4→C5 依次以上一收尾提交为基线）。

## 2. 最终串联全链路 E2E（main@64d1003，本次运行，日志 /tmp/pf-*.log）

- `git diff --check`=0；`RUNTIME_PG_REQUIRED=1 pytest`：194 passed / 0 skip；`make build`=0；`make frontend-e2e`：44 passed（生产构建，E2E_PORT=3141）。
- `ai-smoke`（真实 Provider gpt-5.6-luna + C1 真实 F case + skill_eval_pf_smoke_ckpt）：`AI_SMOKE=OK criteria=4 message_delta=5448 tool_calls=10 elapsed=125.1s`。本次 `run_completed=2` 与 stage=23：发生了一次设计内的**有界修订轮**（首轮引用校验未过 → 同 thread 修订 → 二次图完成），修订机制在真实模型上的自发成功运行，非异常。
- API 真实验收（skill_eval_pf_api{,_ckpt}）：`ACCEPT_REAL_AI=PASS`——两组 C1 真实样本、F 组预算截断→检查点恢复、引用逐字核验、任意整数保存、发布/重开、受理式删除双库零残留、兄弟题完好；run_identity 记录 git SHA/模型指纹/SDK 版本/库名。
- Web 真实验收（skill_eval_pf_web{,_ckpt}）：`M0_WEB_ACCEPTANCE=PASS`——live 增量先于完成到达浏览器（经实际 Next rewrite）、生成中晚订阅回放、刷新恢复不重复生成、**真实 Worker SIGKILL→租约过期→新 Worker→thread_state_incomplete 恢复（events=154，run_started≤1 证明初始输入不重复）**、完整合同/引用浏览器侧核验、依据面板、发布/重开、删除以 404 为准导航、按删除前捕获 thread 清单核验检查点零残留。

## 3. 多智能体对抗式审查（父任务层，双代理终审）

- **旧语义清理终审**：可执行旧路径 **零残留**（旧生成器/两字段假设/204 删除/静态假进度/轮询/800 字截断/EvalData ZIP/占位答案/假 Bad case/兼容开关全部清零；criterion/pass_score 字段、正常 GET、fake 测试模式、最终事务硬删除为合法保留）。发现 1 Major（维护规格 stub-state-and-contracts.md 残留旧两字段口径句 + worker 投影句陈旧）与 2 处代码 docstring 旧词——**已在本次收尾提交修复**（spec 改为完整评分项口径 + kind 分派投影表述；`question_library/__init__.py` 与 `schemas.py` 分节注释更新）。
- **跨子任务一致性终审**：D01-D23 交付映射逐条对账**全部一致**（含 D19 无跨题 Store/检索的 grep 实证、D21 切换记录与备份实存核验、D13 版本锁定与漂移测试）；prd 验收口径 20 条逐条判定**20/20 覆盖**（第 17 条文档同步缺口即上述 Major，修复后闭合）；五个子任务 evidence 声称与仓库/日志抽查**零不实陈述**；交付环境只读核查通过（healthz ok / registration_available=true / 两库空 / 源 hash 不变 / 交付进程与 C5 记录 PID 一致）。
- 子任务层历轮对抗审查（C1 双代理、C2 双代理+二轮复核、C3 双代理+二轮复核、C4 矩阵审查、C5 重置工具专项）共发现并修复 4 Critical + 15 Major，全部有回归测试锁定，记录见各子任务 evidence.md。

## 4. 一次性切换与交付环境（C5 执行，父任务复核）

- 2026-09-06T14:45:05Z 按授权对 skill_eval / skill_eval_checkpoint 执行一次性重置：容器双目标身份核验、pg_dump 备份（115,959 / 10,847,603 bytes，sha256+字节比对+TOC 校验）存 `_artifacts/m0-rubric-anchors-evidence/c5/20260906T144505Z/`、schema 重建、Alembic head 0021、加密 checkpointer 准备、后核验空库。
- 源文件保护：6 个业务样本 sha256 切换前后 diff 为空。未动 volume/角色/.env 密钥/其他库/.local-samples。
- 交付栈（nohup 脱离会话，主工作区 main@64d1003）：API :8000（uvicorn 72997）、Worker（73006）、前端生产构建 :3000（next-server 73032）；日志 `storage/runtime/*.log`；本地 URL <http://127.0.0.1:3000>，首次进入引导创建新管理员（旧账号/会话/凭证随授权重置失效）。

## 5. 已知限制与技术债（如实单列，不伪装已解决）

- langgraph 出现 “Deserializing unregistered type RubricGenerationResult” 警告：当前版本不阻断，未来 langgraph 升级可能要求注册序列化类型——升级时须重跑 C2 原语与 C3/C4 集成门（登记为技术债）。
- 隐藏/恢复页签（visibilitychange）行为无自动化覆盖；SSE 游标重连逻辑有测试，浏览器后台节流场景未自动化。
- 上下文摘要压缩后“回放原文与直播增量逐字一致”仅有实现保证与计数断言，无逐字比对测试。
- 墙钟预算只在调用边界检查：单次超长模型调用可越过时长上限（provider request timeout 兜底）。
- runtime-design.md 中“本轮不执行清理”等表述为**切换前历史快照**（C5 已实际执行），按归档口径不改写。
- 老师（用户）对生成维度的**业务质量认可**是产品使用环节，本任务证据只覆盖程序化合同/引用/链路验证，不代称“老师已认可”。
- API 验收的双库零残留断言在脚本内 fail-closed（PASS 蕴含通过），日志可读性弱于 Web 侧 residue_verified 行。

## 6. 完成条件判定（task-map「父任务完成条件」）

1. C1-C5 各自独立验收 + main 提交 + 复验证据 + Trellis 完成记录：**满足**（第 1 节）。
2. 共享合同和维护文档与 main 一致；SDK/任意整数/完整消息恢复/关联删除/本题隔离/真实样本交叉核验：**满足**（第 3 节，文档缺口已修复）。
3. C5 两库切换 + 真实运行身份/URL 检查 + 源文件不变：**满足**（第 4 节）。
4. 父任务只汇总收尾，未启动新的未分派生产修改：**满足**（本收尾提交仅文档/注释/任务状态）。

**判定：父任务达到完成条件，M0 评分维度重构任务树验收通过。**

## 7. 收尾提交

- 文档同步 + 本记录 + task-map/task.json 收尾 + 父任务归档：见后续提交（合入 main 后以 `git log` 为准）；规划 worktree/分支随后清理，交付服务运行于主工作区不受影响。
