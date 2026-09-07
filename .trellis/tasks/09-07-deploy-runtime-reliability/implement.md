# 实施与验收计划

## 进入条件

- [x] 用户确认创建任务、服务器全新建库、停写导出、三处结合及全部只留最新一套。
- [x] 独立 worktree 已创建并校验；PRD 收敛，无剩余产品问题。
- [ ] 用户在本轮最终规划摘要之后批准实施。该项未完成前不运行 `task.py start` 或修改产品代码。
- [ ] 重新核对 main/worktree 状态和 Git 引用；复制主工作区私有 `.env` 到本 worktree 后再跑测试，显式隔离测试数据库，不输出凭证。
- [ ] 在任务 worktree 运行 `task.py start`，确认 branch 为 `codex/deploy-runtime-reliability`、base_branch 为 `main`。

## 顺序

### 1. 固定格式和最小运行依赖

- 实现 `deploy/backup.py` 的标准库归档/验证及配置预检，保留 `backup.sh` 作为薄入口。
- 增加无真实密钥的 `OSS_BUCKET`、`OSS_PREFIX`、`OSS_ENDPOINT` 模板说明。
- 先验证新归档缺项、损坏、错误密钥、路径越界、旧格式和未知覆盖目标均拒绝；全程使用合成数据。
- 复用当前项目 Python/pytest，不新增依赖包；记录服务器/Mac Python 和 Compose/ossutil 前置版本。

### 2. 一致性导出与服务器最新替换

- 按设计预检容器/两库/卷/磁盘，设置互斥与维护恢复状态。
- 停止确定的写入服务，导出两库与文件后立即恢复；压缩和云传输不延长停写。
- 候选校验后整体原子替换最新归档；清理只涉及本工具的临时文件，不按日期保留旧版。
- 故障注入：停写部分失败、第二库导出失败、文件导出失败、磁盘不足、普通中断、恢复服务失败、并发备份拒绝、残留维护状态重入。

### 3. OSS 最小留存与 Mac 每日下载

- 实现候选上传/回读校验、latest 指针切换及精确旧对象清理；核对 ossutil 实际命令/退出状态和分片处理，不解析彩色展示文本作为合同。
- 用模拟 OSS 命令固定成功、超时、响应丢失、校验失败、清理失败、指针变更与恢复下载竞态；模拟不是云端验收。
- 实现用户主动 `download` 入口：SSH 流式下载、校验、原子覆盖本机 latest；不创建后台调度或日期历史目录。
- 连续两轮成功后断言各处最新只有一套；失败保留上次成功，输出 ID/生成时间/分阶段结果。
- 数据传输来源默认服务器，教程给 OSS 故障恢复路径；未请求真实数据下载，不连接用户服务器。

### 4. Nginx 更新刷新

- `nginx.depends_on` 的 API/Web 两项增加 `restart: true`，保持健康依赖，不改路由。
- 同步发版/回滚完整 Compose 命令和最低版本检查，避免 `--no-deps` 等绕过约定流程。
- 隔离网络测试中强制 API/Web 获得不同 IP，执行支持的 Compose 更新；核对 Nginx 重启及请求指向新标记实例。
- 回归 Cookie/转发头、URI/查询、登录限流、健康路径和 SSE 的分批抵达；不要只检查一次 HTTP 200。

### 5. 教程和旧语义删除

- 更新设计文件清单内的维护文档；OSS 指南包括试用、私有 Bucket、内网、最小权限、版本/分片检查、费用和使用边界。
- 每日 Mac 教程说明固定入口覆盖最新、失败不覆盖、数据生成时间及原密钥保存位置要求。
- 恢复指引覆盖两库/文件/密钥/版本和失败不开放写入，修复原 STAMP 容器变量问题；不是无人值守清库。
- 删除 `LOCAL_KEEP_DAYS`、日期目录留存、按 7/30 天过期删除和旧松散备份成功路径；不改归档任务，不清理任何真实旧备份。
- 如发现新的长期约束需要规格补充，按 Trellis 规格流程先读相应技能，限定在部署/测试边界；不修改 Trellis 框架。

## 验证命令

以下专项文件在实施中新增，当前尚不存在；必须明确显示通过/失败，不能将跳过当通过。

```bash
git diff --check
bash -n deploy/backup.sh deploy/push-images.sh
REGISTRY=example.invalid/review TAG=review POSTGRES_PASSWORD=not-a-secret docker compose --env-file /dev/null -f deploy/compose.yaml config --no-env-resolution --quiet
uv run --project backend pytest -q backend/tests/test_deploy_backup.py
DEPLOY_INTEGRATION_REQUIRED=1 uv run --project backend pytest -q backend/tests/test_deploy_runtime.py
make test
make build
```

- 默认 `make test` 中部署回归只使用 fake docker/ossutil/ssh、临时文件和合成数据；集成测试未开启时显式跳过。
- `DEPLOY_INTEGRATION_REQUIRED=1` 必须自建唯一项目名、网络、卷和库，工具/Docker 缺失直接失败，不能通过自动跳过完成验收。
- 真实 Docker/PostgreSQL 集成验证新归档的导出与恢复、原密钥解密、线程状态和文件摘要；不调用真实 AI，使用合成检查点/受控本地模型。
- Nginx 集成采用现有 Nginx 1.27 和隔离测试上游服务，只绑定本地随机端口；不占用或停止现有 80/3000/8000 监听。
- 集成只删除本次创建且身份核验的资源；失败日志不含密钥、DSN 密码、Cookie、真实材料或原始模型内容。
- ossutil 与阿里云的真实鉴权/计费/内网连接是用户部署阶段检查，本次不登录或调用真实 OSS；完成报告必须保留该未验证边界。

## 定向检索

```bash
rg -n 'LOCAL_KEEP_DAYS|find .*backups|保留.*7|保留.*30|按日期保存|按恢复点日期存放|db-\$STAMP|files-\$STAMP' deploy README.md backend/tests/test_deploy_backup.py
rg -n 'pg_dump|checkpoint|latest|os.replace|restart: true|depends_on' deploy
```

逐项确认剩余命中是新合同必要逻辑或禁止性说明，不是可执行的旧保留/兼容路径。已有归档任务的历史命中不改写。

## 集成与收尾

1. 任务 worktree 通过全部验收、`trellis-check` 后，复查 scope，仅提交本任务文件。
2. 如果 main 前进，先在本分支集成最新 main 并重跑完整检查，不覆盖他人改动。
3. 按 AGENTS.md 使用 main 的专用合并检出串行快进合并；若 main 已被主工作区检出，不 force 重复检出或切换用户工作区，先解决检出占用条件。
4. main 包含全部提交后再次执行同一完整门禁，特别是部署专项测试，不用分支结果替代。
5. 质量门通过后按 Trellis 收尾记录/归档；本任务不推送远端、不实际部署。
6. 只在 main 复验通过、分支无独有提交、worktree 干净后删除本任务子 worktree 和分支；保留共享父目录。

## 失败与回滚

- 修改前的源码由 Git 保留，不在运行代码中保留旧 backup 模式。
- 验收失败保留分支和证据，不能归档或强行合并。
- 新版替换前失败保留旧归档，替换后的旧归档按用户策略不再可恢复；不得声称存在 7/30 天历史回滚能力。
- 当前任务只做仓库和隔离验证，用户的实际数据库重建、最新备份替换及恢复操作需要之后按教程对精确目标授权。
