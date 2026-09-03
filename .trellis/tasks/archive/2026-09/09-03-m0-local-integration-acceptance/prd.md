# 完成本地集成与真实验收

## Goal

把已经实现的 Next.js、FastAPI、数据库、上传 Skill 和唯一生产 Worker 收口为可重复运行的当前 Mac 本地系统，并用真实浏览器与真实 AI 证明 M0 全链路可用。

## Dependency

- 前四个子任务全部合并到已验证 `main` 并归档。

## Requirements

- 根命令可同时启动前端、API 和恰好一个 Worker，并正确清理子进程；保留单独调试命令。
- README 准确说明本地准备、迁移、Provider smoke、启动 URL、成功标志和常见失败检查。
- 根质量门覆盖后端、前端类型/测试/构建、OpenAPI 类型漂移和 Playwright。
- 自动化覆盖 Chromium 完整流程与 WebKit 核心流程，以及两个桌面视口的溢出/布局检查。
- 实际 Chrome 完整目检，实际 Safari 核心流程目检。
- 真实验收使用隔离临时业务库与端口、一个 production Worker、真实 Provider 和安全合成材料。
- 真实链路包含网页首注、评测集、凭证提示词、Skill connection/upload、动态维度、老师保存、发布、重开和再发布。
- 验收输出和 artifact 不含密码、Cookie、token、提示词全文、材料正文或 raw model output。
- 更新当前 README 与 `.trellis/spec/`，删除“纯后端/无前端”的过时现行描述。

## Acceptance Criteria

- [ ] `make start-all` 启动三个服务，任一退出会清理其余；页面 URL 与健康检查身份正确。
- [ ] 同一目标数据库只有一个 Worker，重复进程检查有明确失败或处理步骤。
- [ ] `make test`、`make build`、contract check、Skill 测试和 Playwright 全通过。
- [ ] Chromium/WebKit 自动化、实际 Chrome/Safari 与两个桌面视口均通过约定范围。
- [ ] 真实 Provider 全链路输出 `M0_WEB_ACCEPTANCE=PASS`，且维度由材料动态生成 2–6 项。
- [ ] 秘密扫描确认日志、trace、截图、报告、git diff 无长期凭证与业务正文。
- [ ] README/spec 与真实目录、命令、状态、浏览器和本地边界一致。
- [ ] 父 PRD AC1–AC15 在合并后的 main 全部有验收证据。

## Out Of Scope

- 公网部署、域名、HTTPS、Docker/CI/CD 与远程备份。
- 用 Fake、静态页面、端口监听或 HTTP 200 代替真实链路。
- 修改已确认产品范围或增加新功能。

## Open Questions

- 无。
