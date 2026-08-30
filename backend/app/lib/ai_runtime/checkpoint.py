from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator
from uuid import uuid4

from app.lib.settings import settings


class CheckpointError(RuntimeError):
    pass


class CheckpointNotFound(CheckpointError):
    pass


@dataclass(frozen=True, slots=True)
class FakeCheckpoint:
    checkpoint_id: str
    thread_key: str
    result_json: dict


class FakeCheckpointStore:
    """Test-only checkpoint store; business rows still hold the accepted pointer."""

    def __init__(self) -> None:
        self._items: dict[str, FakeCheckpoint] = {}
        self._lock = asyncio.Lock()

    def put(self, thread_key: str, result_json: dict) -> str:
        checkpoint_id = f"fake-cp-{uuid4()}"
        self._items[checkpoint_id] = FakeCheckpoint(checkpoint_id, thread_key, result_json)
        return checkpoint_id

    def get(self, checkpoint_id: str, thread_key: str) -> dict:
        item = self._items.get(checkpoint_id)
        if item is None or item.thread_key != thread_key:
            raise CheckpointNotFound("accepted checkpoint is missing or belongs to another thread")
        return dict(item.result_json)

    def delete_thread(self, thread_key: str) -> None:
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

    url = database_url or settings.checkpoint_database_url
    if not url:
        raise CheckpointError("CHECKPOINT_DATABASE_URL is required for production co-creation")
    key = encryption_key or settings.checkpoint_encryption_key
    if not key:
        raise CheckpointError("LANGGRAPH_AES_KEY is required for production co-creation")
    if len(key.encode()) not in {16, 24, 32}:
        raise CheckpointError("checkpoint encryption key must be 16, 24, or 32 bytes")
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from langgraph.checkpoint.serde.encrypted import EncryptedSerializer
    from psycopg import AsyncConnection

    connection = await AsyncConnection.connect(url, autocommit=True)
    saver = AsyncPostgresSaver(
        connection,
        serde=EncryptedSerializer.from_pycryptodome_aes(key=key.encode()),
    )
    try:
        yield saver
    finally:
        await connection.close()


async def setup_async_postgres_checkpointer(database_url: str | None = None, encryption_key: str | None = None) -> None:
    async with open_async_postgres_checkpointer(database_url, encryption_key) as saver:
        await saver.setup()


def setup_checkpointer(database_url: str | None = None, encryption_key: str | None = None) -> None:
    asyncio.run(setup_async_postgres_checkpointer(database_url, encryption_key))
