from __future__ import annotations

import argparse
import time
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, field
from threading import Event, Thread
from typing import Any, Iterator
from uuid import uuid4

from app.lib.operations import repository
from app.lib.operations.repository import OPERATION_KINDS
from app.lib.settings import settings


class SupersededOperation(Exception):
    pass


class RetryableOperation(Exception):
    pass


class ProjectionPendingOperation(Exception):
    def __init__(
        self,
        message: str = "业务投影尚未提交。",
        *,
        produced_checkpoint_id: str | None = None,
        result_hash: str | None = None,
    ) -> None:
        super().__init__(message)
        self.produced_checkpoint_id = produced_checkpoint_id
        self.result_hash = result_hash


Handler = Callable[[repository.OperationJob], dict[str, Any] | None]


@dataclass
class OperationWorker:
    worker_id: str = field(default_factory=lambda: f"worker-{uuid4()}")
    handlers: dict[str, Handler] = field(default_factory=dict)

    def register(self, kind: str, handler: Handler) -> None:
        self.handlers[kind] = handler

    def _start_lease_heartbeat(self, job: repository.OperationJob) -> tuple[Event, Thread]:
        stop = Event()
        interval = max(0.1, min(30.0, float(settings.operation_lease_seconds) / 3.0))

        def keep_lease_alive() -> None:
            while not stop.wait(interval):
                try:
                    repository.renew(job.id, self.worker_id)
                except (KeyError, ValueError):
                    # Ownership was lost or the job was finalized elsewhere;
                    # the final commit remains the authoritative boundary.
                    return
                except Exception:
                    # A transient database blip must not stop heartbeats for
                    # the remainder of a long model call.
                    continue

        thread = Thread(
            target=keep_lease_alive,
            name=f"operation-lease-{job.id[:8]}",
            daemon=True,
        )
        thread.start()
        return stop, thread

    def run_once(self) -> repository.OperationJob | None:
        repository.release_expired()
        job = repository.claim_next(self.worker_id)
        if job is None:
            return None
        handler = self.handlers.get(job.kind)
        if handler is None:
            return repository.fail(
                job.id,
                self.worker_id,
                {"code": "UNSUPPORTED_OPERATION", "message": "没有可用的操作处理器。"},
                retryable=False,
            )
        lease_stop, lease_thread = self._start_lease_heartbeat(job)
        try:
            try:
                result = handler(job) or {}
            except SupersededOperation as exc:
                return repository.supersede(job.id, self.worker_id, str(exc))
            except RetryableOperation as exc:
                return repository.fail(
                    job.id,
                    self.worker_id,
                    {"code": "OPERATION_RETRYABLE", "message": str(exc)},
                    retryable=True,
                )
            except ProjectionPendingOperation as exc:
                return repository.mark_projection_pending(
                    job.id,
                    self.worker_id,
                    produced_checkpoint_id=exc.produced_checkpoint_id,
                    result_hash=exc.result_hash,
                )
            except Exception:
                return repository.fail(
                    job.id,
                    self.worker_id,
                    {"code": "OPERATION_FAILED", "message": "后台操作未能完成。"},
                    retryable=False,
                )
            return repository.complete(job.id, self.worker_id, result)
        finally:
            lease_stop.set()
            lease_thread.join(timeout=max(1.0, min(5.0, float(settings.operation_lease_seconds) / 3.0)))

    def run_forever(self, poll_seconds: float = 1.0) -> None:
        while True:
            try:
                result = self.run_once()
            except Exception:
                # Keep one bad operation from killing the sole consumer. The
                # operation's own state/error record remains the retry source.
                time.sleep(poll_seconds)
                continue
            if result is None:
                time.sleep(poll_seconds)


def _build_worker() -> OperationWorker:
    from app.features.case_builder.cocreation_service import (
        complete_batch_analysis,
        handle_cocreation_reproject,
        handle_cocreation_resume,
        handle_cocreation_start,
    )
    from app.features.evaluation_sets.service import handle_coverage_review, handle_freeze

    worker = OperationWorker()
    worker.register("batch_analysis", lambda job: complete_batch_analysis(job))
    worker.register("cocreation_start", lambda job: handle_cocreation_start(job))
    worker.register("cocreation_resume", lambda job: handle_cocreation_resume(job))
    worker.register("cocreation_reproject", lambda job: handle_cocreation_reproject(job))
    worker.register("coverage_review", lambda job: handle_coverage_review(job))
    worker.register("freeze_package", lambda job: handle_freeze(job))
    return worker


def default_worker() -> OperationWorker:
    """Build the deterministic Worker used by tests and explicit fake runs."""

    from app.lib.ai_runtime import initialize_ai_runtime

    initialize_ai_runtime()
    return _build_worker()


@contextmanager
def production_worker() -> Iterator[OperationWorker]:
    """Build a real-provider Worker while retaining its DB connection lifetime."""

    from app.lib.ai_runtime import get_adapters, initialize_ai_runtime, set_adapters
    from app.lib.ai_runtime.adapters import production_adapters
    from app.lib.ai_runtime.checkpoint import open_postgres_checkpointer
    from app.lib.ai_runtime.model import build_runtime_model

    model, identity = build_runtime_model()
    previous_adapters = get_adapters()
    try:
        with open_postgres_checkpointer() as checkpointer:
            initialize_ai_runtime(identity.registration_key)
            set_adapters(
                production_adapters(
                    checkpointer,
                    model=model,
                    model_spec=identity.registration_key,
                )
            )
            yield _build_worker()
    finally:
        set_adapters(previous_adapters)


def fake_worker() -> OperationWorker:
    """Build a deterministic worker for contract and recovery tests."""

    worker = OperationWorker(worker_id="fake-worker")
    for kind in OPERATION_KINDS:
        worker.register(kind, lambda job, operation_kind=kind: {"kind": operation_kind, "target_id": job.target_id})
    return worker


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the single M0 operation consumer.")
    parser.add_argument("--once", action="store_true", help="Claim and process at most one operation.")
    parser.add_argument("--fake", action="store_true", help="Use deterministic adapters for explicit local runs.")
    return parser.parse_args()


if __name__ == "__main__":
    import sys

    from app.lib.ai_runtime.checkpoint import CheckpointError
    from app.lib.ai_runtime.model import ModelConfigurationError
    from app.lib.settings import settings

    args = _parse_args()
    try:
        if args.fake or settings.ai_runtime_mode == "fake":
            worker = default_worker()
            if args.once:
                result = worker.run_once()
                print(result.status.value if result else "idle")
            else:
                worker.run_forever()
        elif settings.ai_runtime_mode == "production":
            with production_worker() as worker:
                if args.once:
                    result = worker.run_once()
                    print(result.status.value if result else "idle")
                else:
                    worker.run_forever()
        else:
            raise ModelConfigurationError("AI_RUNTIME_MODE must be production or fake")
    except (CheckpointError, ModelConfigurationError) as exc:
        print(f"Worker startup failed: {exc}", file=sys.stderr)
        raise SystemExit(2) from None
    except Exception as exc:
        # Startup and dependency failures must not render provider SDK details,
        # DSNs, or exception tracebacks in the worker terminal.
        print(f"Worker startup failed: {type(exc).__name__}", file=sys.stderr)
        raise SystemExit(2) from None
