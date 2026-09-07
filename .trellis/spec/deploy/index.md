# 部署层开发规范

适用于 `deploy/` 的单机 Docker Compose 生产部署：备份/恢复工具、Compose 服务图、Nginx 代理、发布脚本与运维教程。部署层脚本以 Python 标准库和 Bash 实现，不引入第三方备份框架或云 SDK；对应回归测试在 `backend/tests/test_deploy_backup.py`（默认无外部副作用）与 `backend/tests/test_deploy_runtime.py`（默认层 + `DEPLOY_INTEGRATION_REQUIRED=1` 集成层）。

## 规范索引

| 规范 | 何时读取 |
|---|---|
| [备份格式与运行时刷新合同](./backup-and-runtime.md) | 修改 deploy/backup.py、backup.sh、compose.yaml、nginx 配置、发布/恢复流程或相关文档 |

## 开发前检查

- [ ] 已确认改动属于部署/测试边界，不触及 `backend/app`、业务迁移、OpenAPI、前端或依赖锁。
- [ ] 涉及备份/恢复时，已读取 backup-and-runtime.md 的归档格式、留存与失败语义合同。
- [ ] 涉及 Compose/Nginx 时，已确认 `nginx.depends_on.api/web` 保持 `condition: service_healthy` + `restart: true`，发版走完整服务图。
- [ ] 文档改动同步 `deploy/README.md`、`server-setup.md`、`restore.md`、`oss-guide.md` 与根 README 导航，口径一致。

## 质量检查

- [ ] `bash -n deploy/backup.sh deploy/push-images.sh` 与 `docker compose config` 校验通过。
- [ ] `uv run --project backend pytest -q backend/tests/test_deploy_backup.py backend/tests/test_deploy_runtime.py` 通过；涉及真实 Docker 行为（备份恢复、代理换 IP）时另跑 `DEPLOY_INTEGRATION_REQUIRED=1`。
- [ ] 定向检索确认没有恢复旧语义（LOCAL_KEEP_DAYS、日期目录、7/30 天保留、松散两件格式）。
- [ ] 任何输出、日志、测试断言不出现密码 DSN、AES 密钥、Cookie 或真实云资源地址。
