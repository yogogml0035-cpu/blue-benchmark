# 代码复用与所有权

本项目的复用目标不是抽象最多，而是让一个合同只有一个清晰所有者。新增 Helper、Service 或状态映射前，先用 `rg` 查找相同职责。

## 已存在的所有者

| 职责 | 唯一或优先入口 |
|---|---|
| 后端业务错误与错误响应 | `backend/app/lib/errors.py`、`backend/app/lib/schemas.py` |
| 环境与设置 | `backend/app/lib/settings.py` |
| 管理员会话解析 | `backend/app/features/auth/service.py::require_current_user` |
| 场景凭证解析与最小权限 | `backend/app/features/scenes/service.py::require_scene_principal` |
| 场景/凭证生命周期 | `backend/app/features/scenes/service.py` |
| 题目六类材料、状态机与发布 | `backend/app/features/question_library/service.py` |
| 批量收题幂等与原子性 | `backend/app/features/question_library/service.py::batch_upload` |
| 评分维度生成与 CAS 提交 | `backend/app/features/question_library/rubric_generation.py` |
| 可执行性/隐私/逐项及格规则 | `backend/app/features/question_library/rubric_rules.py` |
| 业务数据库 Record 与读写 | 对应 Feature 的 `repository.py` |
| 任务排队、租约与重试 | `backend/app/lib/operations/` |

## 搜索顺序

```bash
rg -n "要新增的字段名|状态值|错误码" backend .trellis/spec
rg -n "相似函数名|相似错误文案" backend/app
```

先判断现有所有者能否直接使用或小幅扩展。只有同一稳定语义跨 Feature 重复时才提取到 `app/lib/`；单个 Feature 的一次性逻辑留在 Feature 内。

## 常见重复错误

- 手写一份 DTO，绕过 `schemas.py` 与 OpenAPI；
- 多处各自维护题目状态文案和允许动作，而不是复用 `QuestionStatus` / `next_action`；
- 一个 Feature 直接读另一个 Feature 的 Repository，复制归属判断；
- 复制一份隐私兜底或可执行性校验，而不是复用 `rubric_rules`；
- 用未来数据库/流程设计提前创建空目录和抽象层。

## 什么时候不要抽象

当前后端保持小而明确。只出现一次、只属于一个 Feature、提取后反而隐藏业务语义的代码不需要通用化；不提前建设全局状态库或通用流程引擎。

## 修改后检查

- [ ] 相同状态、字段、错误码的所有引用都已找到。
- [ ] 新逻辑扩展了正确的所有者，没有创建第二套合同。
- [ ] `backend/openapi.json` 仍由生成命令更新，没有手工补丁。
- [ ] 跨 Feature 共用确有两个以上真实使用方，而非未来猜测。
- [ ] 删除或改名后，`rg` 不再命中过时名称。
