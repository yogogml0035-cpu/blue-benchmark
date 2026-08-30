# M0 Development Environment Contract

Date: 2026-08-30

## Local services

- PostgreSQL: 17, one local container is sufficient for development.
- Business schema and LangGraph Checkpointer schema may share the instance but
  use separate connection settings, migrations, roles, and ownership.
- Backend: FastAPI process.
- Worker: one explicit single-consumer process; it is not started inside the
  web process.
- Frontend: Next.js development server.
- Storage: repository-local `storage/` with uploads, evidence, versions, and
  staging subdirectories; all storage content is Git-ignored.

## Required settings

Only placeholder names belong in tracked configuration:

```text
DATABASE_URL
CHECKPOINT_DATABASE_URL
CHECKPOINT_AES_KEY
STORAGE_ROOT
OPERATION_LEASE_SECONDS
OPERATION_MAX_ATTEMPTS
AI_MODEL_PROVIDER
AI_MODEL_ID
ANTHROPIC_BASE_URL
ANTHROPIC_AUTH_TOKEN
```

The implementation may reuse the same local PostgreSQL instance, but the two
URL variables remain distinct so production roles and migrations cannot be
silently collapsed. `CHECKPOINT_AES_KEY` must be 16, 24, or 32 bytes for the
locked encrypted serializer. No actual URL, password, relay URL, or token is
stored in this document or `.env.example`.

## Migration and startup order

1. Start PostgreSQL.
2. Run business migrations.
3. Run the separate Checkpointer setup/migration command.
4. Verify both schemas are ready.
5. Start FastAPI.
6. Start the single operation consumer.
7. Start Next.js.

Normal API/Worker startup verifies schemas and fails closed; it does not create
or mutate database schema automatically.

## Success and failure markers

- Database: readiness command accepts connections.
- Business migration: command exits 0 and reports current head.
- Checkpointer migration: command exits 0; a synthetic encrypted write/read and
  thread delete pass.
- API: health route identifies this checkout, not just any HTTP 200.
- Worker: startup logs the supported operation kinds and verified Agent tool
  surfaces without payloads or credentials.
- Frontend: page title and route identify this checkout; production build has no
  Preview fixtures.

## Stable local samples

`.local-samples/m0/` is Git-ignored and currently contains the three approved
M0 source files copied with no-overwrite semantics. Real-sample acceptance must
be an explicit opt-in command; default tests never discover or read this path.

## Verified prerequisites

- Python 3.13.15 and uv 0.12.5.
- Node/pnpm already used by the current frontend lockfile.
- Docker Engine 29.7.2 and Compose 5.4.0.
- PostgreSQL 17 temporary container passed the Checkpointer Spike.
- Host `psql` is not installed; container `pg_isready`/`psql` or Python
  `psycopg` commands must be used in the documented local workflow.
