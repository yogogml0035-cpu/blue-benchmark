# Followups:对抗审查发现、超出本任务边界的既有缺陷

以下问题在 main 上已存在(经 git 追溯确认非本次改名引入),与命名无关,按 PRD Out of Scope("与命名无关的功能改动")不在本任务内修复。建议合并后另立一个 deploy 可靠性小任务统一处理:

1. [P1] deploy/restore.md:199 恢复后抽查 SQL 引用不存在的表 `questions`,应为 `eval_questions`(models.py:101)。首次真实恢复会把成功恢复误判为失败并停留在停写状态。
2. [P1] deploy/restore.md:177-179 第 7 步 `docker volume rm -f blue-benchmark_appdata` 会被第 3 步 stop(未 rm)的 exited 容器阻挡;需补 `docker compose rm -f api worker` 步骤,并显式警告禁止 `docker compose down -v`(会连 pgdata 一起清掉,导致第 8.1 步 alembic check 在空库上产生误导性报错)。
3. [P2] deploy/backup.py:459-461 `_discover_schema_version` 探测 `compose_dir.parent/"backend"/"alembic"/"versions"`,实际迁移目录是 `backend/migrations/versions`,且服务器 /opt 布局根本没有 repo 检出 → manifest `business_schema_version` 恒 None,restore.md:79 要求核对的"业务 schema 版本"永远显示"未知"。需要设计决策(从库内 alembic_version 读取 vs 删除文档核对项)。
4. [P2] deploy/README.md:54 与 push-images.sh:61 "等待全部 healthy"不可达:compose 中 worker/nginx 无 healthcheck,只会 Up;应统一为 server-setup.md:158 的口径(api/postgres/web healthy,worker/nginx Up)。
5. [P3] deploy/acr-guide.md:54-55 "验证:推送一个测试标签"只 tag 不 push 且 `2>/dev/null || true` 吞错,hello-world 镜像与 hello 仓库均不在要求创建的清单内;删除或改为真实 push+清理。
6. [P3] deploy/acr-guide.md:79-80 "REGISTRY 留空会退回 Docker Hub"只对 nginx/postgres(compose 有默认值)成立;web/api 是裸 `${REGISTRY}/...`,留空会得到非法镜像引用直接失败,必须配置。
7. [P3] deploy/compose.yaml:20 注释"Compose >= 2.17"与 README.md:61、server-setup.md:35、restore.md:51 的"2.20+"基线不一致;统一口径(2.17 为 depends_on.restart 硬下限,2.20 为项目基线)。
8. [P3] backend/alembic.ini:4 `sqlite:///./storage/blue-benchmark.db` 是死配置:migrations/env.py:16-18 恒以 ALEMBIC_DATABASE_URL/settings.database_url 覆盖;建议改注释或与 settings 默认对齐,消除"相对 cwd"的误导。

9. [P2·命名遗留决策] `sep_` 凭证前缀(= 旧名 Skill Eval Platform 首字母缩写)是活着的跨层运行时合同:发行于 backend/app/features/scenes/service.py:200,机密检测正则 backend/app/features/question_library/rubric_rules.py:86,消费侧覆盖 skills/ai-eval-push(scripts/references/tests)、frontend/e2e 03/04、real-acceptance.mjs、logic.test.ts、backend/tests/test_scenes.py 等。本任务**有意保留**并经对抗审查第 2 轮记录决策,理由:(a) 不在已批准的 design §1 映射表内,属跨层安全合同,按 AGENTS.md 不得借清理之名超范围改动;(b) 待上传的 m0 题目批次与老师持有的场景凭证已按 `sep_` 前缀校验/绑定,立即改前缀会使这些在途资产失效;(c) AC1 口径(skill.?eval 检索)不覆盖该缩写,不构成验收违例。后续如决定改名(如 `bb_`),需单独立项:同步改发行点、检测正则、skill 副本与部署副本、e2e/单测断言,并处理在途凭证的换发。
