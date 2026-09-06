# C3 实施与验收

## 进入条件

- 检查 C1（09-06-m0-rubric-real-samples）和 C2（09-06-m0-rubric-deep-runtime）完成/归档记录、交付提交及 main 复验；不能只看 meta.depends_on 或目录存在。
- 本任务明确获批后，从最新已验证 main 创建 codex/m0-rubric-atomic-cutover 独立 worktree，复制 .env 并覆盖独占验收目标。
- 读取 C1/C2 已合入的实际代码与接口，不依赖上游 worktree 私有文件；每个验证输入由 C1 代码重新构建。

## 实施顺序

1. 锁定完整 rubric、thread/消息/删除 operation 合同；同步 schema/migration、Pydantic、OpenAPI 与生成 TypeScript，不手改生成文件。
2. 把 C2 接入 RubricGenerator 与 production Worker，完成受限材料读取、联合结果和生成/编辑分离校验。
3. 实现业务 thread/revision 映射、完整消息持久化、SSE、预算/失租/过期保护、断线与重启恢复。
4. 实现跨库删除冻结、独立清理作业及状态投影，覆盖所有历史 thread、原文和缓存；保留原门禁。
5. 完成维度编辑器、依据/分档、改分核对、确认重生成和真实加载时间线；更新删除确认后的处理/失败/完成交互。
6. 同步 fake/fixtures、API/前端测试与真实验收 runner，使用 C1 数据和隔离 PostgreSQL；删除被替代路径和所有验收占位兜底。
7. 运行核心真实业务闭环与恢复/删除检查，完成分支/main 全量质量门，记录新合同和维护规格后交接 C4。

## 必须同任务完成的删除清单

- 旧单次生产 generator、两字段完成断言、旧缺字段读取/转换/保存丢失、静态假进度分支。
- DELETE 提前成功、handleDelete 收到响应就跳转、清理失败误投影生成失败、需要模型可用才能清理的路径。
- 相关真实验收脚本的旧 ZIP 强依赖、前 800 字截断、缺失答案占位和假 Bad case 冒充真实来源。
- 只删除被替代行为；criterion/pass_score、正常 GET、测试用 fake 和最终事务硬删除仍有用途时保留。

## 质量门

```bash
git diff --check
make openapi
make frontend-generate-api
make contract-check
make frontend-check-api
make test
make build
make frontend-e2e
```

- 使用已更新的 ai-smoke、accept_real_ai_rubric 与 accept-web 入口跑两组真实来源；必须明确 production Worker、PostgreSQL、事件/检查点及结果关联。
- 核心回归包括任意整数、建议分描述、全部字段保存、普通编辑不覆盖、确认重生成、原文回放、重复输入与旧写防护。
- 删除核心测试覆盖原门禁、同题全部历史、处理失败可重试、存储无残留和兄弟题隔离，不能留给 C4 才实现。
- 定向检索 backend/app、tests、scripts、frontend/src/e2e/scripts、README、Makefile、规格；逐项解释剩余旧标识符，不用零命中替代语义检查。

## 完成与回退

- 每个核心验收必须有本次证据；源码接入或 HTTP 200 不算闭环。C4 后续扩大故障覆盖，不豁免本任务基础验证。
- main 包含本任务提交且重复通过完整质量门后才能按 Trellis 关闭本子任务；现有旧数据库与旧演示环境尚未切换，不能报部署完成。
- 不清理当前项目两库或源样本，不把 C5 的一次性 reset 提前放进 migration/应用启动。
