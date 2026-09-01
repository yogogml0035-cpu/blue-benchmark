# M0 评测集版本与版本包规范

## 先确认当前实现边界

`evaluation_sets` 已实现单用户场景下的唯一下一版本草稿、合同影响复核、覆盖快照、freeze OperationJob 和本地不可变三分区包。已发布的 `BenchmarkQuestionRevision` 可以作为 Working Set 成员，与旧 `TaskPackage` 成员共存；含新题目修订的版本使用独立的 v2 package builder/reader。M2 的 Skill/Agent 执行、judge 运行和报告不属于当前实现。历史版本的内容事实只来自版本记录指向的 ready 文件。

## Scenario: Working Set 与 immutable package

### 1. Scope / Trigger

- Trigger: 老师把已确认题加入唯一下一版本草稿，经完整性门和覆盖风险确认后冻结为连续版本。
- `evaluation_sets/service.py` 负责授权、revision、门禁和投影；`repository.py` 负责 draft/member/review/coverage/version 数据；`lib/version_packages` 负责纯快照构建和 canonical 序列化。

### 2. Signatures

- `POST /api/workspaces/{workspace_id}/evaluation-sets/drafts`：`command_id`，从最新冻结 Manifest 派生唯一 active draft。
- `POST /api/workspaces/{workspace_id}/evaluation-sets/drafts/{draft_id}/members`：`command_id`、`draft_revision`、`task_package_id`、`task_package_revision`、`action=include|remove`。
- `POST /api/workspaces/{workspace_id}/evaluation-sets/drafts/{draft_id}/impact-reviews/{task_package_id}`：老师逐题 `reviewed` 或无冲突确认；AI 不能代替。
- `POST /api/workspaces/{workspace_id}/evaluation-sets/drafts/{draft_id}/coverage-review`：返回 `202`，Worker 保存当前 draft revision 的 CoverageSnapshot。
- `POST /api/workspaces/{workspace_id}/evaluation-sets/drafts/{draft_id}/freeze`：`command_id`、`draft_revision`、覆盖风险确认，返回 `202` 和 freeze OperationJob。
- `GET /api/workspaces/{workspace_id}/evaluation-sets/versions/{version_id}/manifest` 与 `/download`：只读取版本记录指向的 ready Manifest/ZIP。
- 数据表：`working_set_drafts`、`working_set_members`、`working_set_commands`、`contract_impact_reviews`、`coverage_snapshots`、`evaluation_set_versions`；active draft 用 `active_key=workspace_id` 保证单一工作线。

### 3. Contracts

- Draft 以 `revision` 做 CAS；成员变更、影响复核会推进 revision，CoverageSnapshot 必须精确匹配当前 revision。discard 后只能从最新版本重新派生。
- 冻结硬门：合同已确认；至少一道 included 且已定稿题；任务快照、判定依据、来源证据、文件 visibility 和 runtime 输入完整；所有合同冲突已逐题复核或确定性无冲突批量确认；当前 coverage 已生成；覆盖 warning 已由老师明确确认。
- v1 `runtime.json` 只允许 `schema_version/tasks/task_id/title/brief/input_files`，文件只允许 `file_id/name/media_type/sha256/content`；参考结果、hard gate、评分维度、老师判断和形成记录分别保存在 `judge.json`/`provenance.json`。v1 builder/reader 不改写历史字节。
- Working Set 成员必须且只能引用一个来源：旧成员保存 `task_package_id + task_package_revision`， authored 成员保存 `question_revision_id + question_revision_number + question_revision_hash`。后者由外键、XOR check 和发布内容 hash 同时约束。
- v2 `runtime.json` 只含题目输入、brief 和 runtime 可见资料；`judge.json` 对 authored 题目包含标准答案、rubric 和 threshold；`provenance.json` 包含来源题目修订、hash、资料元数据和老师发布信息。发布后资料元数据或可见性变化会阻塞冻结，不静默改变题目。
- runtime 文件在进入 Agent 或版本包前都要再次验证 ready marker、字节数和 SHA-256；任务 revision 落后于 WorkingSetMember 时即使同一个题 ID 仍然阻塞 freeze。
- 场景合同确认会传播到当前 workspace 内所有已确认任务；如果题的既有判定依据来自旧合同修订，TaskPackage 会保留历史数据但不再标记为当前可用，必须重新完成单题共创后才可冻结。
- 下一版草稿中的 `reviewed`/`no_conflict_confirmed` 是老师明确认可旧判定依据仍适用于新合同的放行证据；只有在该草稿影响复核完成后，freeze 才可读取这份旧依据，普通题读取仍保持严格不匹配阻塞。
- 标准升级提案批准同样创建合同新修订并使旧题判定依据进入复核；拒绝或仅本题保留不能改变场景合同。
- Manifest 使用固定排序和 JSON 序列化，记录合同快照、题 revision、来源文件 hash、分区 hash、冻结人/时间、风险确认和 `overall_sha256`。ZIP 固定条目顺序/时间戳；API 和下载都校验 Manifest、三个分区和 ZIP 内容一致。
- Manifest 的 `version.id/workspace_id/number` 必须分别等于 `EvaluationSetVersion` 的数据库字段；freeze command 在同一 workspace 不能复用于另一份草稿。历史派生前也必须先完成整包完整性校验，不能只读 Manifest。
- 历史派生读取 v1 或 v2 Manifest 后都必须校验版本身份、三个分区 hash、ready marker、ZIP 条目和分区内容；不能把 v2 Manifest 交给 v1 reader，也不能把 v2 authored 成员降级成旧 TaskPackage。
- freeze 先 staging 和 ready marker，再以 draft revision CAS 创建 `EvaluationSetVersion`；打包或 DB 失败不能留下可见版本。相同 `freeze_command_id` 重试只返回同一版本。draft 创建 command 在终态后重放仍返回原 draft，不因 active draft 已清除而创建第二份 lineage；OperationJob command 若跨 `coverage_review` / `freeze_package` kind 复用必须冲突。
- API 不返回 storage key、绝对路径、Checkpoint、原始消息或 private reasoning；教师完整下载包时，调用方必须把 runtime 分区与 judge/provenance 分开使用。

### 4. Validation & Error Matrix

- 无已确认合同、无题、题未定稿、文件不可读/未确认 visibility、判定依据缺失、合同影响 `review_required`、coverage 缺失/过期 -> `409 FREEZE_BLOCKED` 或更具体的 `CONTRACT_NOT_CONFIRMED`/`CONTRACT_REVIEW_REQUIRED`。
- coverage 有 warning 且没有老师确认 -> `409 COVERAGE_RISK_CONFIRMATION_REQUIRED`；有确认说明才允许 freeze。
- stale draft/task revision -> `409 STALE_DRAFT`/`STALE_TASK_PACKAGE`；非 active draft -> `409 DRAFT_NOT_EDITABLE`。
- 同一个 command 相同 payload 返回已有投影/版本；相同 command 不同 payload -> `409 COMMAND_ID_REUSED` 或 `FREEZE_IN_PROGRESS`。
- Manifest、任一分区或 ZIP ready marker/hash 不一致 -> 不提供内容，返回清洗后的 `500 VERSION_PACKAGE_UNREADABLE`/`VERSION_HASH_MISMATCH`。
- 版本号只可由最新版本号加一生成；并发冲突不得重写旧版本，失败保留可重试 OperationJob/intent。
- draft/member/review/coverage/version 的写事务锁定当前 draft（分配合同/版本号时锁定 workspace），并在提交前再次 CAS；题 revision 过期必须阻塞而不能静默采用最新题稿。

### 5. Good/Base/Bad Cases

- Good: 一道已确认主观题可冻结为 v1；从 v1 Manifest 派生草稿并冻结 v2，v1 Manifest/hash/ZIP 字节保持不变。
- Base: 合同改版使旧题进入 `review_required`；老师逐题写下无冲突结论后才能运行 coverage/freeze。coverage warning 不阻塞题量，但必须有明确风险确认。
- Bad: 从可变 TaskPackage 重拼历史、把 `reference_results` 放进 runtime、覆盖 ready 文件、打包一半写入版本行、或把 model 说“覆盖充分”当作老师放行；都必须拒绝或 fail-closed。

### 6. Tests Required

- Draft：唯一 active draft、从 Manifest 派生、include/remove、discard/rebuild、stale revision、同命令幂等和 payload 冲突。
- Authored member：发布题目修订列表、加入/移除、跨 workspace 403、重复 command、stale revision/hash、旧合同不一致阻塞，以及 legacy/authored mixed freeze。
- Gates：合同/题/判定依据/来源/visibility/coverage/impact review 的逐项失败；覆盖不足经老师确认可冻且无固定题数。
- Package：canonical hash 稳定、三分区 allowlist、runtime 机械泄漏、ZIP 条目和分区 hash 一致、文件篡改导致 API/download 拒绝。
- Concurrency/recovery：freeze `202`、重复 command 单版本、打包失败无可见版本并可重试、Worker 在 DB 提交后崩溃重跑不生成 v2、连续版本和历史不可变。
- Cross-layer：`make openapi` 生成 `backend/openapi.json` 与 `frontend/src/lib/api/generated.ts`，`make test`/`make build` 通过。

### 7. Wrong vs Correct

#### Wrong

```python
manifest = build_from_live_task_rows(workspace_id)
return json.dumps(manifest)
```

#### Correct

```python
artifacts = build_package(tasks=confirmed_snapshots, ...)
publish_staging_and_ready(artifacts)
create_version_if_current(draft_revision, hashes=artifacts.hashes)
```

历史读取只跟随已生成的 Manifest/分区/ZIP keys；业务表的后续编辑不能改变已冻结版本。
