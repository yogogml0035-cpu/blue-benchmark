# M0 持久化与上传基础设计

## Boundary

本任务只建立确定性基础：PostgreSQL 业务表、文件存储、上传/解包、OperationJob 单消费者和 StudioProjection。AI 端口以 Fake handler 接入，真实 Deep Agents 留给下一子任务。

## Architecture

- `app/lib/database`：engine/session、事务边界和 schema-ready 检查。
- `app/lib/operations`：OperationJob、AgentRunAttempt、claim/lease/retry/CAS 和单消费者入口。
- `app/lib/storage`：服务端键、本地目录、staging/ready 原语和哈希。
- `features/case_builder/ingestion_*`：UploadBatch、EvidenceFile、FileDisposition、TaskPackage 基础和安全解析。
- Feature Service 拥有业务状态转换；Worker handler 只能调用目标 Feature Service。

## Data and transaction contracts

- 同 target/revision/command 最多一个有效 OperationJob。
- 同一共创 session 最多一个活动 resume 的数据库约束在本任务建表，行为由后续任务使用。
- 文件先进入 staging，数据库事务成功后发布；失败进入可重试清理，不暴露半成品。
- 迟到操作在提交时比较 revision/accepted pointer，不匹配则进入 superseded。

## Development configuration

- PostgreSQL 17；业务 schema 与 Checkpointer schema 使用独立迁移所有权。
- 业务连接使用 `DATABASE_URL`，Checkpoint 使用独立 `CHECKPOINT_DATABASE_URL`，即使开发时指向同一实例也不合并职责。
- 本地存储根使用 `STORAGE_ROOT`，默认只允许仓库内 Git-ignored `storage/`；配置文件只放占位符。
- `POSTGRES_*` 本地容器值使用开发占位，不提交真实凭证。

## Compatibility and rollback

- 当前没有真实生产数据，可一次升级 API，但必须同步 Pydantic、OpenAPI、生成类型和测试。
- 先保持 auth/workspaces 行为；其回归失败时停止后续迁移。
- 单消费者与数据库租约已满足 M0，不引入 Redis/Celery；真实吞吐证据出现前不扩展。

## File ownership

- 独占新增：`backend/app/lib/database/**`、`backend/app/lib/storage/**`、`backend/app/lib/operations/**`、`backend/migrations/**`、ingestion 专属模块和测试。
- 首写共享：`backend/pyproject.toml`、`backend/uv.lock`、`.env.example`、`backend/app/lib/settings.py`、现有 Feature Repository/Service/Schema/Router、`backend/app/main.py`、`backend/openapi.json`。
- 父任务保留 `docs/**` 和 `.interface-design/system.md` 的架构合同所有权。
