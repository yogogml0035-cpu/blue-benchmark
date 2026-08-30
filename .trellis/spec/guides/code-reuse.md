# 代码复用与所有权

本项目的复用目标不是抽象最多，而是让一个合同只有一个清晰所有者。新增 Helper、Hook、组件或状态映射前，先用 `rg` 查找相同职责。

## 已存在的所有者

| 职责 | 唯一或优先入口 |
|---|---|
| 通用 HTTP、Cookie、204、错误解析 | `frontend/src/lib/api/client.ts` |
| 页面级 401/403/404/409 分流 | `frontend/src/lib/api/pageFault.ts` |
| User / Workspace / M0 资料、题、草稿、版本 DTO | `frontend/src/lib/api/generated.ts` |
| 认证会话读取 | `frontend/src/features/auth/hooks/useSession.ts` |
| 兼容 Case 状态名称、语义色、下一步、进度 | `frontend/src/features/case-builder/lib/caseState.ts` |
| Button、Field、Note、StatePanel、Skeleton | `frontend/src/components/ui/` |
| 后端业务错误与错误响应 | `backend/app/lib/errors.py`、`backend/app/lib/schemas.py` |
| Workspace 归属校验 | `backend/app/features/workspaces/service.py::assert_owner` |
| Case 业务状态转换 | `backend/app/features/case_builder/service.py` |
| 业务数据库 Record 与读写 | 对应 Feature 的 `repository.py` |

## 搜索顺序

```bash
rg -n "要新增的字段名|状态值|错误码" backend frontend docs .trellis/spec
rg -n "相似函数名|相似用户文案" backend/app frontend/src
```

先判断现有所有者能否直接使用或小幅扩展。只有同一稳定语义跨 Feature 重复时才提取到 `app/lib/`、`src/lib/` 或 `src/components/ui/`；单个 Feature 的一次性逻辑留在 Feature 内。

## 常见重复错误

- 组件直接 `fetch`，复制 `apiFetch` 的 Cookie、JSON 和错误处理；
- 手写一份 DTO，绕过 OpenAPI 生成类型；
- 多个组件各自维护 Case 状态文案和允许动作；
- Case Builder 直接读 Workspace Repository，复制归属判断；
- 每个表单各自造一套按钮 busy 行为、错误面板或字段结构；
- 用未来数据库/Graph 设计提前创建空目录和抽象层。

## 什么时候不要抽象

当前 M0 工作台仍保持小而明确。只出现一次、只属于一个 Feature、提取后反而隐藏业务语义的代码不需要通用化；场景工作台的分组编辑和共创显示留在对应 Feature，不提前建设全局状态库或通用流程引擎。

## 修改后检查

- [ ] 相同状态、字段、错误码的所有引用都已找到。
- [ ] 新逻辑扩展了正确的所有者，没有创建第二套合同。
- [ ] 生成文件仍由生成命令更新，没有手工补丁。
- [ ] 跨 Feature 共用确有两个以上真实使用方，而非未来猜测。
- [ ] 删除或改名后，`rg` 不再命中过时名称。
