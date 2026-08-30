# M0 真实 AI E2E 验证与加固设计

## 1. 验证问题

当前自动化绿色只说明 Fake adapter、临时 SQLite 和 TestClient 合同可运行；真实 Provider、业务 PostgreSQL、加密 Checkpointer、常驻 Worker 与真实浏览器路径必须分别被观测。验证目标是证明真实输入经过真实 AI 和真实持久化后，仍能到达一个可回查、不可变、三视图隔离的 M0 v1。

## 2. 证据分层

1. 配置证据：只输出运行模式、Provider、模型和各凭证 `present/length` 等布尔或长度信息。
2. 组件证据：Provider 结构化 smoke、业务 DB schema、Checkpoint setup/read/write、Worker fail-closed 和 adapter tool surface。
3. 跨层证据：真实样本上传到冻结下载包的状态转移、业务行与 operation attempt、哈希/隔离机械检查。
4. 交互证据：运行中的 API、单 Worker、前端和浏览器动作；所有状态以服务端 projection 为准。
5. 对抗证据：独立 reviewer 先找漏洞，再用复现和回归闭环；不能以既有报告中的“已修复”替代当前 checkout 的实测。

## 3. 运行隔离

- 从已验证 `main` 创建短生命周期分支；不占用与本任务无关的 `server-deployment-planning` 活跃 planning 任务。
- PostgreSQL 使用本机临时 Docker 实例、独立业务库和 Checkpointer 库；真实 `.env` 的 AI 设置保持生效，数据库/存储通过进程环境覆盖到本次隔离实例，不连接远端。
- 每次真实 E2E 使用 `/Users/hsikey/BenchMark/EvalData` 中的三份输入、唯一临时 `STORAGE_ROOT` 和业务账号/场景；不打印响应正文，只保留阶段、ID 数量、状态、哈希比较结果和错误类型。
- Worker 只启动一个实例；API、Worker、前端的 PID/日志进入明确临时目录，日志收尾前做凭证/正文扫描。

## 4. 链路覆盖

```text
real AI config
  -> provider ToolStrategy smoke
  -> PostgreSQL migration + encrypted Checkpointer setup
  -> API upload 202
  -> real Worker batch analysis
  -> role/visibility + task grouping
  -> real Worker contract/judgment co-creation
  -> teacher confirmation + projection
  -> draft include + coverage review
  -> freeze job + immutable package
  -> manifest/API/download equality + runtime isolation
  -> browser refresh/restart/private-access checks
```

共创必须保留“老师确认”这一业务边界：真实 AI 只提出候选问题/结果，脚本或浏览器不会把 AI 候选直接当作标准。真实样本闭环沿用归档验收的两个任务、三次 attempts、两道题和一个 v1 约束。

## 5. 变更边界

- 首选只增加验证脚本/测试和必要的局部修复；不重写 M0 业务模型，不新增并行 DTO，不引入 Celery/Redis，不实现 M2。
- 若缺陷属于业务 Feature，修复放在其 Router/Service/Repository/Schema 实际所有者；跨层合同变更必须从 Pydantic/OpenAPI 开始并重新生成前端类型。
- 若仅是环境策略（如 pnpm build approval），优先使用可审计、可恢复的项目级配置或在验证记录中隔离运行，不把临时机器状态提交为产品行为。

## 6. 释放与成功定义

成功不是单个 HTTP 200，而是输入、AI 候选、老师确认、业务持久化、Worker attempt、Checkpointer 指针、版本 Manifest 和下载字节可互相对上；任何一段只能静态检查或 Fake 的结论必须单独标注。完成前必须在合并后的 `main` 重跑项目质量门。
