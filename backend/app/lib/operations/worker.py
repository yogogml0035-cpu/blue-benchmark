from __future__ import annotations

import argparse
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from app.lib.operations import repository
from app.lib.operations.repository import OPERATION_KINDS


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

    def run_forever(self, poll_seconds: float = 1.0) -> None:
        while True:
            if self.run_once() is None:
                time.sleep(poll_seconds)


def default_worker() -> OperationWorker:
    from app.features.case_builder.cocreation_service import (
        complete_batch_analysis,
        handle_cocreation_reproject,
        handle_cocreation_resume,
        handle_cocreation_start,
        handle_coverage_review,
    )
    from app.lib.ai_runtime import initialize_ai_runtime

    initialize_ai_runtime()
    worker = OperationWorker()
    worker.register("batch_analysis", lambda job: complete_batch_analysis(job))
    worker.register("cocreation_start", lambda job: handle_cocreation_start(job))
    worker.register("cocreation_resume", lambda job: handle_cocreation_resume(job))
    worker.register("cocreation_reproject", lambda job: handle_cocreation_reproject(job))
    worker.register("coverage_review", lambda job: handle_coverage_review(job))
    return worker


def fake_worker() -> OperationWorker:
    """Build a deterministic worker for contract and recovery tests."""

    worker = OperationWorker(worker_id="fake-worker")
    for kind in OPERATION_KINDS:
        worker.register(kind, lambda job, operation_kind=kind: {"kind": operation_kind, "target_id": job.target_id})
    return worker


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the single M0 operation consumer.")
    parser.add_argument("--once", action="store_true", help="Claim and process at most one operation.")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    worker = default_worker()
    if args.once:
        result = worker.run_once()
        print(result.status.value if result else "idle")
    else:
        worker.run_forever()
