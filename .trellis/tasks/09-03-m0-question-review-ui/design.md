# Technical Design

## List

Question service 获取当前 scene 全列表；纯函数执行标题归一化包含搜索、单状态筛选和 `updated_at desc + id` 稳定排序。列表行使用真实 `next_action`，点击导航与行内按钮隔离。详情按路由进入后单独请求。

## Workbench

页面保持 `materials minmax(0, 1fr) + review 420–480px` 双栏。左栏材料独立滚动；右栏 sticky 操作区按后端状态原位切换。动态状态使用稳定高度/轨道，长文本允许纵向增长而不撑宽。

材料阅读模型直接来自 generated DTO；进入编辑时深拷贝为草稿。记忆材料初始折叠。取消丢弃草稿；保存构造 `save-regenerate` payload 并在成功后切回 generating。

## Criterion Draft

页面草稿增加非持久字段 `selected` 与 `source`：

- confirmed=false -> AI 项全部未选；
- confirmed=true -> 当前权威项全部已选；
- 手工新增 `manual-${crypto.randomUUID()}`；
- 保存仅投影 selected 的 `{id, criterion, pass_score}`。

保存前确认永久丢弃未选项。成功后完全采用服务端响应，不保留候选历史。分数使用可键盘操作的整数控件，边界 0–10，最高分不可改。

## State And Polling

- generating：页面 visible 时轮询，hidden 暂停，终态停止；
- failed：重试或从零手工新增维度；
- pending + unconfirmed：必须选择并保存；
- pending + confirmed：可继续保存或独立发布；
- published：只读维度、重新打开、材料编辑。

脏草稿拦截应用内导航和 beforeunload。409 stale 保留草稿并允许查看最新，不自动合并。

## Delete

详情根据 `delete_confirmation_required` 与当前状态选择普通确认或标题输入。published 只显示重新打开，不显示直接删除。请求始终带 revision，API 拒绝是最终事实。

## Rollback

前端回退不能撤销已保存维度或已发布状态；只移除 UI。若后端合同同时回退，generated types 与调用点必须同批一致。
