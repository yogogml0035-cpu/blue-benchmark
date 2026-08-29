# UI Adversarial Review

Written against commit `603fe08` and the uncommitted M0 planning artifacts.

## Design language

- Audited surface: current scene/case flow plus the planned M0 scene-building workflow.
- Design sources: `.interface-design/system.md`, current `case-builder` components, and task `design.md` section 8.
- Valid identity to preserve: quiet light palette, business-teacher vocabulary, one primary action, focused one-section reading, explicit source separation.
- Explicit exception: the current “no scene sidebar because there are only four routes” decision no longer governs M0; the planned workflow has more durable asset types and needs persistent orientation.

## Finding 1 — Backend entities became routes

- Contract: `.interface-design/system.md:17-31` says the teacher is authoring standards rather than operating a configuration dashboard, and each screen should have one focus.
- Evidence: task `design.md:254-278` maps upload, batch, contract, question, evaluation set and version to separate pages.
- Problem: the route map exposes lifecycle entities instead of the teacher's stable mental model, creating page hopping and return-state complexity inside one linear authoring flow.
- Correction: use one Scene Studio as the canonical workspace. Upload, analysis, grouping and scene-standard co-creation are progressive states inside it. Keep separate routes only for a focused question and a read-only version.

## Finding 2 — Permanent support UI competes with the question

- Contract: `.interface-design/system.md:140-202` gives the current question or current review section the whole focal surface.
- Evidence: task `design.md:274,282` proposes a 320–360px contract/judgment drawer alongside the 640–720px main content.
- Problem: a permanently visible second information system recreates the multi-panel density the design system rejected.
- Correction: the standard inspector is closed by default and opens on demand as a side sheet/full-screen sheet. After each answer, show a compact inline Formation Receipt with only the changed items and unresolved gap count.

## Finding 3 — Technical vocabulary and escape hatches leak into teacher UI

- Contract: `.interface-design/system.md:33-55,238-249` requires UI language separate from API language and says development detail should not dominate production UI.
- Evidence: task `design.md:278` proposes `runtime/judge/provenance` and hashes in the version screen; current `DraftEditor.tsx:221-260` exposes a JSON editor; `.interface-design/system.md:219-221` always shows machine codes.
- Problem: UploadBatch/TaskPackage/contract/revision/hash/JSON are implementation concepts. Their visibility makes the product feel like an admin tool and conflicts with the business-teacher persona.
- Correction: UI vocabulary becomes 资料、任务、场景标准、题稿、题、下一版、历史版本. runtime/judge/provenance render as 给 Skill 的材料、评分依据、形成记录. JSON is dev-only. Error IDs and hashes live under a collapsed technical-details disclosure or a copy action.

## Finding 4 — The global 30-character budget is too blunt for consequential review

- Contract: `.interface-design/system.md:107-116` limits explanatory copy to one sentence under 30 characters.
- Counterexample: task grouping, standard promotion, contract-impact review and freeze-risk acknowledgement require enough language to explain consequences before an irreversible action.
- Correction: keep the 30-character rule for page subtitles and passive hints, but allow compact multi-line consequence copy inside confirmation, error and impact-review surfaces. Put detail behind disclosure; do not make critical meaning cryptic merely to satisfy a character count.

## Improve first

Replace the entity-per-route plan with a Scene Studio information architecture. This removes the largest source of navigational and visual complexity before styling individual components.

## UI documentation delta

Do not update `.interface-design/system.md` while current product code still implements the old surface. At implementation start, revise:

1. Direction: allow a scene-local text-only navigation with only “当前 / 题 / 版本” while continuing to reject a generic global SaaS sidebar.
2. Vocabulary: add 资料、任务、场景标准、下一版、历史版本 and human names for the three package views.
3. Text budget: change from a universal character limit to context-specific progressive disclosure.
4. Layout: define three-item scene navigation + focused canvas + on-demand 标准与依据, never a permanent three-column workspace.
5. Production boundaries: remove JSON editor and default machine-code presentation from business surfaces.
6. Signature: add 本轮更新 after each AI turn and make standard lineage visible without a dashboard.
7. Visual system: use a neutral dark primary action, blue only for links/focus/current state, smaller radii, fewer bordered surfaces and no card-in-card.

## Second adversarial review — 2026-08-30

The second pass used live Preview screenshots (`current-workspaces.png`, `current-question-review.png`) and reviewed the revised planning contract rather than only the current source.

### Finding 5 — The proposed navigation mixed unlike concepts

- “共创” is an activity mode, “题” is an asset, “下一版” is a mutable state and “历史” is a time category. Four parallel labels force the teacher to learn the implementation lifecycle.
- Correction: collapse to “当前 / 题 / 版本”. Current owns the sole next action and background work; Question owns drafts and confirmed questions; Version owns both the one working draft and immutable history.

### Finding 6 — AI Native was described as a visual identity rather than a behavior contract

- Naming Scene Studio, Asset Rail and Formation Receipt creates internal design jargon without making the product more intelligent.
- AI-native behavior is: start from evidence, propose one sourced delta, let the teacher confirm consequences, preserve history and recover the exact next action after refresh.
- Correction: use plain Chinese labels and explicitly ban chat bubbles, robot avatars, magic-wand icons, glowing orbs, token streams and fake thinking progress.

### Finding 7 — The current visual baseline is clean but still generic

- The focused one-section review screen has a strong focal point and should be preserved.
- The scene list is a familiar white-card grid with a saturated blue CTA; repeating that pattern across M0 would turn the product into a generic dashboard.
- Correction: M0 uses fewer surfaces, neutral dark primary actions, blue only for focus/link/current state, 6–12px radii, and whitespace/hairlines before cards or shadows.

### Finding 8 — Hiding chat history entirely weakens auditability

- Removing the chat waterfall is correct, but teachers may still need to revisit what they answered and how a standard changed.
- Correction: keep the main canvas focused, but include an on-demand “形成过程” inside the standards/evidence sheet. It contains business questions, teacher answers and accepted deltas—not raw Agent messages or private reasoning.

### Finding 9 — Synchronous co-creation would make the quiet UI dishonest

- If answer submission blocks on a Deep Agent run, refresh loses feedback and the UI must either spin indefinitely or imply progress it cannot know.
- Correction: answer and freeze commands return `202`; the canvas renders persisted business phases and resumes from the same StudioProjection after refresh. This preserves simplicity without hiding failure.

### Finding 10 — Checkpointer can accidentally turn the product into an Agent console

- Stable thread, interrupt, resume and Checkpoint IDs are necessary backend recovery concepts, but none helps a business teacher decide what to do.
- Correction: the UI only receives the projected question, reason, accepted answer status, current business phase, latest receipt and one next action. It never receives or renders thread/checkpoint/interrupt IDs, action requests, decisions, Graph nodes, messages or summaries.
- A resume failure must preserve the already accepted teacher answer and offer one “重试整理” action. The teacher must not re-enter the answer or choose a checkpoint/recovery strategy.
