# 实施计划：前端工作台交互与 UI 真实验收修复

## Ordered checklist

1. [x] 从干净且已验证的 `main` 创建 `codex/frontend-interaction-ui-hardening`，执行 `task.py start` 并确认任务分支/base branch。
2. [x] 为 `useSession` 增加显式预演跳过边界，更新所有带 preview 的页面调用方，并将工作台 Session 传递给子组件，消除重复认证请求。
3. [x] 将 Agent 连接卡移到“当前”主流程之后；统一 `--action` 主按钮和 rubric 评分项展示；删除确认无活动引用的旧 Case Builder 前端文件。
4. [x] 扩展预演 E2E：后端关闭时无业务请求/console error，当前内容先于连接卡，窄屏无横向溢出，rubric 不泄漏内部 ID。
5. [x] 每轮代码修改后运行 `git diff --check`、预演 Playwright、`pnpm typecheck`；完成后运行 `make test`、`make build`。
6. [x] 对抗审查：权限/预演越界、Session 重复读取、迟到响应、busy/重复提交、loading/error 私有内容、390px/200% zoom、旧引用和内部标识泄漏；发现问题直接修正并回归。
7. [x] 启动隔离真实 API/Worker，使用 `/Users/hsikey/BenchMark/EvalData` 跑真实 Provider 浏览器 E2E、`ai-smoke` 和完整链路；本地 HTTP runner 直连 loopback，不把预演或历史报告当作真实证据。
8. [ ] 在任务分支通过 `trellis-check` 对应的质量门后提交；切换 `main` fast-forward 合并，重新跑完整质量门和真实 E2E，确认旧分支无未合并提交后安全删除。

## Validation commands

```bash
cd frontend && pnpm exec playwright test e2e/human-scoring.spec.ts e2e/lifecycle-preview.spec.ts
cd frontend && pnpm typecheck
make test
make build
git diff --check
```

真实验收沿用仓库已有 runner，显式指定：

```bash
cd backend && uv run python scripts/accept_real_ai_e2e.py \
  --samples-dir /Users/hsikey/BenchMark/EvalData \
  --base-url http://127.0.0.1:8000
```

## Rollback points

- 预演边界、工作台布局、token 和 dead-code 删除可作为一个前端提交整体回滚；不触碰数据库和后端数据。
- 若真实 E2E 暴露前端合同问题，保留任务分支，修正后重新验证；禁止以跳过真实 Provider、改用 Fake 或删除失败证据收口。
