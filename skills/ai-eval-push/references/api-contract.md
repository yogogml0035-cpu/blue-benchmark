# 批量上传 API 合同

`POST /api/external/question-batches` 的机器合同，使用场景凭证鉴权（`Authorization: Bearer sep_...`）。场景由凭证决定；载荷中不得携带场景 id。

## 请求

```json
{
  "schema_version": "1.0",
  "command_id": "skill-<stable>",
  "cases": [
    {
      "client_case_id": "case-001",
      "title": "新闻稿改写",
      "task_prompt": "请把提供的新闻素材改写成一段正式新闻稿。",
      "reference_examples": [
        {
          "client_ref_id": "ref-1",
          "source_name": "新闻素材",
          "content_text": "老师提供且 Agent 实际读取过的内容。"
        }
      ],
      "bad_cases": [
        {
          "content_text": "一份被否定的初稿。",
          "teacher_feedback_texts": ["语气太随意。"],
          "reason_summary": "语体不符合新闻稿规范。"
        }
      ],
      "reference_answer": "老师认可的标准答案。",
      "memory_materials": [
        {
          "client_ref_id": "mem-1",
          "source_label": "业务记忆",
          "content_text": "本轮实际加载的相关记忆原文。"
        }
      ]
    }
  ]
}
```

## 字段限制

| 字段 | 约束 |
|---|---|
| `schema_version` | 出现时必须为 `"1.0"`（缺省即 `"1.0"`） |
| `command_id` | 1..255 字符；同一载荷保持稳定 |
| `cases` | 0..50 |
| `client_case_id` | 1..128 字符；批次内唯一，且场景内唯一 |
| `title` | 1..200 字符，非空白 |
| `task_prompt` | 1..100,000 字符，非空白 |
| `reference_answer` | 1..200,000 字符，非空白（每题必填） |
| `reference_examples` | 0..50 条 |
| `bad_cases` | 0..50 条 |
| `memory_materials` | 0..50 条 |
| `*.client_ref_id` | 1..128 字符；所在列表内唯一 |
| `source_name` / `source_label` | 可选，<= 200 字符 |
| `content_text` | 1..200,000 字符，非空白 |
| `teacher_feedback_texts` | 1..20 条，每条 1..5,000 字符，非空白 |
| `reason_summary` | 可选，<= 5,000 字符 |

`extra` 字段会被拒绝（`422`）。记忆材料文本必须是实际加载的原文（不得总结）。参考样例可以提炼，但必须有出处支撑。

## 幂等性

- 相同 `command_id` + 相同载荷 -> 重放原始结果（201，相同 id）。
- 相同 `command_id` + 不同载荷 -> `409 COMMAND_ID_REUSED`。
- 业务级题目问题（隐私泄漏、`client_case_id` 重复等）-> **整批**以 `422 BATCH_CASE_INVALID` 拒绝；`details.cases[]` 数组逐条指明失败的 `client_case_id` 及其问题（问题码为 `PRIVATE_CONTENT_REJECTED` 或 `CASE_ALREADY_EXISTS`）。不创建任何内容。
- Schema 违规（类型错误、字段超长、必填文本为空、多余未知字段、`schema_version` 非法）-> 请求校验层返回 `422 VALIDATION_ERROR`；不创建任何内容。
- 场景内已存在的 `client_case_id` 会在预检阶段被捕获，并归入 `BATCH_CASE_INVALID` 上报（问题码 `CASE_ALREADY_EXISTS`）；顶层 `409 CASE_ALREADY_EXISTS` 只出现在并发写入竞态时。

## 响应（201）

```json
{
  "command_id": "skill-<stable>",
  "scene_id": "<scene uuid>",
  "accepted_case_count": 2,
  "cases": [
    { "client_case_id": "case-001", "question_id": "<uuid>", "status": "generating" }
  ]
}
```

每道题会立即进入评分维度生成队列（`status: generating`）。Skill 报告这些结果即可，不做后续轮询。

## 错误码

| 错误码 | 含义 |
|---|---|
| `CREDENTIAL_REQUIRED` / `CREDENTIAL_INVALID` | 凭证缺失 / 无效 / 已吊销（401） |
| `COMMAND_ID_REUSED` | 相同命令、不同载荷（409） |
| `COMMAND_IN_PROGRESS` | 相同命令正在处理中（409） |
| `BATCH_CASE_INVALID` | 业务级题目问题；不创建任何内容（422）；`details.cases[]` 逐条指明失败题目 |
| `VALIDATION_ERROR` | 请求未通过 schema 校验（类型 / 长度 / 多余字段）；不创建任何内容（422） |
| `CASE_ALREADY_EXISTS` | 作为顶层错误码时仅表示并发写入竞态（409）；通常嵌套在 `BATCH_CASE_INVALID` 内 |
| `PRIVATE_CONTENT_REJECTED` | 隐私泄漏；本端点上是 `BATCH_CASE_INVALID` 内的问题码 |
| `BATCH_CONFLICT` | 意外写入冲突；不创建任何内容（409） |

## 连接状态检查

`GET /api/external/connection` 使用同一 bearer token，返回绑定的场景与凭证 id（绝不返回 token）：

```json
{
  "status": "connected",
  "scene_id": "<scene uuid>",
  "scene_name": "媒体场景",
  "credential_id": "<credential uuid>",
  "last_used_at": "2026-09-03T00:00:00+00:00"
}
```

## 隐私兜底（服务端）

所有文本字段（title、client_case_id、task_prompt、reference_answer、全部样例 / 记忆 / bad case 正文、反馈、原因总结、来源名 / 标签）都会在 Unicode 归一化和零宽字符剥离后，扫描凭证、主机路径与系统控制内容。泄漏会以 `PRIVATE_CONTENT_REJECTED` 拒绝。预览前请在客户端先做同样的过滤。
