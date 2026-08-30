from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import subprocess
import sys
import time

import pytest

from app.lib.ai_runtime import get_adapters, reset_adapters
from app.lib.ai_runtime.checkpoint import (
    CheckpointError,
    _assert_schema_ready,
    _checkpoint_config,
)
from app.lib.ai_runtime.model import RuntimeModelIdentity
from app.lib.operations import worker as worker_module
from app.lib.settings import settings


class _FakeConnection:
    def __init__(self, table_names: set[str], migration_version: int = 9) -> None:
        self.table_names = table_names
        self.migration_version = migration_version
        self.closed = False

    def execute(self, query: str):
        return _FakeResult(self.table_names, self.migration_version, query)

    def close(self) -> None:
        self.closed = True


class _FakeResult:
    def __init__(self, table_names: set[str], migration_version: int, query: str) -> None:
        self.table_names = table_names
        self.migration_version = migration_version
        self.query = query

    def fetchall(self) -> list[dict[str, str]]:
        return [{"table_name": name} for name in self.table_names]

    def fetchone(self) -> dict[str, int] | None:
        if "COALESCE(MAX(v)" not in self.query:
            return None
        return {"version": self.migration_version}


def test_checkpointer_url_accepts_sqlalchemy_driver_but_renders_psycopg_scheme(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "database_url", "sqlite:///business.db")

    url, key = _checkpoint_config(
        "postgresql+psycopg://checkpoint:secret@db.example:5432/checkpoints",
        "1234567890123456",
    )

    assert url == "postgresql://checkpoint:secret@db.example:5432/checkpoints"
    assert key == "1234567890123456"


def test_checkpointer_rejects_same_postgres_database_even_when_driver_scheme_differs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "database_url", "postgresql+psycopg://business:secret@db.example:5432/app")

    with pytest.raises(CheckpointError, match="separate"):
        _checkpoint_config("postgresql://checkpoint:secret@db.example:5432/app", "1234567890123456")


def test_checkpointer_readiness_requires_all_langgraph_tables() -> None:
    connection = _FakeConnection({"checkpoint_migrations", "checkpoints"})

    with pytest.raises(CheckpointError, match="schema is not ready"):
        _assert_schema_ready(connection)


def test_checkpointer_readiness_rejects_old_migration_version() -> None:
    connection = _FakeConnection(
        {"checkpoint_migrations", "checkpoints", "checkpoint_blobs", "checkpoint_writes"},
        migration_version=8,
    )

    with pytest.raises(CheckpointError, match="schema is not ready"):
        _assert_schema_ready(connection, required_version=9)


def test_sync_checkpointer_uses_encrypted_saver_and_closes_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    from psycopg import Connection
    from psycopg.rows import dict_row

    connection = _FakeConnection(
        {"checkpoint_migrations", "checkpoints", "checkpoint_blobs", "checkpoint_writes"},
    )
    connect_args: dict[str, object] = {}

    def fake_connect(*args, **kwargs):
        connect_args.update(kwargs)
        assert args[0] == "postgresql://checkpoint:secret@db.example:5432/checkpoints"
        return connection

    monkeypatch.setattr(Connection, "connect", fake_connect)
    monkeypatch.setattr(settings, "database_url", "sqlite:///business.db")

    from app.lib.ai_runtime.checkpoint import open_postgres_checkpointer

    with open_postgres_checkpointer(
        "postgresql://checkpoint:secret@db.example:5432/checkpoints",
        "1234567890123456",
    ) as saver:
        assert saver.__class__.__name__ == "PostgresSaver"
        assert saver.serde.__class__.__name__ == "EncryptedSerializer"
        assert (
            "CoCreationAgentResult"
            in repr(getattr(saver.serde.serde, "_allowed_msgpack_modules", None))
        )

    assert connect_args["autocommit"] is True
    assert connect_args["prepare_threshold"] == 0
    assert connect_args["row_factory"] is dict_row
    assert connection.closed is True


def test_production_worker_installs_real_adapters_for_context_lifetime(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_adapters()
    previous = get_adapters()
    events: list[str] = []
    fake_model = object()
    identity = RuntimeModelIdentity(provider="openai", model="test-model", base_url=None)

    def fake_build_runtime_model():
        events.append("model")
        return fake_model, identity

    monkeypatch.setattr("app.lib.ai_runtime.model.build_runtime_model", fake_build_runtime_model)
    monkeypatch.setattr("app.lib.ai_runtime.adapters._assert_production_tool_surfaces", lambda *_args: None)

    @contextmanager
    def fake_checkpointer():
        events.append("enter")
        yield object()
        events.append("exit")

    monkeypatch.setattr("app.lib.ai_runtime.checkpoint.open_postgres_checkpointer", fake_checkpointer)

    with worker_module.production_worker() as worker:
        events.append("yield")
        adapters = get_adapters()
        assert isinstance(worker, worker_module.OperationWorker)
        assert adapters.evidence_analyzer._runtime_model is fake_model
        assert adapters.standard_cocreator._runtime_model is fake_model
        assert adapters.coverage_reviewer._runtime_model is fake_model
        assert adapters.standard_cocreator.checkpointer is not None

    assert events == ["model", "enter", "yield", "exit"]
    assert get_adapters() is previous


def test_production_worker_build_failure_happens_before_any_operation_claim(monkeypatch: pytest.MonkeyPatch) -> None:
    claimed = False

    def fail_build():
        raise RuntimeError("invalid model")

    def unexpected_claim(*_args, **_kwargs):
        nonlocal claimed
        claimed = True
        return None

    monkeypatch.setattr("app.lib.ai_runtime.model.build_runtime_model", fail_build)
    monkeypatch.setattr("app.lib.operations.repository.claim_next", unexpected_claim)

    with pytest.raises(RuntimeError, match="invalid model"):
        with worker_module.production_worker():
            pytest.fail("production worker should not yield after model failure")

    assert claimed is False


def test_production_worker_checkpointer_failure_happens_before_any_operation_claim(monkeypatch: pytest.MonkeyPatch) -> None:
    claimed = False
    fake_model = object()
    identity = RuntimeModelIdentity(provider="openai", model="test-model", base_url=None)

    monkeypatch.setattr("app.lib.ai_runtime.model.build_runtime_model", lambda: (fake_model, identity))

    @contextmanager
    def fail_checkpointer():
        raise CheckpointError("Checkpointer schema is not ready")
        yield

    def unexpected_claim(*_args, **_kwargs):
        nonlocal claimed
        claimed = True
        return None

    monkeypatch.setattr("app.lib.ai_runtime.checkpoint.open_postgres_checkpointer", fail_checkpointer)
    monkeypatch.setattr("app.lib.operations.repository.claim_next", unexpected_claim)

    with pytest.raises(CheckpointError, match="schema is not ready"):
        with worker_module.production_worker():
            pytest.fail("production worker should not yield after Checkpointer failure")

    assert claimed is False


def test_worker_module_help_does_not_emit_runpy_warning() -> None:
    backend_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-m", "app.lib.operations.worker", "--help"],
        cwd=backend_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "RuntimeWarning" not in result.stderr
    assert "runpy" not in result.stderr


def test_worker_renews_a_long_running_operation_lease(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    job = SimpleNamespace(id="long-running-job", kind="batch_analysis")
    renewed: list[tuple[str, str]] = []
    completed = object()

    monkeypatch.setattr(worker_module.repository, "release_expired", lambda: 0)
    monkeypatch.setattr(worker_module.repository, "claim_next", lambda _worker_id: job)
    monkeypatch.setattr(
        worker_module.repository,
        "renew",
        lambda job_id, worker_id: renewed.append((job_id, worker_id)),
    )
    monkeypatch.setattr(worker_module.repository, "complete", lambda *_args: completed)
    monkeypatch.setattr(worker_module.settings, "operation_lease_seconds", 1)

    worker = worker_module.OperationWorker(worker_id="heartbeat-worker")
    worker.register("batch_analysis", lambda _job: (time.sleep(0.45), {})[1])

    assert worker.run_once() is completed
    assert renewed == [("long-running-job", "heartbeat-worker")]
