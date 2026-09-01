# 人工评分 Feature 规范

## Scenario: 外部答卷提交与不可变人工评分

### 1. Scope / Trigger

- Trigger：老师把平台外生成的一份主文本绑定到一条已发布题目修订，并按发布时的 rubric 评分。
- Scope：`human_scoring` 的 Router、Service、Repository、数据库迁移和本地答卷存储；不执行 Skill、不调用 AI、不做批量或多答卷比较。

### 2. Signatures

- `POST /api/workspaces/{workspace_id}/question-revisions/{question_revision_id}/submissions`：JSON `command_id`、`content_text`。
- `POST .../submissions/upload`：multipart `command_id`、恰好一个 `file`；文件仅 `.md`/`.txt` UTF-8。
- `GET /api/workspaces/{workspace_id}/submissions/{submission_id}`：返回答卷正文、已发布题目标准和全部评分历史。
- `POST .../submissions/{submission_id}/scores`：JSON `command_id`、每项 `criterion_id/score/reason`，hard-fail 项再传 `hard_fail_triggered`，可传 `parent_score_id`。
- `GET .../submissions/{submission_id}/scores`：只返回评分历史，不返回答卷正文。
- 数据库：`evaluation_submissions`、`human_scores`、`human_score_items`；发布后的评分只有 append，没有 update/delete。

### 3. Contracts

- 访问先经过当前 Session 和 Workspace owner，再读取题目修订或答卷；URL Workspace 与资源不一致返回 `403`。
- 答卷正文最大 `1 MiB`（按 UTF-8 bytes），存储流程固定为 `stage_bytes → publish → ready/hash 校验 → DB`；key 只能是服务端生成的 `submissions/<uuid>/content`。
- command 的幂等 hash 只包含题目修订、来源、文件名、大小和内容 hash，不把正文复制到错误、日志、OperationJob 或版本包。相同 command + 相同 payload 返回原投影，不同 payload 返回 `409 COMMAND_ID_REUSED`。
- 题目、标准答案、评分项和通过线从 `evaluation_sets.service.get_published_question_revision` 获取；不能直接跨 Feature 读取 rubric Repository。
- Service 精确匹配评分项集合，校验每项 `0..max_score`；minimum 关键项由分数推导，hard-fail 关键项只接受老师的布尔判定；总分、关键项结论和通过结论全部由服务端计算。
- `score < reference_expected_score`、minimum 关键项失败或 hard-fail 命中时，该项 `reason` 必填；评分提交后不可覆盖。答卷已有评分时，新评分必须 parent-link 到当前最新评分，禁止新增无 parent 根节点。
- DB 用复合外键守住 `submission.workspace_id = revision.workspace_id`、`score.question_revision_id = submission.question_revision_id`、parent 与 score 属于同一 submission，并用 check/unique 约束守住来源、大小、状态、分数和 command。
- API 启动后可按已提交 ID 回收 `submissions/` 与 `staging/human-scoring/` 下无 DB 记录的 UUID 目录；回收过程可重复且不触碰其他 namespace。

### 4. Validation & Error Matrix

- 未登录 → `401 AUTH_REQUIRED`；已登录但越权 → `403 FORBIDDEN`；授权范围内不存在 → `404 RESOURCE_NOT_FOUND`。
- 非 `.md/.txt`、路径文件名、多个文件或 MIME 不匹配 → `415 UNSUPPORTED_FILE_TYPE` / `422 SINGLE_FILE_REQUIRED`。
- 空白正文、非法 UTF-8 → `422 EMPTY_SUBMISSION` / `422 INVALID_UTF8`；超过 bytes 上限 → `413 FILE_TOO_LARGE`。
- 重复/缺失/未知 criterion、超出该项满分、hard-fail 判定缺失或误传 → `422`；低于锚点或关键失败无理由 → `422 SCORE_REASON_REQUIRED`。
- 已有历史却省略 parent → `409 PARENT_SCORE_REQUIRED`；parent 不属于当前答卷 → `422 INVALID_PARENT_SCORE`；parent 不是最新 → `409 PARENT_SCORE_STALE`。
- ready marker 缺失、长度/hash 不符或绑定题目修订不可读 → 清洗为 `500`，不接受新的评分。

### 5. Good/Base/Bad Cases

- Good：授权老师上传一份 UTF-8 Markdown，同 command 重放返回同一答卷；逐项评分后刷新仍能看到正文、服务端总分和不可变历史；重评从最新 parent 追加。
- Base：数据库写入失败或进程在发布后退出；请求内精确清理，下一次 API 启动回收带 `human-scoring` 前缀且没有 DB 记录的对象。
- Bad：客户端传 `total_score/passed`、漏掉低分理由、把别的答卷的 parent 带入、篡改正文后继续评分、用同 command 换正文；全部 fail-closed。

### 6. Tests Required

- HTTP：owner isolation、未授权先行、题目修订绑定、单文件/扩展名/MIME/UTF-8/1 MiB bytes、同 command 重放与冲突。
- 评分：精确 criterion 集合、范围、伪总分、minimum/hard-fail 推导、理由绕过、首次评分、parent 必填、旧 parent、跨答卷 parent、历史不可覆盖。
- 完整性：ready/hash/大小篡改阻止 GET 和新评分；数据库失败无 final/staging 孤儿；两线程同 command 只有一条答卷。
- 迁移：PostgreSQL `0012 → 0013`、全新 SQLite、旧头回滚/重升、约束/索引/FK/check readiness；应用启动回收幂等。
- 跨层：`make openapi`、`make test`、`make build`、`git diff --check`；真实 Provider/Worker/浏览器流程使用 `/Users/hsikey/BenchMark/EvalData`，只输出阶段和计数。

### 7. Wrong vs Correct

#### Wrong

```python
total = payload.total_score
repository.update_score(score_id, total=total)
```

#### Correct

```python
rubric = evaluation_sets_service.get_published_question_revision(workspace_id, revision_id)
items, total, critical_passed, passed = validate_and_compute(rubric, payload.items)
repository.append_score_with_items(total=total, critical_passed=critical_passed, passed=passed)
```

## Scenario: Cross-revision rescoring

### 1. Scope / Trigger

- Trigger: a teacher appends a new immutable score for an existing submission
  using a later published revision of the same logical question.
- Scope: score target selection, immutable history readback, migration
  constraints, and the human-scoring API; the submission body remains unchanged.

### 2. Signatures

- `ScoreCreateRequest.question_revision_id?: str`: optional for compatibility;
  first scoring must resolve to the submission's original revision, while a
  rescore may select another published revision.
- `HumanSubmissionResponse.question_revisions: dict[str, QuestionRevisionView]`:
  one deduplicated immutable view per published revision of the submission's
  `question_draft_id`.
- `HumanScore.question_revision_id`: the exact revision used for that score;
  it is not required to equal `EvaluationSubmission.question_revision_id`.
- Database `human_scores` has separate foreign keys to the submission and the
  target `benchmark_question_revisions` row; same-question and workspace
  checks remain service invariants.
- Database index `uq_human_score_submission_parent` is unique for non-null
  `parent_score_id`, so one parent can have only one child score even when two
  requests race.

### 3. Contracts

- When `question_revision_id` is omitted, a first score uses the original
  submission revision; a rescore uses the latest score's revision. Replaying a
  command resolves its already-stored target revision before comparing hashes.
- An explicit target must be published, belong to the current Workspace, and
  share the original revision's `question_draft_id`. The target rubric alone
  validates items, totals, critical outcomes, and reasons.
- The score command payload hash includes the resolved target revision, item
  set, parent score, and overall reason; the submission body is never copied.
- Every response exposes the original revision separately and provides the
  deduplicated revision views needed to explain each historical score.

### 4. Validation & Error Matrix

- first score targeting a later revision -> `409 SCORE_REVISION_MISMATCH`;
- unknown/unpublished target -> `404 RESOURCE_NOT_FOUND`;
- target from another Workspace -> `403 FORBIDDEN`;
- target from another logical question -> `409 SCORE_REVISION_MISMATCH`;
- parent not the latest score -> `409 PARENT_SCORE_STALE`;
- same command with another resolved target or payload -> `409 COMMAND_ID_REUSED`.
- concurrent claim of an already-used parent -> `409 PARENT_SCORE_STALE`.

### 5. Good/Base/Bad Cases

- Good: one immutable submission receives a first score on v1 and a parent-linked
  score on v2; GET still returns one body and explains v1/v2 with their own
  criterion names, maximums, anchors, and conclusions.
- Base: an old client omits the target on rescore; the service preserves the
  prior same-revision behavior and command replay remains idempotent.
- Bad: a caller sends v2 criterion IDs while omitting v2, selects another
  question's revision, or supplies an old parent; the request fails before any
  score row is appended.

### 6. Tests Required

- HTTP: first-score original lock, same-question cross-revision append,
  cross-question/workspace/unknown target rejection, old-client compatibility,
  stale parent, idempotency, and immutable body/history readback.
- Migration: empty database 0001→0014, legacy 0013→0014 FK conversion,
  schema-readiness names, unique parent-claim index, and no copied submission
  rows.
- Frontend/browser: revision picker only lists same-question revisions,
  selection clears incompatible criterion inputs, history shows each revision,
  keyboard/native select works, and 390px has no horizontal overflow.

### 7. Wrong vs Correct

#### Wrong

```python
# Every rescore is silently evaluated against the submission's first revision.
rubric = get_published_question_revision(workspace_id, submission.question_revision_id)
repository.add_score(question_revision_id=submission.question_revision_id, ...)
```

#### Correct

```python
target = resolve_score_revision(payload, latest_score, submission)
rubric = get_published_question_revision(workspace_id, target.id)
repository.add_score(question_revision_id=target.id, ...)
```
