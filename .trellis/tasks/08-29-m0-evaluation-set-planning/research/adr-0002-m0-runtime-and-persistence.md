# ADR-0002: M0 Runtime and Persistence Authorities

Status: planned contract; implementation approval pending

Date: 2026-08-30

## Context

M0 needs durable business facts, resumable long-running operations, one
multi-turn AI co-creation session, and immutable evaluation-set packages. These
requirements create several persistence mechanisms with different semantics.
Treating them as one database simply because they may share PostgreSQL would
make recovery, authorization, and history ambiguous.

The previous repository ADR and architecture files are currently deleted in the
working tree by another change. This task-scoped ADR records the implementation
decision without restoring or overwriting those paths.

## Decision

### PostgreSQL business tables

Own users, sessions, workspaces, upload/evidence records, confirmed file roles,
task packages, teacher answers, scenario contracts, question revisions,
working-set drafts, frozen versions, audit records, revisions, idempotency keys,
and the one accepted Checkpoint pointer. These tables are the only business
authority exposed through Services and APIs.

### OperationJob and AgentRunAttempt

Own scheduling, leases, retries, deadlines, command idempotency, active-operation
UI projection, model/tool/transport counters, base/produced Checkpoint pointers,
result hashes, projection_pending, and superseded outcomes. They are not Graph
state and do not store raw model messages or business evidence.

### PostgreSQL Checkpointer

Owns only `standard_cocreator` execution continuity: messages, tool-call pairing,
pending interrupt, StateBackend scratch, Checkpoint history, and resume cursor.
The application always resumes from the business table's explicit accepted
Checkpoint ID, never raw thread latest. Checkpoint payloads are encrypted,
access-isolated, retained by thread lifecycle, and deletable without deleting
confirmed business assets.

`batch_analyzer` and `coverage_reviewer` use fresh attempts and no stable
Checkpointer thread.

### Store and Memory

LangGraph Store, StoreBackend Memory, MemoryMiddleware, cross-thread facts, and
cross-scene implicit memory are disabled in M0. Every cross-session fact comes
from business tables through an authorized Service.

## Consistency and recovery

- A Graph step may produce a Checkpoint before the business projection commits.
  AgentRunAttempt records the produced pointer; recovery uses read-only
  `get_state` re-projection and never repeats the model call.
- The accepted pointer advances only in the successful business CAS transaction.
  A stale revision, different accepted pointer, or active concurrent resume is
  rejected. Raw latest branches can remain orphaned but never become authority.
- Missing or incompatible Profile/Graph versions fail closed. Recovery creates
  an explicit continuity reset from business projections on a new thread and
  records the old/new identifiers and reason.
- OperationJob remains the queue and retry authority even though Checkpointer
  can resume Graph execution.

## Migration and security

- Business migrations and Checkpointer setup are separate deployment commands.
- Normal API/Worker startup validates both schemas but does not create them.
- Business and Checkpointer connections use distinct settings and production
  roles, even when they share a PostgreSQL instance.
- The AES key is injected only through deployment environment configuration;
  it is absent from Git, logs, DTOs, metrics, and test artifacts.
- Active, waiting-for-answer, retryable, and projection_pending threads are
  protected from retention cleanup. Completed threads may be deleted only after
  business-independent readback passes.

## Consequences

- More explicit pointers and CAS checks are required, but each recovery path has
  one authority.
- Deleting Checkpoint data cannot erase a confirmed question or frozen version.
- M0 does not gain hidden cross-thread memory or a second business database.
- Future framework or codec upgrades must preserve active profile/graph routes or
  use an explicit continuity reset; they cannot silently resume old Checkpoints.
