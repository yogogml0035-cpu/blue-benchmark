# 补齐 M0 Web 后端合同

## Goal

补齐 Next.js 管理端所需、但当前 FastAPI 尚未拥有的业务合同，使认证、评测集生命周期、人工维度确认、重新审改和永久删除都由后端真实约束，而不是由前端模拟。

## Dependency

- 父合同：`.trellis/tasks/09-03-m0-nextjs-integration/prd.md`。
- 本子任务是五个子任务中的第一个，必须从已验证 `main` 独立实施并合并后，才开始 Next.js 工程。

## Requirements

- 新增匿名认证 bootstrap，只返回 `registration_available`，不泄露管理员身份。
- 管理员 CLI 新增交互式密码重置，成功后撤销全部会话；密码不得进入 argv、输出或日志。
- 新增评测集名称/描述更新 API，并让 CLI 复用同一 Service。
- 新增空评测集删除 API；只有当前无题目时允许，删除同步使凭证失效，非空和并发上传必须被原子拒绝。
- 新迁移增加 `criteria_confirmed` 与内部 `ever_published`，并完成 published/other 历史回填。
- AI 生成和材料重生成后 `criteria_confirmed=false`；老师保存维度后为 true；发布必须校验 true。
- `next_action` 区分 `review_criteria` 与 `publish`。
- 新增已发布题目 `review-reopen` 动作，保留材料/维度，清空当前发布时间并退回待发布。
- 加固题目硬删除：revision、生成中拒绝、发布态先重开、曾发布题标题二次确认。
- 签发/轮换凭证响应增加 no-store/no-cache headers。
- OpenAPI、README、CLI、迁移检查、测试和 backend specs 同步。

## Acceptance Criteria

- [ ] 空库 bootstrap=true；首注后为 false；并发第二注册仍被数据库拒绝。
- [ ] 密码重置不泄露密码，失败不改数据；成功后旧密码与全部旧会话失效。
- [ ] 评测集可更新；空集可删且凭证失效；非空/并发上传场景返回 `SCENE_NOT_EMPTY` 且数据完整。
- [ ] fresh、0018 upgrade、downgrade 和 schema-ready 覆盖两个新字段。
- [ ] AI 结果不能直接发布；保存至少一项最终维度后才能发布，列表/详情/next_action 可区分两阶段。
- [ ] 已发布题目可重新打开，保留材料和维度；错误状态和陈旧 revision 返回明确 409。
- [ ] 删除规则在 API 层生效，曾发布题即使刷新后仍要求当前标题确认。
- [ ] 凭证一次性响应不可缓存，状态响应仍不含明文。
- [ ] `make test`、`make build`、迁移和 OpenAPI 漂移检查通过。

## Out Of Scope

- Next.js 或其他前端代码。
- 新题目创建入口、评分执行、候选池/发布版本和回收站。
- 改变六类材料、两字段 `criterion + pass_score` 或 AI 动态 2–6 候选语义。
- 公网部署、限流或多管理员。

## Open Questions

- 无。
