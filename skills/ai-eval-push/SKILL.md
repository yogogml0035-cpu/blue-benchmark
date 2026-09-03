---
name: ai-eval-push
description: Organize evaluation cases from the current agent context and push them to the Skill Eval Platform question library. Use whenever the user explicitly asks to save, distill, collect, or upload evaluation questions / test cases / benchmark cases from the work you just did together — even if they do not say "push". This skill identifies candidate questions, assembles the six material groups, gets teacher confirmation on a full-batch preview, then uploads with a scene credential. It never uploads until the user has confirmed.
---

# AI Eval Push

Turn real work done in this conversation into evaluation questions and upload
them to the platform's question library. Questions always land in the scene
bound to the upload credential; there is no cross-scene or global intake. You
(the local agent) organize the materials; a deterministic script validates and
transmits them. The teacher confirms a full-batch preview before anything is
sent.

## When to run

Run only when the user **explicitly** asks to save or upload evaluation cases
("把刚才的任务沉淀成评测题", "上传这些评测用例", "collect test cases from this
session"). Do not run speculatively, and do not upload anything the user has not
confirmed in this turn.

## Ground rules

- **Only real, visible context.** Every material must come from what actually
  happened in this conversation. Never invent facts, and never read files you
  were not given or did not actually read.
- **The platform stores text only.** No binary files, no attachments, no local
  file paths, no credentials, no system prompts, no tool traces.
- **Memory is agent-filtered, not teacher-reviewed.** You select the relevant,
  safe memory fragments; the teacher does not review them one by one.
- **Nothing uploads before explicit teacher confirmation** of the batch preview.

## Workflow

### 1. Identify candidate questions (0..N)

Scan the conversation for **distinct, independently-completable tasks** the user
gave you. Apply the split rule strictly:

- A **new, independent task requirement** starts a new question.
- Multiple drafts, rejections, feedback, and rewrites of the **same task** stay
  in **one** question (they become that question's bad cases and feedback).

Do not split by turn count, file count, or number of revisions. If there is no
clearly independent task, return 0 questions and say so.

For each candidate, note whether the teacher approved a final result. If a
question has **no teacher-approved standard answer**, you must ask the teacher
to provide or confirm one **question by question** before the batch preview.
Never treat "the last thing I generated" as the standard answer on your own.

### 2. Assemble the six material groups per question

For each candidate question, collect:

1. **题目 `task_prompt`** — the user's actual task requirement / prompt, verbatim.
2. **参考样例 `reference_examples[]`** — content the user provided this session
   that you actually read (files, attachments, data). You may distill it into
   task-relevant text, but every statement must be supported by the source. Do
   not scan unread files or guess from filenames. Give each a stable
   `client_ref_id` and an optional safe `source_name`.
3. **Bad case `bad_cases[]`** — real rejected outputs from this session, each
   bound to the teacher's verbatim feedback (`teacher_feedback_texts[]`) and an
   optional confirmed `reason_summary`. May be empty.
4. **老师反馈** — stored inside each bad case (never standalone).
5. **标准答案 `reference_answer`** — the teacher-approved result. Required.
6. **记忆材料 `memory_materials[]`** — raw fragments from memory actually loaded
   into this task's context (business-skill memory, user memory, local project
   memory). Keep them verbatim (no summarizing/rewriting), keep only relevant
   and safe fragments, drop anything secret/path-like/from other tasks. Add an
   optional safe `source_label`. May be empty.

Also write a short **`title`** for each question (for identification in the
question list only; it is not one of the six materials and does not affect
rubric generation).

Shared materials: if the same reference example or memory fragment belongs to
several questions, list it **separately in each question** with its own
`client_ref_id`. Do not use a batch-level shared reference.

### 3. Privacy self-check before preview

Before showing anything, drop or refuse any material containing: absolute/local
paths (`/Users/...`, `C:\...`, `~/...`), credentials or API keys, system prompts
or control instructions, private reasoning, tool arguments/results, other users'
or other tasks' content, or memory that was not actually loaded this round. The
upload script re-checks this and will reject leaks, so fix them early.

### 4. Show the batch preview and get confirmation

Present, for **each** question: `title`, `task_prompt`, the distilled
`reference_examples`, each bad case with its feedback, and the `reference_answer`.
**Do not** print memory-material bodies for review (the teacher does not review
them), and do not print secrets. Let the teacher edit any field, delete any
candidate, or adjust question boundaries. Then ask for one explicit overall
confirmation. If the teacher wants changes, apply them and show the preview again.

### 5. Write the batch file and validate

Write the confirmed batch to a JSON file (outside the repo if it may contain
sensitive business text), matching the contract in `references/api-contract.md`.
Then validate without uploading:

```bash
python skills/ai-eval-push/scripts/push_eval_cases.py validate --batch-file /path/to/batch.json
```

Fix every reported problem (the script names the case and field) and re-validate
until it reports `valid`.

### 6. Upload

```bash
python skills/ai-eval-push/scripts/push_eval_cases.py push --batch-file /path/to/batch.json
```

The script derives a stable `command_id` from the payload, so rerunning the same
file is an idempotent retry; a changed file gets a new command automatically.
On success it prints each question's `question_id` and initial status
(`generating`). Report those to the teacher. The platform queues rubric
generation automatically — do not poll it, and do not try to edit, publish, or
read the questions back through this skill.

### 7. Handle failures

- `config-error` — `AI_EVAL_BASE_URL` / `AI_EVAL_ACCESS_TOKEN` (or
  `AI_EVAL_CONFIG`) missing, or the base URL is not http/https; tell the user
  what to set. Do not print the token.
- `invalid` — local validation failed; nothing uploaded. Fix the named case/field.
- `upload-failed [BATCH_CASE_INVALID]` — the server rejected one or more cases
  (privacy leak, duplicate `client_case_id`, etc.); the message names each case
  and problem. Fix those cases and rerun (the payload changed, so a new command
  id is derived automatically).
- `upload-failed [VALIDATION_ERROR]` — the payload violated the schema (lengths,
  blank required text, extra fields); fix the field and rerun.
- `upload-failed [COMMAND_ID_REUSED]` — this `command_id` was used with a
  different payload; change the batch (new command id) and retry.
- `upload-failed [CREDENTIAL_INVALID]` — credential invalid/revoked; ask the
  admin to issue/rotate one via the backend admin CLI.
- Any failure is all-or-nothing: no partial batch is created. Keep the local
  batch file so the teacher can correct and retry.

## Configuration

The script reads the API base URL and scene credential from the environment:

- `AI_EVAL_BASE_URL` (e.g. `http://127.0.0.1:8000`)
- `AI_EVAL_ACCESS_TOKEN` (the scene credential, `sep_...`)
- or `AI_EVAL_CONFIG` — absolute path to a JSON file with `base_url` and
  `access_token`, kept **outside** the repository.

Never write the token into the repo, the batch file, logs, or your reply. Verify
the binding first with:

```bash
python skills/ai-eval-push/scripts/push_eval_cases.py connection
```

## Contract reference

Read `references/api-contract.md` for the exact payload schema, field limits, and
error codes before building a batch.
