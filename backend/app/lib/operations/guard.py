"""Process-level protection for the single business-operation consumer."""

from __future__ import annotations

from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from typing import Iterator
import fcntl

from sqlalchemy import text
from sqlalchemy.engine import Engine, make_url

from app.lib.database import engine as business_engine


class WorkerLockError(RuntimeError):
    """The Worker cannot safely become the business-operation consumer."""


class WorkerAlreadyRunning(WorkerLockError):
    """Another long-running Worker already owns the business database lock."""


_ADVISORY_LOCK_KEY = int.from_bytes(
    sha256(b"skill-eval-platform:operation-worker").digest()[:8],
    byteorder="big",
    signed=True,
)


def _sqlite_lock_path(database_engine: Engine) -> Path | None:
    database = make_url(str(database_engine.url)).database
    if not database or database == ":memory:":
        return None
    return Path(database).expanduser().resolve().with_name(
        f".{Path(database).name}.operation-worker.lock"
    )


@contextmanager
def worker_process_lock(database_engine: Engine | None = None) -> Iterator[None]:
    """Hold one process-level consumer lock for the lifetime of a Worker.

    PostgreSQL uses a database-scoped advisory lock so separate processes and
    containers sharing the business database cannot consume in parallel.
    SQLite uses a local file lock for development. Direct run_once() calls
    remain available to isolated tests; the CLI and run_forever() use this
    guard.
    """

    target = database_engine if database_engine is not None else business_engine
    if target.dialect.name == "postgresql":
        connection = None
        try:
            connection = target.connect()
            acquired = bool(
                connection.execute(
                    text("SELECT pg_try_advisory_lock(:lock_key)"),
                    {"lock_key": _ADVISORY_LOCK_KEY},
                ).scalar()
            )
        except Exception:
            if connection is not None:
                connection.close()
            raise WorkerLockError("unable to acquire the business Worker lock") from None
        if not acquired:
            connection.close()
            raise WorkerAlreadyRunning("another Worker already owns the business database")
        try:
            yield
        finally:
            try:
                connection.execute(
                    text("SELECT pg_advisory_unlock(:lock_key)"),
                    {"lock_key": _ADVISORY_LOCK_KEY},
                )
            except Exception:
                pass
            connection.close()
        return

    if target.dialect.name != "sqlite":
        raise WorkerLockError("business database does not support a Worker process lock")

    lock_path = _sqlite_lock_path(target)
    if lock_path is None:
        yield
        return
    try:
        lock_file = lock_path.open("a+")
    except OSError:
        raise WorkerLockError("unable to open the local Worker lock") from None
    try:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise WorkerAlreadyRunning("another Worker already owns the local database") from None
        except OSError:
            raise WorkerLockError("unable to acquire the local Worker lock") from None
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    finally:
        lock_file.close()
