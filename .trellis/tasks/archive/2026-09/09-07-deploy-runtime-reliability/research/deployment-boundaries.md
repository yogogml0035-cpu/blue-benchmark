# 部署修复证据与规划边界

## 基线身份

- 检查日期：2026-09-07。
- 本地 main：`6bf0d3d7c59b04fedc7198e853d86622cbe96331`，创建任务前工作区干净。
- `git ls-remote origin refs/heads/main` 返回 `f8fbb0719028c9e7435d990e100f2919927e89d5`，与本地 origin/main 一致；本地 main 领先 46 个提交，远端没有独有提交。本次不推送。
- 专属 worktree 创建后已核对目录、分支、干净状态及 worktree 清单；不修改主工作区。
- 历史主线质量证据见 `.trellis/workspace/hsikey/journal-1.md:689`、`:702`。前一轮只读审查另通过 43 项定向测试、OpenAPI、Compose 配置与 Shell 语法检查；这些都不替代实施后的完整门禁。

## 当前事实

1. `deploy/compose.yaml:73` 的 PostgreSQL 服务使用一个 pgdata 卷。业务库和 checkpoint 库在同一实例中，但逻辑上是两个数据库。
2. `deploy/.env.production.example:22` 已规定独立 checkpoint 数据库和 AES 密钥；`deploy/server-setup.md:136` 的首次启动流程已包括建库。用户选择服务器全新建库，因此无需为旧库增设兼容迁移。
3. `deploy/backup.sh:30` 至 `:49` 的现行成功路径只覆盖业务库和文件；服务不停写；失败退出仅清理临时目录。当前脚本没有跨库一致性、checkpoint 备份或完整恢复点判定。
4. `deploy/restore.md:32` 至 `:51` 只重建业务库并恢复文件，不恢复 checkpoint。文件解包命令中的 STAMP 位于容器 shell 的单引号代码中，且未显式传入容器；完善恢复步骤时需同时验证该实际命令能找到对应归档。
5. `backend/app/lib/ai_runtime/deep_runtime.py:633` 的 open_session 使用独立 PostgreSQL 连接和加密 saver；丢失 checkpoint 或原密钥不能由业务库备份补回。线程登记与运行事件在业务库中，单题删除也跨两库。
6. `deploy/nginx/nginx.conf:21`、`:25` 使用静态上游域名，没有运行时 DNS 刷新。`deploy/compose.yaml:17` 的依赖只声明健康启动顺序，没有随依赖更新重启的声明。
7. `backend/app/features/question_library/router.py:264` 的 SSE 响应已有 `X-Accel-Buffering: no` 和 keepalive；代理修复需保留，不能仅因新增流式而推断当前必然被缓冲。

## R1 已确认的最新一套策略

用户于 2026-09-07 明确允许每日备份导出期间短暂停止 API 和 Worker，选定三处结合后又明确“三处都保留最新，没有必要保留旧数据”。因此流程采用：预检并记录服务状态，停止本项目 API/Worker，确认停写后导出两库和文件，恢复服务，再更新服务器及 OSS 最新完整副本；Mac 由用户每日下载并校验后覆盖自身旧版，不再次导出。服务器 7 天与 Mac 30 天建议均已撤销；最终实施批准仍待本轮摘要确认。

用户是部署初学者，要求 OSS 教程并接受此前解释的费用示例，准备自行领取免费试用。ACR/OSS 是否已开通尚未验证，本任务不会开通或修改云资源。每日流程恢复到最后成功备份的限制仍需在最终摘要中写清，不能把三处保存描述成实时零丢失。

实现设计需覆盖：

- 不直接 shell source 不受信任的 .env；通过已有结构化配置或容器环境解析数据库目标，禁止输出含密码 DSN。
- 仅支持已确认部署拓扑，不连接任意外部数据库，不误备份 PostgreSQL 默认库；从当前配置核对两个目标。
- 以明确恢复点组织产物、校验和及无密钥的必要元数据；OSS 完整性校验及全部对象确认完成后才标记完整服务器外副本成功。不混淆本盘导出、OSS 上传和用户 Mac 下载的完成状态。
- 原 AES 密钥使用独立安全渠道保管，不打入普通备份日志或 Git。说明丢失密钥的后果。
- 服务停止、第二个库导出、文件归档、服务恢复及上传各阶段的故障注入；失败路径与中断信号不静默遗留停机，且不擅自启动原来停止的服务。
- 若 API 已停止，不能继续使用 docker compose exec api 打包；使用不启动应用入口、只读挂载原文件卷的受控一次性容器或等价方式。
- 明确“首次还没有 checkpoint 表”的有效空库与“checkpoint 数据库根本不存在”的配置错误不同。
- 恢复须同一恢复点成套执行；复核目标与密钥后才进行破坏性步骤，任一步失败不开放业务写入。

不重复讨论已确认的停写许可。若用户要求更小数据损失窗口或零丢失，需要重新收敛备份频率及日志归档/复制边界；不能仅凭两个独立 pg_dump 成功或一次恢复演练就宣称零丢失。

### OSS 最新一套与 Mac 每日副本

- 三处稳态各只保留最新成功一套，更新时允许旧版与候选短暂共存。服务器/Mac 使用单归档校验和原子替换；OSS 候选校验成功后切换恢复点再清旧版。禁止逐个覆盖两库文件或先删旧版。
- 新备份校验失败时保留旧版；清旧失败时报告残留，不将“两套暂留”假称“一套”。只能操作专用前缀，需明确处理未完成分片或版本控制造成的隐藏累积，不擅自关闭既有 Bucket 的保护能力。
- 日常 Mac 下载优先读取服务器已有的完整归档，减少每天从 OSS 公网下载造成的外网流出费用；仍消耗服务器公网流量，套餐额度和超额价格未核实。OSS 作为服务器不可用时的恢复来源，下载时仍核查费用。
- Mac 下载临时归档并校验后整体覆盖 `latest.tar.gz`，日期仅记录在归档清单和输出，不创建长期日期目录；服务器同样只留 latest。成功替换会移除本工具拥有的旧版，但不清用户之前已有的未知文件或日期目录。
- 一天漏下载不等于 OSS 或服务器备份失败，但 Mac 最新可用时间必须如实显示。此任务不创建用户日常提醒或自动后台下载，不实际下载敏感数据。

## 存放位置与费用核对（2026-09-07）

用户在比较后已选三处结合，并接受存储费用示例，但备份实际大小、账号免费资格和账单仍未核验。用户截图显示轻量应用服务器、ESSD 系统盘 40 GiB，不包含磁盘利用率。不要记录截图中的公网 IP 或磁盘标识，也不要根据本机磁盘空间代替服务器空间。

以下为本轮读取的官方资料，不包含用户账号资格或账单核验：

- [OSS 控制台快速入门](https://help.aliyun.com/zh/oss/user-guide/console-quick-start)：开通 OSS 服务免费，但存储、请求、公网下载会产生费用；购买资源包不等于开通服务。OSS 是独立服务，不占用或附送于这块 40 GiB 系统盘。
- [OSS 新用户免费试用](https://help.aliyun.com/zh/oss/free-quota-for-new-users)：实名认证且未开通过 OSS 的用户可按规则领取标准本地冗余存储 20 GB/3 个月、外网流出 2 GB/3 个月、请求 20 万次/3 个月。资格未验证，不能承诺用户免费，也不能把试用当永久免费；先核对领取资格再开通。
- [OSS 计费概述](https://help.aliyun.com/zh/oss/billing-overview)：按实际存储量、时长、请求及适用流量计费，按小时结算。官方文档以标准本地冗余存储 0.12 元/GB/月举例，实际价格以地域和当前产品定价为准。
- [轻量服务器与 OSS 内网互通](https://help.aliyun.com/zh/simple-application-server/use-cases/implement-service-interconnection-over-the-internal-endpoint-of-an-oss-resource)：同地域使用 OSS 内网 Endpoint 时不收取流量费用；不代表存储、请求免费，Mac 公网恢复下载也不属于该内网条件。
- [轻量服务器快照](https://help.aliyun.com/zh/simple-application-server/user-guide/manage-snapshots)：创建快照免费，单台最多 3 个，没有内置快照策略；服务器到期释放时相关快照清除。适合变更前恢复点，不直接等价于独立的每日逻辑备份。

此前给用户的 7 份测算只是比较示例，不是最新的 OSS 留存决策。按目前仅一套的目标，若完整压缩备份为 1 GB，稳态纯存储按示例单价约 0.12 元/月，另有替换期间临时占用、请求、公网下载及其他适用费用。实际备份大小未知，不能据此保证账单。没有真正清理旧对象、分片或历史版本时，也不能按一套估算。

服务器空间需实际 `df -h /` 和归档体积，还要留系统、镜像、数据库、日志及候选空间；同盘副本不提供整盘/实例丢失保护。Mac 和 OSS 保护依赖传输成功。三处都更新之后不存在更早逻辑误删恢复点，这是用户最新策略的明确代价，不保留隐藏历史。

## R2 选定 Compose 原生依赖重启

采用 `nginx.depends_on.api/web` 的 `restart: true`，保留健康依赖；不调整 HTTP 路由、不升级 Nginx 镜像。2026-09-07 通过爬虫读取 [Compose 启动顺序](https://docs.docker.com/compose/how-tos/startup-order/) 和 [services 参考](https://docs.docker.com/reference/compose-file/services/#depends_on)，确认显式 Compose 更新/重启依赖时会重启下游，该字段自 2.17.0 引入，不覆盖容器运行时自动重启。

本机 Compose 版本为 5.5.0，服务器 Compose 版本未验证，Docker Engine 版本不能代替 Compose 版本。工具/手册设支持基线 2.20+；真实换 IP 和下游重启、URI/查询、认证及 SSE 回归属于实施验收，本轮只核对官方语义，不声称测试已通过。

## 预计修改面

- 必需：`deploy/backup.sh`、`deploy/restore.md`、`deploy/README.md`、`deploy/server-setup.md`。
- 新增 `deploy/backup.py`，以标准库集中实现唯一格式/安全替换/每日下载，原 `backup.sh` 保留为稳定薄入口；新增 OSS 初学者指南和每日 Mac 操作说明，不加后台常驻下载器。
- 代理只改 `deploy/compose.yaml` 的依赖重启以及 `deploy/push-images.sh`、维护手册的发版说明；保持 `nginx.conf` 的路由不变。
- 根据配置需要修改：`deploy/.env.production.example`；不改真实 .env。
- 验证：复用 pytest 加入部署脚本失败路径回归，以及隔离 Docker 备份恢复/代理换 IP 的专项验证入口。
- 当前任务规划文档与必要的维护规格；历史归档任务保持原样。

## 验证层级

- 默认 make test 使用模拟 docker/ossutil 命令和临时目录，不接触用户 Docker 资源或云存储。
- 专项集成验证只能创建自有 Docker 项目、网络、数据库和卷，使用合成数据与临时密钥；不暴露 80/3000/8000 等现有服务端口。
- checkpoint 恢复验证使用真实 PostgreSQL saver 和合成状态即可，不需要真实模型调用。
- 不执行服务器重建，不运行本地 reset_local_data，不导入项目库或原始语料。
- 实施完成后按 AGENTS.md 在任务分支和 main 分别执行完整质量门；任务目录 validate 仅证明上下文条目合法，不证明方案批准或代码验收。
