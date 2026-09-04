# 服务器部署与发布方案

## Goal

为当前 Skill Eval Platform 形成一套适合初学者理解和维护、可按常规主流方式部署到服务器并供目标用户使用的正式方案。方案必须以当前源码的真实运行边界为基础，区分 Docker、服务器部署和 CI/CD 的职责，并在需求对齐后给出可实施、可验证、可备份和可回滚的项目修改计划。

## Background

- 用户是服务器部署初学者，听说过 Docker，但还不清楚 Docker 的作用、其他部署方式以及 CI/CD 是否等同于部署。
- 用户希望通过逐轮访谈挖掘真实目标、假设、局限和遗漏；每轮只处理一个最高价值问题，直到对需求和目标达到约 95% 的理解置信度。
- 用户已同意创建 Trellis 规划任务。本阶段只写规划材料，不修改业务代码、不运行 `task.py start`、不实际购买或操作服务器。
- 2026-09-04 本轮重新核对了仓库现状：旧 PRD 中“前端已移除”的过时提醒本身已过时——旧前端确实被删除（`b70f83d`），但随后重建了全新的 Next.js 16 前端（`c90ec06`）并持续迭代至今；Checkpointer 数据库已随共创流程简化而删除；生产 AI 接线已完成（`ai_runtime_mode` 默认 `production`，经 `service.py → operations/worker.py → ai_runtime/adapters.py` 走 langchain）。

## Confirmed Repository Facts（2026-09-04 重新核对）

- 前端是重建后的 Next.js 16.3.4 应用；浏览器只访问同源 `/api/*`，由 Next.js Rewrite 转发到后端（服务端环境变量 `BACKEND_URL`），HttpOnly Session Cookie 保持第一方。生产形态需要 `next build` 后 `next start`；当前 `next.config.mjs` 未配置 `output: 'standalone'`。
- 后端是 FastAPI（`app.main:app`），生产需使用不带 `--reload` 的 uvicorn 启动；启动时默认执行 Alembic head schema 检查（`DATABASE_SCHEMA_CHECK_ON_STARTUP`）。
- 后台任务由独立的单消费者 Worker 处理（`app.lib.operations.worker`，进程锁保证每个业务库只有一个 Worker）；只启动网页和 API 会导致异步任务一直等待。
- 账号模型已收敛为单管理员：`/register` 只允许第一个注册者成为唯一管理员，之后注册返回 `ADMIN_EXISTS`（backend/app/features/auth/service.py:70-83）。旧 PRD“任何人自由注册”的前提不再成立。
- 业务数据使用 SQLAlchemy/Alembic 管理的 PostgreSQL（`DATABASE_URL`）；本地 SQLite 仅供开发和 Fake 模式。Checkpointer 数据库已删除，只剩一个业务库。
- 上传、证据、版本包等文件保存在服务端本地文件系统（`backend/storage/` 与仓库根 `storage/`：uploads、evidence、versions、staging、submissions），部署必须提供持久存储、备份和恢复边界。
- 生产真实 AI 已接线：Worker 默认 `AI_RUNTIME_MODE=production`，支持 OpenAI 官方/任意 OpenAI Chat Completions 兼容端点或 Anthropic（`AI_PROVIDER`/`AI_MODEL`/`AI_API_KEY`/`AI_BASE_URL`），并提供 `scripts/smoke_ai_provider.py` 冒烟脚本。设置环境变量即可启用真实 AI，不再需要额外接线代码。
- `SESSION_COOKIE_SECURE` 默认 `true`；纯 HTTP 部署必须显式设为 `false`，否则 Cookie 无法写入、登录不可用。
- 当前仓库没有 Dockerfile、Compose、反向代理或 CI/CD workflow，服务器部署能力尚未实现。
- 已有一台运行中的阿里云 Linux 服务器，区域为华北 2（北京），镜像预装 Docker 26.1.3；用户本轮描述配置为 2 vCPU、2 GiB 内存和 40 GiB ESSD，并具有公网地址（是否已升级到 4 GiB 待确认）。规划文档不记录具体公网 IP 或实例 ID。

## Requirements

- 用初学者可理解的方式解释服务器、进程、Docker、Docker Compose、反向代理、数据库、持久化和 CI/CD 之间的关系。
- 首版通过公网对外开放，使用固定公网 IP，不配置域名。
- 保持现有单管理员账号模型，不因部署方案重做账号体系。
- 基于目标用户、暴露范围、预算、数据敏感度、维护能力和可用性要求，对比至少以下路线：服务器原生进程、单机 Docker Compose、托管 PaaS/容器平台。
- 给出明确推荐，不把“大家都用 Docker”当作选择依据；每个新增组件都必须对应当前项目的真实运行需求。
- 最终技术方案必须覆盖前端、API、Worker、业务数据库、文件存储、反向代理与端口暴露、密钥管理、迁移、健康检查、日志、备份、恢复和回滚。
- 生产环境必须执行真实 AI，不得用 Fake adapter 的确定性结果冒充真实模型验收。
- 数据恢复目标仍为最多丢失最近 24 小时的数据，发生服务器故障后允许停机数小时完成恢复。
- 业务数据库与上传文件至少每日自动备份一次；可靠备份必须存放在故障域之外，不能只复制到同一台服务器，并需要有可重复的恢复验证步骤。
- 明确 CI 与 CD 的边界，决定首版采用手动部署、半自动发布还是自动发布，并提供与用户维护能力匹配的故障处理路径。
- 形成项目级 `design.md` 和 `implement.md`，列出需要修改或新增的部署文件、实施顺序、验证命令、风险点及回滚点。
- 所有部署成功结论都必须由真实运行路径验证，不能用镜像构建成功、端口监听或 HTTP 200 冒充完整业务验收。

## Acceptance Criteria

- [x] 目标使用者、公网暴露范围与访问控制决策已经明确（使用者仅用户本人；完全开放公网；不用白名单）。
- [x] “生产环境”定位与传输加密（HTTP/HTTPS）决策已经对齐（接受过渡期 HTTP 明文，域名到位后加 HTTPS，已列为已知风险）。
- [x] 服务器内存基线（2 GiB 或已升级 4 GiB）已经确认（维持 2 GiB，卡住再升级）。
- [x] AI Provider、密钥来源与生产边界已经明确（沿用现有配置，部署提供等价环境变量）。
- [x] 已对比原生部署、Docker Compose 和托管平台，并说明推荐结论及不选其他方案的原因（见 design.md）。
- [x] 推荐方案覆盖前端、API、Worker、数据库、持久文件、反向代理和密钥管理。
- [x] CI/CD 方案与首版发布频率及维护能力匹配，并保留手动回滚路径（首版手动，见 implement.md）。
- [x] `design.md` 包含架构、数据流、部署拓扑、安全边界、备份恢复和发布回滚设计。
- [x] `implement.md` 包含有序修改清单、质量门、服务器预检、首次部署、升级发布和验收步骤。
- [x] 最终规划摘要经用户单独确认后，才允许进入实施阶段（用户已于 2026-09-04 确认“我接受”）。

## Out of Scope During Planning

- 修改业务代码或部署配置。
- 运行 `task.py start`。
- 购买云服务器、注册域名、开通云服务或实际推送生产环境。

## Open Questions

- 裸 IP + HTTPS 可行性研究（阿里云 ALB IP 证书 vs 服务器内短证书自动续期）作为后续域名阶段的参考项，不阻塞当前方案。
- 服务器内存当前是 2 GiB 还是已升级到 4 GiB。
- 真实 AI 使用 OpenAI 官方、OpenAI 兼容端点还是 Anthropic？密钥来自哪里？
- 预算和发布维护偏好仍待逐轮确认。

## Resolved Decisions

- 预期早期用户量很小，当前不以高并发扩容为首要目标。
- 账号模型保持现状：单管理员，首个注册者成为唯一管理员。
- 可接受最多丢失最近 24 小时的数据，并允许故障后停机数小时恢复；不要求首版高可用或近零数据损失。
- 部署目标优先使用现有阿里云 Linux 服务器，而不是重新选择托管平台。
- 首版不配置域名，只使用阿里云实例的固定公网 IP 访问；域名、DNS 和 ICP 备案延后处理。
- 服务器演示必须使用真实 AI；Fake 模式只保留给自动化测试或显式的本地开发，不作为服务器业务验收路径。
- 用户本轮（2026-09-04）明确将此次部署定位为生产环境，而非临时演示；与“纯 HTTP”之间的冲突是当前待解决的核心决策。
- 首版完全开放公网访问，不设 IP 白名单：使用者只有用户本人，且要求随时随地（含移动网络）访问；白名单与移动访问的出口 IP 不稳定直接冲突。
- 域名后续会配置；首版不等待域名，先以固定公网 IP 上线。
- 真实 AI 沿用现有 `.env` 中的 Provider/模型/密钥配置，部署只负责在服务器上提供等价环境变量，不为部署更换 Provider。
- 代码仓库现状：本地开发机（Apple Silicon，Docker Desktop + buildx 支持 amd64/arm64）+ GitHub 远端（`github.com/yogogml0035-cpu/skill-eval-platform`）；服务器为阿里云华北2（北京），从服务器访问 GitHub 不可靠，发布链路必须绕开服务器直连 GitHub。
- 发布链路定案为路线 A：本地构建镜像 → 推送阿里云容器镜像服务（ACR）→ 服务器拉取运行；发版由用户本地电脑发起，服务器上不放源代码。用户不了解 ACR，最终交付物必须包含面向初学者的 ACR 开通、登录、推送、拉取操作说明。

## Risk Notes

- 公网完全开放 + 单管理员登录页会面临扫描和暴力撞库；账号模型杜绝了陌生注册，但部署设计必须保留登录限流、监控和后续治理的扩展点。
- 数据库记录与本地文件存在一致性关系，备份和恢复不能只覆盖数据库或只覆盖文件；每日备份满足当前恢复目标，但仍需验证恢复后的业务路径和版本包完整性。
- 2 GiB 内存需要同时容纳容器运行时、Next.js、FastAPI、Worker、PostgreSQL 和反向代理，生产余量偏紧；若保持该配置，应避免在服务器内构建镜像，并需要限制并发、设置资源边界和监控内存压力。
- 裸 IP 的明文 HTTP 会暴露管理员密码、Session Cookie 和上传内容。Let’s Encrypt 已在 2026-01-15 将 IPv4/IPv6 地址证书设为正式可用，但这类证书有效期为 160 小时，部署必须使用支持 `shortlived` ACME profile 的客户端并验证自动续期；不能依赖手工换证。
- 真实 AI 调用会产生 API 费用；公网暴露下需防止密钥配置泄漏导致的费用失控。

## Notes

- 本任务当前处于需求探索阶段；本次对话中的任务创建许可不是实施许可。
