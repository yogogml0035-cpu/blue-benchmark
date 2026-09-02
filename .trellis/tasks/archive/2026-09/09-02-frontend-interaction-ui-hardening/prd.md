# 前端工作台交互与 UI 真实验收修复

## Goal

修复开发预演误发真实会话请求、恢复工作台主流程焦点、统一主动作视觉 token，并补齐真实浏览器可验证的交互边界。

## Requirements

- 开发预演是本地 fixture 边界：当 URL 带有已识别的 `preview` 状态时，不发起会话、工作台、题目或评分的真实请求，不因后端未启动产生 500/console error；真实 URL 仍必须先读取并校验 Session。
- 场景工作台的“当前”页先呈现当前业务下一步；连接本地 Agent 是低频的场景设置，不能抢在主流程前成为第一焦点。连接卡只在已得到工作台快照后出现，加载态和错误态不额外请求或渲染它。
- 主动作遵循已批准的设计系统：主按钮使用中性 `--action`，`--accent` 只承担链接、焦点、当前导航和进度含义；不在组件里新增第二套颜色或视觉 token。
- 面向业务老师的规则审阅不显示内部评分项 ID；内部 ID 只保留在 DOM 标识和 API 请求中，机器详情仍按既有技术详情边界收起。
- 删除当前前端没有任何活动路由或组件引用的旧 Case Builder 展示/服务代码，消除旧案例编辑器、旧状态映射和旧前端 DTO 入口；不为这些已删除入口添加兼容分支。
- 本地真实验收脚本必须直连 loopback API，不受开发机系统代理影响；该修复不能把真实 Provider 替换成 Fake。
- 保持现有后端业务合同、不可变历史包和真实 AI Worker 链路不变；本子任务只修复前端边界，不伪造真实 AI 证据。

## Acceptance Criteria

- [x] 所有带 `preview` 的现有 Playwright 预演在 FastAPI 未启动时仍通过；请求日志中没有 `/api/auth/me` 或其他真实业务 API，页面 console/pageerror 无错误。
- [x] `/workspaces/{id}?section=current&preview=success` 中“当前”主流程的首个内容焦点位于连接卡之前；`preview=loading/error/forbidden/not_found` 不显示连接卡。
- [x] 主按钮的计算背景色来自 `--action`；链接、焦点和状态仍使用既有语义色；删除重复 CSS 规则后无 `transition: all`、胶囊或新的组件库。
- [x] rubric 预演不向业务界面渲染 `fact_accuracy` 等内部评分项 ID；人工评分、建题和工作台既有交互仍可用。
- [x] 旧前端 Case Builder 展示/服务文件没有活动引用，删除后 `pnpm typecheck`、`make test`、`make build` 和前端预演 E2E 全部通过。
- [x] 使用 `/Users/hsikey/BenchMark/EvalData` 的真实 Provider/Worker 浏览器 E2E 与既有真实 AI 验收通过；真实运行、预演、静态检查和未验证项分别报告。

## Notes

- Keep `prd.md` focused on requirements, constraints, and acceptance criteria.
- Lightweight tasks can remain PRD-only.
- For complex tasks, add `design.md` for technical design and `implement.md` for execution planning before `task.py start`.
