# 前端质量与验证

## 当前自动化边界

`frontend/package.json` 当前提供 `typecheck` 和 `build`，没有 lint、单元测试或 Playwright 脚本；仓库也没有前端测试文件。不要把 ESLint、Vitest、Jest、Playwright 或覆盖率写成已存在的自动质量门。

现行命令：

```bash
cd frontend && pnpm typecheck
cd frontend && pnpm build
make test
```

`make test` 运行后端 pytest、前端 typecheck 和 OpenAPI/生成类型一致性检查；涉及 App Router、生产门控或构建边界时再运行 `make build`。

## 状态验收

登录、场景列表、场景工作台、上传入口、聚焦题页和版本详情通过 `?preview=` 提供开发态预演，支持各页面声明的 loading、empty、success、error、unauthorized、forbidden、not_found、question、review 状态。预演 fixture 使用生成 DTO，可以作为类型回归证据，但不是浏览器自动化测试。

真实闭环仍按 `README.md` 人工验收：注册、建场景、上传、任务分组拆分/合并、场景标准和单题共创、组集、冻结下载、刷新恢复、跨账号 403 和错误恢复。只有实际执行后才能声称浏览器路径跑通。

## Review 清单

- [ ] App Router 页面仍然薄，交互只下沉到必要的 Client Component。
- [ ] 组件通过 Feature Service 请求，未直接 `fetch` 或复制 DTO。
- [ ] 受保护页在会话完成前不渲染私有数据；401/403/404/409 行为正确。
- [ ] 命令期间禁止重复提交，成功后采用服务端快照。
- [ ] 上传在同一表单重试复用稳定 command；静默轮询遇到 401/403/404 清空旧内容，workspace/batch 变化后的迟到响应被丢弃。
- [ ] 任务分组回归覆盖 `task_packages=[]` 的零候选但有可用资料、分析进行中、全部资料 ignored 三种状态；前者可手动确认，后两者不能展示可确认编辑器且必须有明确出口。
- [ ] `projection_pending` 不被伪装成普通处理中，页面提供服务端重投影/重试动作。
- [ ] 新状态已同步 `STATE_META`、进度派生、错误视图和预演 fixture。
- [ ] 表单标签、键盘操作、焦点、busy、alert 与 reduced-motion 没有回退。
- [ ] 样式复用全局 token；大块 Feature 样式在 colocated CSS Module。
- [ ] `pnpm typecheck` 通过；路由/生产门控变更还通过 `pnpm build`。

## 禁止用假证据收口

- Typecheck 通过不等于交互已验收。
- 预演 fixture 可渲染不等于真实 API 已连通。
- 页面能打开不等于后端、授权和完整 Case Builder 闭环可用。
- README 或技术合同写了未来能力，不等于仓库已经实现。
