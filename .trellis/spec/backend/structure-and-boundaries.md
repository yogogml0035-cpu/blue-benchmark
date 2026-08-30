# 后端结构与依赖边界

## 当前结构

后端是 Python 3.12+ / FastAPI 的单体服务，按业务 Feature 纵向组织，业务数据由 SQLAlchemy Repository 持久化：

```text
backend/
├── app/
│   ├── main.py
│   ├── features/
│   │   ├── auth/{router,service,repository,schemas}.py
│   │   ├── workspaces/{router,service,repository,schemas}.py
│   │   └── case_builder/{router,service,repository,schemas}.py
│   └── lib/{errors,schemas,settings}.py
├── scripts/export_openapi.py
├── tests/test_api.py
├── openapi.json
└── pyproject.toml
```

`app/main.py` 只组装应用级能力：异常处理器、同源保护、健康检查和三个 Feature Router。业务接口放在所属 Feature，不继续堆进 `main.py`。

## Feature 内部分工

当前三个 Feature 都使用同一分层：

```text
router -> service -> repository
          |             |
          |             -> 数据库 Row 与 Record 映射、读写函数
          -> 业务状态转换、授权编排、DTO 投影
schemas -> HTTP 输入、输出和领域枚举
```

- `router.py` 定义路径、HTTP 状态、认证依赖、请求模型和 `response_model`，然后委托给 Service。参考 `features/workspaces/router.py` 与 `features/case_builder/router.py`。
- `service.py` 负责业务规则、状态转换、授权顺序和 Record 到响应模型的投影。参考 `workspaces/service.py::assert_owner` 与 `case_builder/service.py::confirm`。
- `repository.py` 只拥有本 Feature 的 Record 到数据库 Row 的映射和基本读写；不处理 HTTP，也不返回 FastAPI Response。
- `schemas.py` 用 Pydantic 模型定义外部合同；内部可变状态使用 `@dataclass(slots=True)` Record。参考 `case_builder/schemas.py` 与 `case_builder/repository.py`。

## 跨 Feature 依赖

跨 Feature 必须经过对方 Service 暴露的业务入口，不能绕过边界读取其 Repository。当前正例是 `case_builder/service.py::_authorized_case` 调用 `workspaces/service.py::assert_owner`；Case Builder 不直接读取 `workspaces.repository`。

通用能力只有确实跨 Feature 时才进入 `app/lib/`：

- `lib/errors.py`：统一错误类型与响应转换；
- `lib/schemas.py`：跨 Feature 的健康检查和错误响应模型；
- `lib/settings.py`：环境配置及缓存后的单例设置。

单个 Feature 使用的帮助函数先留在该 Feature 的 `service.py`，不要为了“以后可能复用”提前创建通用模块。

## 命名与新增代码位置

- Python 模块、函数、变量使用 `snake_case`；Pydantic 模型、Record 和枚举使用 `PascalCase`。
- 每个 Router 对象统一命名为 `router`，由 `app/main.py` 添加 `/api` 前缀。
- 新接口先放入所属 Feature 的现有四层；只有出现新的独立业务所有权时才新增 Feature。
- 新的请求/响应字段先进入 `schemas.py`，再由 Service 填充，最后重新生成 OpenAPI 和前端类型。
- 脚本放在 `backend/scripts/`，测试放在 `backend/tests/`；不要在生产模块 import 测试或预演数据。

## 不要这样做

- 不要创建空的 `models.py`、`workflow.py`、Worker 或评测 Feature 来对应未来文档；已有数据库/存储/operations 模块必须由真实迁移、测试和业务入口支撑。
- 不要把业务状态转换写在 Router、Repository 或前端。
- 不要让一个 Feature 直接修改另一个 Feature 的全局字典。
- 不要把内部 `password_hash`、`parsed_text`、`thread_id` 等 Record 字段自动暴露进响应模型。
