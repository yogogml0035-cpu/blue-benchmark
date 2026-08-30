# Short cross-layer adversarial review brief

Active task: `.trellis/tasks/08-31-m0-real-ai-e2e-validation`

Read only the current diff, this task's `prd.md`/`implement.md`, `backend/app/features/evaluation_sets/**`, the two relevant child acceptance/PRD files, and `.trellis/spec/guides/cross-layer-contracts.md` plus backend/frontend quality specs. Do not edit or commit. Attack exactly these five questions and report file:line evidence: (1) does the public API expose only business booleans while tests use valid DTO fields; (2) can duplicate/stale commands create extra tasks, turns, drafts or versions; (3) can freeze/download leak judge/provenance or become mutable; (4) can auth/old routes/frontend polling render private or stale content; (5) can the explicit EvalData runner be reproduced without command-ID or pnpm/build drift. Give verified findings, severity, and the smallest fix; stop after a concise report.
