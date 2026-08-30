from __future__ import annotations

from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from threading import Lock
from typing import AsyncIterator, Iterator
from uuid import uuid4

from pydantic import SecretStr
from sqlalchemy.engine import make_url

from app.lib.settings import settings


class CheckpointError(RuntimeError):
    pass


class CheckpointNotFound(CheckpointError):
    pass


class CheckpointIncompatible(CheckpointError):
    pass


_POSTGRES_TABLES = frozenset({"checkpoint_migrations", "checkpoints", "checkpoint_blobs", "checkpoint_writes"})


def _secret_text(value: object) -> str:
    if isinstance(value, SecretStr):
        return value.get_secret_value().strip()
    return str(value or "").strip()


def _database_identity(url: str) -> tuple[str, int, str] | None:
    """Return a driver-independent identity for PostgreSQL database separation."""

    try:
        parsed = make_url(url)
    except Exception:
        raise CheckpointError("CHECKPOINT_DATABASE_URL is not a valid PostgreSQL URL") from None
    if parsed.get_backend_name() != "postgresql":
        return None
    try:
        host = parsed.host
        port = parsed.port
    except Exception:
        raise CheckpointError("CHECKPOINT_DATABASE_URL is not a valid PostgreSQL URL") from None
    return (
        (host or "").lower(),
        port or 5432,
        parsed.database or "",
    )


def _psycopg_url(url: str) -> str:
    """Render a SQLAlchemy PostgreSQL URL in the scheme psycopg accepts."""

    identity = _database_identity(url)
    if identity is None:
        raise CheckpointError("CHECKPOINT_DATABASE_URL must use PostgreSQL")
    parsed = make_url(url)
    return parsed.set(drivername="postgresql").render_as_string(hide_password=False)


def _checkpoint_config(
    database_url: str | None = None,
    encryption_key: str | None = None,
) -> tuple[str, str]:
    raw_url = str(database_url or settings.checkpoint_database_url or "").strip()
    if not raw_url:
        raise CheckpointError("CHECKPOINT_DATABASE_URL is required for production co-creation")
    checkpoint_identity = _database_identity(raw_url)
    business_url = str(settings.database_url or "").strip()
    business_identity = _database_identity(business_url) if business_url else None
    if checkpoint_identity is None:
        raise CheckpointError("CHECKPOINT_DATABASE_URL must use PostgreSQL")
    if business_identity is not None and checkpoint_identity == business_identity:
        raise CheckpointError("CHECKPOINT_DATABASE_URL must be separate from DATABASE_URL")
    key = _secret_text(encryption_key if encryption_key is not None else settings.checkpoint_encryption_key)
    if not key:
        raise CheckpointError("LANGGRAPH_AES_KEY is required for production co-creation")
    if len(key.encode()) not in {16, 24, 32}:
        raise CheckpointError("checkpoint encryption key must be 16, 24, or 32 bytes")
    return _psycopg_url(raw_url), key


def _encrypted_serializer(key: str) -> object:
    """Create an encrypted serializer with an explicit application type allowlist."""

    from app.features.case_builder.cocreation_schemas import CoCreationAgentResult
    from langgraph.checkpoint.serde.encrypted import EncryptedSerializer
    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

    serde = JsonPlusSerializer(allowed_msgpack_modules=[CoCreationAgentResult])
    return EncryptedSerializer.from_pycryptodome_aes(serde=serde, key=key.encode())


def _assert_schema_ready(connection: object, *, required_version: int | None = None) -> None:
    try:
        rows = connection.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = current_schema() AND table_type = 'BASE TABLE'"
        ).fetchall()
        existing = {row["table_name"] for row in rows}
    except Exception:
        raise CheckpointError("unable to inspect Checkpointer schema") from None
    missing = _POSTGRES_TABLES - existing
    if missing:
        raise CheckpointError("Checkpointer schema is not ready; run make checkpoint-setup")
    if required_version is not None:
        try:
            row = connection.execute(
                "SELECT COALESCE(MAX(v), -1) AS version FROM checkpoint_migrations"
            ).fetchone()
            version = int(row["version"] if row else -1)
        except Exception:
            raise CheckpointError("unable to inspect Checkpointer schema") from None
        if version < required_version:
            raise CheckpointError("Checkpointer schema is not ready; run make checkpoint-setup")


@dataclass(frozen=True, slots=True)
class FakeCheckpoint:
    checkpoint_id: str
    thread_key: str
    result_json: dict


class FakeCheckpointStore:
    """Test-only checkpoint store; business rows still hold the accepted pointer."""

    def __init__(self) -> None:
        self._items: dict[str, FakeCheckpoint] = {}
        self._lock = Lock()

    def put(self, thread_key: str, result_json: dict) -> str:
        checkpoint_id = f"fake-cp-{uuid4()}"
        with self._lock:
            self._items[checkpoint_id] = FakeCheckpoint(checkpoint_id, thread_key, result_json)
        return checkpoint_id

    def get(self, checkpoint_id: str, thread_key: str) -> dict:
        with self._lock:
            item = self._items.get(checkpoint_id)
        if item is None or item.thread_key != thread_key:
            raise CheckpointNotFound("accepted checkpoint is missing or belongs to another thread")
        return dict(item.result_json)

    def delete_thread(self, thread_key: str) -> None:
        with self._lock:
            for checkpoint_id, item in list(self._items.items()):
                if item.thread_key == thread_key:
                    del self._items[checkpoint_id]


def explicit_checkpoint_config(thread_key: str, checkpoint_id: str | None = None) -> dict:
    if not thread_key or len(thread_key) >= 255:
        raise CheckpointError("stable thread key must be 1..254 characters")
    configurable = {"thread_id": thread_key}
    if checkpoint_id:
        configurable["checkpoint_id"] = checkpoint_id
    return {"configurable": configurable}


@asynccontextmanager
async def open_async_postgres_checkpointer(
    database_url: str | None = None,
    encryption_key: str | None = None,
) -> AsyncIterator[object]:
    """Open the production checkpointer; schema setup is an explicit deploy step."""

    url, key = _checkpoint_config(database_url, encryption_key)
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from psycopg import AsyncConnection
    from psycopg.rows import dict_row

    try:
        connection = await AsyncConnection.connect(
            url,
            autocommit=True,
            prepare_threshold=0,
            row_factory=dict_row,
        )
    except Exception:
        raise CheckpointError("unable to connect to Checkpointer database") from None
    try:
        saver = AsyncPostgresSaver(
            connection,
            serde=_encrypted_serializer(key),
        )
        yield saver
    finally:
        await connection.close()


@contextmanager
def open_postgres_checkpointer(
    database_url: str | None = None,
    encryption_key: str | None = None,
    *,
    require_schema: bool = True,
) -> Iterator[object]:
    """Open the synchronous encrypted saver used by the Operation Worker."""

    url, key = _checkpoint_config(database_url, encryption_key)
    from langgraph.checkpoint.postgres import PostgresSaver
    from psycopg import Connection
    from psycopg.rows import dict_row

    try:
        connection = Connection.connect(
            url,
            autocommit=True,
            prepare_threshold=0,
            row_factory=dict_row,
        )
    except Exception:
        raise CheckpointError("unable to connect to Checkpointer database") from None
    try:
        saver = PostgresSaver(
            connection,
            serde=_encrypted_serializer(key),
        )
        if require_schema:
            _assert_schema_ready(connection, required_version=len(PostgresSaver.MIGRATIONS) - 1)
        yield saver
    finally:
        connection.close()


async def setup_async_postgres_checkpointer(database_url: str | None = None, encryption_key: str | None = None) -> None:
    async with open_async_postgres_checkpointer(database_url, encryption_key) as saver:
        try:
            await saver.setup()
        except CheckpointError:
            raise
        except Exception:
            raise CheckpointError("Checkpointer schema setup failed") from None


def setup_checkpointer(database_url: str | None = None, encryption_key: str | None = None) -> None:
    with open_postgres_checkpointer(database_url, encryption_key, require_schema=False) as saver:
        try:
            saver.setup()
        except CheckpointError:
            raise
        except Exception:
            raise CheckpointError("Checkpointer schema setup failed") from None
