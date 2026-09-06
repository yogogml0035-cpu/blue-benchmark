# 后端结构与依赖边界

## 当前结构

后端是 Python 3.12+ / FastAPI 的单体服务，按业务 Feature 纵向组织，业务数据由 SQLAlchemy Repository 持久化。本文件只描述后端；前端（`frontend/`，Next.js）规范见 `../frontend/`：

```text
backend/
├── app/
│   ├── main.py
│   ├── features/
│   │   ├── auth/{router,service,repository,schemas}.py
│   │   ├── scenes/{router,service,repository,schemas}.py
│   │   └── question_library/{router,external_router,service,repository,schemas,rubric_generation,rubric_rules}.py
│   └── lib/{errors,schemas,settings,ai_runtime/{model,adapters,deep_runtime},operations/,database/}
├── scripts/{export_openapi,verify_openapi,check_schema,migrate,smoke_ai_provider,accept_real_ai_rubric,accept_skill_push,m0_samples,probe_deep_runtime,reset_local_data,admin_cli}.py
├── migrations/versions/
├── tests/
├── openapi.json
└── pyproject.toml
```

`app/main.py` 只组装应用级能力：异常处理器、健康检查和 auth、scenes、question_library（管理路由 + 外部收题）Router。业务接口放在所属 Feature，不继续堆进 `main.py`。

## Feature 内部分工

当前业务 Feature 都使用同一分层：

```text
router -> service -> repository
          |             |
          |             -> 数据库 Row 与 Record 映射、读写函数
          -> 业务状态转换、授权编排、DTO 投影
schemas -> HTTP 输入、输出和领域枚举
```

- `router.py` 定义路径、HTTP 状态、认证依赖、请求模型和 `response_model`，然后委托给 Service。参考 `features/scenes/router.py` 与 `features/question_library/router.py`。
- `service.py` 负责业务规则、状态转换、授权顺序和 Record 到响应模型的投影。参考 `question_library/service.py::publish` 与 `scenes/service.py::create_or_replace_credential`。
- `repository.py` 只拥有本 Feature 的 Record 到数据库 Row 的映射和基本读写；不处理 HTTP，也不返回 FastAPI Response。
- `schemas.py` 用 Pydantic 模型定义外部合同；内部状态使用 `@dataclass(frozen=True)` Record。参考 `question_library/schemas.py` 与 `question_library/repository.py`。
- `question_library/rubric_generation.py` 负责评分维度生成的 Worker handler、原子提交（CAS + fencing）与失败投影；`rubric_rules.py` 是纯函数规则（可执行性、隐私兜底、逐项及格），被 API 校验与 Worker 共用。
- `lib/ai_runtime` 只拥有模型构造（`model.py`）与评分维度生成 adapter（`adapters.py`）；它不直接写业务表、不产生 HTTP DTO。
- `lib/operations/__init__.py` 只重导出 Repository/Attempt 能力；`OperationWorker` 和 `fake_worker` 必须惰性导出，避免 `python -m app.lib.operations.worker` 在模块执行前被包级导入触发 runpy warning 或循环加载。

## 跨 Feature 依赖

跨 Feature 必须经过对方 Service 暴露的业务入口，不能绕过边界读取其 Repository。`question_library/service.py` 通过 `scenes.service.ScenePrincipal` 获得场景归属，不直接读取 `scenes.repository`。

通用能力只有确实跨 Feature 时才进入 `app/lib/`：

- `lib/errors.py`：统一错误类型与响应转换；
- `lib/schemas.py`：跨 Feature 的健康检查和错误响应模型；
- `lib/settings.py`：环境配置及缓存后的单例设置。

单个 Feature 使用的帮助函数先留在该 Feature 的 `service.py`，不要为了“以后可能复用”提前创建通用模块。

## 命名与新增代码位置

- Python 模块、函数、变量使用 `snake_case`；Pydantic 模型、Record 和枚举使用 `PascalCase`。
- 每个 Router 对象统一命名为 `router`，由 `app/main.py` 添加 `/api` 前缀。
- 新接口先放入所属 Feature 的现有四层；只有出现新的独立业务所有权时才新增 Feature。
- 新的请求/响应字段先进入 `schemas.py`，再由 Service 填充，最后重新生成 `backend/openapi.json` 并运行漂移检查。
- 脚本放在 `backend/scripts/`，测试放在 `backend/tests/`；不要在生产模块 import 测试或预演数据。
- 真实会话语料（`.local-samples/`，仓库外只读）只能经 `scripts/m0_samples.py` 的 hash 门禁提取；重建产物写入 gitignored 的 `backend/storage/acceptance/`，真实正文、完整模型输出与凭证一律不进 Git，提交物只含代码、非敏感取样元数据（路径/hash/uuid/行号/字符数）与合成负例。

## 不要这样做

- 不要创建空的 `models.py`、`workflow.py`、Worker 或评测 Feature 来对应未来文档；已有数据库/operations 模块必须由真实迁移、测试和业务入口支撑。
- 不要把业务状态转换写在 Router 或 Repository。
- 不要让一个 Feature 直接修改另一个 Feature 的全局字典。
- 不要把内部 `password_hash`、`token_hash`、`client_case_id` 明文凭证等字段自动暴露进响应模型。
- 不要让评分维度生成 adapter 直接确认或发布题目；模型输出必须先经过完整评分项合同、引用存在性与可执行性/隐私校验，再由 `rubric_generation` 做 revision/ownership/删除冻结 CAS 提交。adapter 不直接操作业务表；公开事件经服务注入的持久化 sink 先落库再外送。
- 场景凭证明文按 1:1 模型持久化在 `token_plaintext`（撤销/替换即清空），但绝不进入日志与状态/列表响应（只给掩码预览）；携带明文的端点（创建/替换、`GET /scenes/{id}/credential`）必须带 `no-store` 头。
