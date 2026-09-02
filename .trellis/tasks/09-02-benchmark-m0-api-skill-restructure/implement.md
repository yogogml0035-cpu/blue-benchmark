# Implementation Plan

## Child 1: Backend domain and API

- [ ] Add memory-material request/view/persistence/publication contracts.
- [ ] Replace Rubric criterion schema with `name + description + pass_score` and fixed 10-point scale.
- [ ] Replace score validation with per-criterion mandatory pass and normalized display total.
- [ ] Update AI adapters/prompts/fake fixtures for six materials and three-field output.
- [ ] Update version-package schemas/builders and remove legacy rubric semantics.
- [ ] Add Alembic migration and update backend API/unit/integration tests.
- [ ] Regenerate and verify `backend/openapi.json`.
- [ ] Run backend tests, compile checks, migration checks and adversarial boundary tests.
- [ ] Commit, fast-forward merge to `main`, rerun gates on `main`, archive child and safely delete branch.

## Child 2: Backend-only repository

- [ ] Delete `frontend/` and root Node/pnpm artifacts that only serve it.
- [ ] Remove `FRONTEND_URL`, `draft_url`, frontend CORS assumptions and stale browser routes/documentation.
- [ ] Refactor Makefile to backend/API/Worker/OpenAPI/test commands only.
- [ ] Move contract drift verification fully to backend artifacts.
- [ ] Remove obsolete frontend Trellis specs; update backend/shared specs and README.
- [ ] Run complete backend tests, OpenAPI verification, compile/import checks and `git diff --check`.
- [ ] Commit, fast-forward merge to `main`, rerun gates on `main`, archive child and safely delete branch.

## Child 3: Repository upload Skill

- [ ] Create `skills/ai-eval-push` with `SKILL.md`, UI metadata, scripts and focused API reference.
- [ ] Implement private config loading, connection status, payload validation and idempotent upload.
- [ ] Require a teacher-confirmed preview before mutation and enforce six-material privacy boundaries.
- [ ] Add script/unit tests with a local fake HTTP server and validate the Skill package.
- [ ] Run a real local API HTTP acceptance with a temporary scene-bound credential and approved EvalData input without printing secrets or source bodies.
- [ ] Run full repository checks and final adversarial review across permissions, idempotency, recovery, leakage, migration and storage.
- [ ] Commit, fast-forward merge to `main`, rerun gates on `main`, archive child and safely delete branch.

## Final parent acceptance

- [ ] On `main`, verify clean worktree, no child-only commits, backend test suite, OpenAPI drift, migration head, Skill validation/tests and real HTTP flow.
- [ ] Confirm no Node/Next.js dependency or old Rubric field remains.
- [ ] Update specs, archive parent, record journal and safely delete any remaining completed task branch.
