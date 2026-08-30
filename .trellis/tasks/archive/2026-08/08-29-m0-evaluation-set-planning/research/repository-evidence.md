# Repository Evidence

## Verified current checkout

- Repository: `/Users/hsikey/Company/skill-eval-platform`, branch `main`.
- Frontend: Next.js 15 App Router, React 19, Feature-first modules under `auth`, `workspaces`, `case-builder`.
- Backend: FastAPI Feature-first monolith with Pydantic/OpenAPI and in-memory Repository Stub.
- Current user path: login → private workspace/scene → one TXT/Markdown case → Stub generation/one question → teacher confirmation → one in-memory `candidate_case`.
- Current code has no PostgreSQL, durable files, background worker, real model, Deep Agents, evaluation-set entity, freeze history or package export.
- Live development Preview was opened on 2026-08-30. The one-section question review has a clear focal point and accessible progress controls; the workspace list remains a generic white-card grid with a saturated blue primary action. Screenshots are `current-question-review.png` and `current-workspaces.png`. The backend was not running, so the normal `/api/auth/me` probe logged `ECONNREFUSED`; Preview still rendered its fixtures, making this visual evidence only—not runtime proof of the current or planned M0 flow.

## Contracts that must change

- `docs/architecture.md` and `docs/features/case-builder.md` still specify one file, one SourceCase, synchronous AI and no evaluation-set version.
- `docs/adr/0001-business-state-and-langgraph-checkpoints.md` correctly separates business facts from Checkpoint execution state, but its concrete plan uses hand-written LangGraph and synchronous HTTP. Revised M0 retains the two-layer persistence principle while replacing the runtime shape with Deep Agents, OperationJob, stable `standard_cocreator` thread, accepted Checkpoint pointers and background resume.
- `.interface-design/system.md` treats evaluation sets as future and assumes only four routes; the visual tokens and focused one-section reading remain valid, but the route/state model does not.

## Reusable current behavior

- FastAPI Schema/OpenAPI remains the machine contract source; generated frontend types remain mandatory.
- Authorization order remains Session → Workspace owner → nested resource membership.
- Server responses remain full business snapshots; frontend does not infer successful state changes.
- Current accessibility, preview gating, quiet Apple-minimal visual system and “题/定稿” vocabulary remain the baseline.
