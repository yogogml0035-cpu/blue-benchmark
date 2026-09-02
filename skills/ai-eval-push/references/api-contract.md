# Batch Upload API Contract

Machine contract for `POST /api/external/question-batches`, authenticated by a
scene credential (`Authorization: Bearer sep_...`). The scene is determined by
the credential; the payload must not carry a scene id.

## Request

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

## Field limits

| Field | Constraint |
|---|---|
| `schema_version` | value must be `"1.0"` when present (defaults to `"1.0"`) |
| `command_id` | 1..255 chars; stable per payload |
| `cases` | 0..50 |
| `client_case_id` | 1..128 chars; unique within the batch and per scene |
| `title` | 1..200 chars, non-blank |
| `task_prompt` | 1..100,000 chars, non-blank |
| `reference_answer` | 1..200,000 chars, non-blank (required per question) |
| `reference_examples` | 0..50 items |
| `bad_cases` | 0..50 items |
| `memory_materials` | 0..50 items |
| `*.client_ref_id` | 1..128 chars; unique within its list |
| `source_name` / `source_label` | optional, <= 200 chars |
| `content_text` | 1..200,000 chars, non-blank |
| `teacher_feedback_texts` | 1..20 items, each 1..5,000 chars, non-blank |
| `reason_summary` | optional, <= 5,000 chars |

`extra` fields are rejected (`422`). Memory material text must be the raw loaded
fragment (no summarizing). Reference examples may be distilled but must stay
source-supported.

## Idempotency

- Same `command_id` + same payload -> original result replayed (201, same ids).
- Same `command_id` + different payload -> `409 COMMAND_ID_REUSED`.
- Business-level case problems (privacy leak, duplicate `client_case_id`, etc.)
  -> the **entire** batch is rejected with `422 BATCH_CASE_INVALID`; the
  `details.cases[]` array names each failing `client_case_id` and its problems
  (problem code `PRIVATE_CONTENT_REJECTED` or `CASE_ALREADY_EXISTS`). Nothing is
  created.
- Schema violations (wrong types, over-length fields, blank required text, extra
  unknown fields, bad `schema_version`) -> `422 VALIDATION_ERROR` from the
  request-validation layer; nothing is created.
- A `client_case_id` that already exists in the scene is caught pre-flight and
  reported inside `BATCH_CASE_INVALID` (problem code `CASE_ALREADY_EXISTS`); the
  top-level `409 CASE_ALREADY_EXISTS` only occurs on a concurrent-write race.

## Response (201)

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

Each question is immediately queued for rubric generation (`status: generating`).
The skill reports these and does not poll further.

## Error codes

| Code | Meaning |
|---|---|
| `CREDENTIAL_REQUIRED` / `CREDENTIAL_INVALID` | missing / invalid / revoked credential (401) |
| `COMMAND_ID_REUSED` | same command, different payload (409) |
| `COMMAND_IN_PROGRESS` | same command currently processing (409) |
| `BATCH_CASE_INVALID` | business-level case problems; nothing created (422); `details.cases[]` names each failing case |
| `VALIDATION_ERROR` | request failed schema validation (types/limits/extra fields); nothing created (422) |
| `CASE_ALREADY_EXISTS` | as a top-level code, only a concurrent-write race (409); normally nested in `BATCH_CASE_INVALID` |
| `PRIVATE_CONTENT_REJECTED` | privacy leak; nested problem code inside `BATCH_CASE_INVALID` on this endpoint |
| `BATCH_CONFLICT` | unexpected write conflict; nothing created (409) |

## Connection check

`GET /api/external/connection` with the same bearer token returns the bound scene
and credential id (never the token):

```json
{
  "status": "connected",
  "scene_id": "<scene uuid>",
  "scene_name": "媒体场景",
  "credential_id": "<credential uuid>",
  "label": "ci",
  "last_used_at": "2026-09-03T00:00:00+00:00"
}
```

## Privacy backstop (server)

Every text field (title, client_case_id, task_prompt, reference_answer, all
example/memory/bad-case bodies, feedbacks, reason, and source names/labels) is
scanned for credentials, host paths, and system-control content after Unicode
normalization and zero-width stripping. Leaks are rejected with
`PRIVATE_CONTENT_REJECTED`. Do the same filtering client-side before previewing.
