# Cross-layer adversarial review brief

Active task: `.trellis/tasks/08-31-m0-real-ai-e2e-validation`

Review the current branch against the archived M0 PRD and five child task contracts. Focus on API/DTO/OpenAPI synchronization, operation idempotency and stale revisions, task grouping and contract propagation, version lineage/freeze atomicity, runtime/judge/provenance leakage, authorization, frontend service/state behavior, pnpm/build reproducibility, and the explicit EvalData runner. Do not edit files or commit. Use read-only inspection and existing tests; identify boundary cases the current real E2E may still miss. Report file:line, severity, concrete failure scenario, and the smallest correction or additional test needed. Keep M2 out of scope.
