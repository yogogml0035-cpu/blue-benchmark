# 实施计划：Benchmark 收题、发布与人工评分重构

## Parent Rule

父任务只管理需求事实、子任务顺序、跨子任务合同和最终集成验收，不作为日常业务代码分支。每个子任务完成完整分支闭环后才能启动下一项。

## Completed Baseline

- [x] `benchmark-input-answer-cocreation` 已合并、复验并归档。
- [x] `benchmark-rubric-publishing` 已合并、复验并归档。
- [x] `benchmark-human-scoring` 已合并、复验并归档。
- [x] 2026-09-01 当前 `main`：相关后端测试 14 项通过，完整 `make test` 166 项通过，OpenAPI 合同一致，`make build` 通过。

## 1. Cross-revision Rescoring

Task：`09-01-benchmark-cross-revision-rescoring`

- 先解决候选修订范围的产品问题。
- 迁移 score/revision 约束，保持 submission 正文不变。
- 让每条评分历史按自己的 revision 还原 criterion 和结论。
- 保持旧客户端同修订重评兼容。
- 完成分支、测试、提交、main 复验、归档和删支。

## 2. Question Lifecycle Simplification

Task：`09-01-benchmark-question-lifecycle-simplification`

- 场景收敛为名称 + 问题描述；新写流程取消强制场景合同。
- 增加文本坏样本及否定原因，严格隔离 runtime/judge/provenance。
- 发布即入当前正式评测集并自动生成不可变版本。
- 修改派生唯一下一修订草稿，完整发布后才替换 active；停用、恢复、删除自动留史，删除不抹除历史。
- 停用/删除阻止新的待评结果和评分写入但不阻止历史读取。
- 保留旧包 reader 和旧 bytes/hash。
- 完成完整分支闭环。

## 3. External Authoring API

Task：`09-01-benchmark-external-authoring-api`

- 新增场景绑定连接、一次兑换、最小权限 token、撤销和结构化单个评测用例草稿上传。
- 复用 Authoring Service，External Router 不直接写 Repository。
- OpenAPI 固定版本化 payload；完整测试租户隔离、幂等、并发、泄漏和存储失败。
- 场景 UI 提供连接与撤销；上传成功同步返回精确 Web 草稿 URL，且不创建 AI/rubric Job。
- 外部草稿在网站复用普通编辑合同，原上传 receipt/hash 保留；外部 token 不能读取或修改草稿。
- 所有草稿使用服务端“确认题目并生成打分规则”组合命令，避免前端连续调用确认与生成两个端口。
- rubric 审阅使用服务端“确认规则并发布到评测集”组合命令，删除新流程中的独立 confirmed-but-unpublished 状态。
- 使用真实本地 HTTP 客户端完成 E2E，再完成分支闭环。

## 4. ai-eval-push Handoff

目标：`/Users/hsikey/BenchMark/BenchMark/ai-eval-push`

- 平台 API 合并后，在目标目录初始化独立 Git 与 Trellis 规划；目录当前为空，不覆盖任何已有文件。
- Skill 名称和仓库名称严格使用 `ai-eval-push`，不擅自追加 `-skill`。
- 采用跨平台 SKILL.md + 确定性 API 客户端脚本；显式调用、上传前预览与确认、缺失标准答案阻塞。
- 凭证使用 OS keychain 或用户私有 0600 配置；禁止源码内 token、`.env`、命令回显和隐式触发。
- Skill 只概括标题，逐字保留任务要求；依赖前文时要求补充输入内容，不静默改写提示词。
- Skill 对所选输入文件上传完整原文；节选必须标注来源并确认。坏样本只取真实执行结果，不得合成。
- 坏样本的老师反馈逐字保存；Agent 摘要必须经老师确认，反馈含糊时继续追问或不上传该样本。
- 只消费真实 OpenAPI，不复制平台权限、发布或评分业务规则。
- 验证连接、预览、上传、重试、错误分流和精确可编辑草稿 URL；确认 Skill 不轮询、不触发平台 AI、也不能读取/更新草稿，再执行安全扫描和 Skill eval。
- 安装到本机全局 Agent Skills，并验证当前 Codex 可直接调用；全局入口指向源码，避免双副本漂移。
- 初始化提交后通过已授权 `gh` 创建私有 `yogogml0035-cpu/ai-eval-push` 并推送；不得提交 token、`.env` 或真实业务题目。

## 5. Parent Integration Gate

- [x] 所有剩余平台子任务均已归档，提交包含于 `main`，旧任务分支相对 `main` 无未合并提交。
- [x] `main` 干净并通过：

```bash
make openapi
make test
make build
git diff --check
```

- [x] 浏览器走通：场景连接 -> 本地单题上传 -> 草稿审阅 -> rubric -> 发布即入集 -> 停用/恢复/删除 -> 历史回查。
- [x] 修改已发布用例走通：派生草稿 -> 旧版继续生效 -> 新版发布原子替换；覆盖放弃、停用、恢复与删除草稿。
- [x] 验证两个组合动作各只有一个主按钮；生成/发布任一步失败都能恢复且不制造半状态。
- [x] 人工评分走通：待评结果首次评分 -> 同修订重评 -> 同用例跨修订重评 -> 跨用例拒绝 -> 停用/删除后所有写入拒绝且历史仍可读 -> 恢复后重新开放。
- [x] 版本包检查：旧 v1/v2 hash/bytes 不变；新 runtime 不含标准答案、坏样本、rubric、评分或凭证。
- [x] 权限、并发、幂等、恢复、泄漏、迁移、删除、存储和 Git 凭证做最终对抗审查并修正。
- [x] README、`.trellis/spec/` 和 `.interface-design/system.md` 与最终源码事实一致。
- [ ] `ai-eval-push` 全局安装与私有远端均由实际路径、调用和远端 URL 验证（本地安装、调用和私有仓库创建已完成；GitHub push 因 github.com:443 网络不可达，尚未完成远端 branch 验证）。

## Risky Boundaries

- `backend/app/lib/database/models.py` 与迁移：只前向增加/调整约束，不删历史行。
- `evaluation_sets` 发布/版本包：数据库与文件系统使用 staging/ready/reconciliation，不能伪装跨介质原子事务。
- `human_scoring`：每条 score 的 revision 与历史展示必须一致。
- `auth`：外部 token 不复用 Cookie，不进 URL，不授予跨场景读取。
- `version_packages`：旧 reader/bytes/hash 不被新自动版本覆盖。
- 生成文件只通过 `make openapi` 更新。

## Rollback

- 三项新能力分别 Feature Gate；关闭写入口不影响旧用例、旧包、待评结果和评分读取。
- 不通过 downgrade 删除生产历史；回滚应用版本时保留新增列/表和不可变资产。
