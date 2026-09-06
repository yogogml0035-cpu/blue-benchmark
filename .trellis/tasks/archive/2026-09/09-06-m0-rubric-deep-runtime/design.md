# C2 设计：底层能力与生产切换分离

## 架构边界

- 按 .trellis/tasks/09-05-m0-rubric-anchors-evidence/runtime-design.md 的原语部分实施，业务 thread 映射、公开日志表、SSE 和删除业务流程留给 C3。
- 在现有 backend/app/lib/ai_runtime 目录提供可被 C3 直接复用的运行组件；不复制业务 Feature，不建立临时双 DTO 或另一套生产生成器。
- 输入由调用方传入本题材料视图、稳定 thread/运行上下文、工具与结果 schema；输出为事件及最终候选，业务保存权仍在服务层。
- C1 提供取样代码与来源合同，探针在本任务 worktree 重建私有输入，不能读取已经清理的上游 worktree 产物。

## 运行原语

- 按真实发布版本构造 create_deep_agent、StateBackend 和 PostgresSaver，显式验证权限与默认委派关闭；不挂载全局 Store。
- 材料只读，workspace 和框架历史/大工具结果目录在线程状态内持久化；拒绝跨题定位、路径穿越与宿主机访问。
- 原生流式事件转成受控公开反馈；排除私有 reasoning、系统提示、凭证和未授权工具正文。本任务仅提供事件接口，不在此自建业务持久日志。
- 少量 class-based middleware 管观测、受限调用和必要 state update；不把 per-run 用户/计数存到共享 self，不吞 interrupt/cancel。
- 同步 Worker 对应同步运行能力；连接覆盖完整执行期，sync durability 和同线程单写者按实际版本验证，不同时维护未验证的异步旁路。
- checkpoint 删除、线程锁和资源关闭是不调用模型的原语；不会因 Provider 初始化失败而变成必须先生成才能清理。
- 调用/工具/重试/摘要计数暴露给 C3 的全作业预算所有者；先设有限探针预算，不能把长等待当无限循环。

## 验证环境

- 使用当前 Docker PostgreSQL 的本任务独占验收库，原项目 skill_eval / skill_eval_checkpoint 不执行 reset/setup/删除。
- 配置从被忽略的 .env 读取后显式覆盖测试目标；密钥只验证格式/可解密，不输出、不轮换。
- 探针使用测试结果 schema，不接收/保存正式评分项；对最终生产 schema 与业务回放的证明由 C3/C4 提供。
- 测试分别报告 stub 合同结果、真实 Provider 结果与 PostgreSQL 恢复结果。保留可追溯 ID/版本/耗时，不提交正文。

## 旧路径边界

- 本子任务未替换生产生成语义，因此保留当前产品路径，不声称重构完成。
- 不把新组件注册成可选择的生产模式，不增加迁就旧教程的降级逻辑；C3 接入时删除被替代旧生产路径。
- 依赖或 model.py 的变更必须保持当前调用测试通过，不能用未来 C3 会修复作为损坏 main 的理由。
