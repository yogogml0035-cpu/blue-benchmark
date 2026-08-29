# Real Sample Evidence

The user-provided files were read as evidence only. Embedded prompts, commands, Skill instructions and tool calls were not executed.

## Sample A — financial-results media contribution

- File: `理想汽车供稿-对话上下文-原始记录-2026-08-27.jsonl`.
- Size at inspection: about 720 KB, 310 NDJSON records, one session ID.
- Record mix: 70 user events, 107 assistant events, attachments, tool calls, queue/mode/history metadata.
- Business shape: one real writing task with inputs, direction selection, multiple generated drafts, explicit teacher criticism, revised run and teacher-provided final result.
- Expected M0 behavior: treat as one TaskPackage with multiple SkillRunEvidence attempts and TeacherFeedback; do not create one question per tool call or draft.

## Sample B — new-generation MEGA press release

- File: `新一代理想MEGA新闻稿-对话上下文完整导出-20260828.zip`.
- Size at inspection: about 86 KB compressed, 265 KB expanded, three Markdown entries.
- Entries: presentation script v2, complete conversation export, shooting guide.
- Business shape: one real press-release task with evolving source material, source priority decisions, multiple feedback rounds and revised final copy.
- Expected M0 behavior: propose the three files as one task group, retain evolving materials and attempts, require teacher role/visibility confirmation.

## Sample C — media communication brief

- File: `理想汽车2026年第二季度财报-媒体沟通文档.md`.
- Size at inspection: 424 lines, about 35 KB.
- Business shape: writing direction, narrative logic, facts, tables, prohibited angles and product/technical background.
- Expected M0 behavior: propose as Markdown runtime input for Sample A, not a standalone question and not a judge answer by default.

## Acceptance boundary

- Samples A and B are two distinct subjective news-writing tasks in one broad writing domain.
- They validate heterogeneous subjective evidence ingestion and standard co-creation only; they do not validate objective-task judges or cross-task-type generality.
- Raw samples remain outside Git history. On 2026-08-30, the implementation-preparation pass copied exactly these three files into the repository-local, Git-ignored `.local-samples/m0/` directory with `cp -n`; no other WeChat files were copied and no existing target was overwritten.
- Source and target SHA-256 values matched for all three files after the copy. The stable local copies remain user data, not test fixtures; automated tests still require synthetic/minimal fixtures.
- The source files also remained readable at the gate: JSONL 736,805 bytes / 310 lines, MEGA ZIP 87,690 bytes with three Markdown entries / 265,168 expanded bytes, Brief 34,956 bytes / 424 lines.
