# Implementation Plan

1. 整理根 Makefile 和前端 scripts，建立三服务生命周期、完整 test/build/contract/E2E 命令。
2. 更新 `.gitignore`，隔离 `.next`、node_modules、Playwright report/trace/video、临时配置和验收数据库。
3. 建立完整 Chromium 与核心 WebKit E2E，覆盖 1280x720/1440x900、错误状态、长内容和无溢出。
4. 建立隔离真实 AI Web runner：安全端口、临时 DB、单 production Worker、Skill config、浏览器闭环和清洗输出。
5. 核对/处理当前重复 Worker，仅操作已解析且属于目标数据库/任务的精确进程。
6. 在实际 Chrome 完成完整流程和 1440x900 截图，在实际 Safari 完成核心流程。
7. 扫描控制台、网络摘要、report、trace、截图目录和 git diff，确认无密码/Cookie/token/提示词全文/材料正文。
8. 更新 README、frontend specs、backend/shared specs 与验收说明。
9. 运行全量质量门和父 AC1–AC15 审计，输出 `M0_WEB_ACCEPTANCE=PASS`。
10. 经 `trellis-check` 后提交、fast-forward 合并 main，在 main 再跑完整门禁、归档子任务，再完成父任务最终验收。

## Risky Files

- 根 `Makefile` 三进程 trap
- real acceptance runner 的秘密与临时路径处理
- Playwright artifact 与 actual Safari 验收记录
- README/spec 当前事实更新

## Stop Conditions

- 无法确认目标 Worker/数据库身份；
- 真实 Provider 仅 smoke 成功但 Web 闭环未完成；
- 任何 artifact 泄露 token、Cookie、密码或材料正文；
- WebKit 通过被误报为实际 Safari 已通过；
- 本地验收被扩展成公网部署。
