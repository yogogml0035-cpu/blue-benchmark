from __future__ import annotations

import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from threading import Event, Thread
from typing import Any
from uuid import uuid4

from app.lib.operations import repository
from app.lib.settings import settings


class SupersededOperation(Exception):
    pass


class RetryableOperation(Exception):
    pass


Handler = Callable[[repository.OperationJob], dict[str, Any] | None]


def _clean_error(error: dict[str, Any]) -> dict[str, Any]:
    return {
        "code": str(error.get("code") or "OPERATION_FAILED"),
        "message": str(error.get("message") or "")[:500],
    }


@dataclass
class OperationWorker:
    worker_id: str = field(default_factory=lambda: f"worker-{uuid4()}")
    runtime_mode: str = "fake"
    handlers: dict[str, Handler] = field(default_factory=dict)

    def register(self, kind: str, handler: Handler) -> None:
        self.handlers[kind] = handler

    def run_once(self) -> bool:
        _released, terminal_failures = repository.release_expired()
        for failed_job in terminal_failures:
            self._project_terminal_failure(failed_job)
        try:
            job = repository.claim_next(self.worker_id)
        except Exception:
            # A poisoned job row must never take the whole consumer down;
            # back off and let the next poll retry.
            return False
        if job is None:
            return False
        handler = self.handlers.get(job.kind)
        stop_heartbeat = Event()

        def _heartbeat() -> None:
            interval = max(0.1, min(settings.operation_lease_seconds / 3, 30))
            consecutive_failures = 0
            while not stop_heartbeat.wait(interval):
                try:
                    repository.renew(job.id, self.worker_id)
                    consecutive_failures = 0
                except Exception:
                    # A single transient failure (e.g. SQLite busy) must not
                    # drop the lease; only sustained failure stops renewing.
                    consecutive_failures += 1
                    if consecutive_failures >= 5:
                        return

        heartbeat = Thread(target=_heartbeat, daemon=True)
        heartbeat.start()
        try:
            if handler is None:
                repository.fail(
                    job.id,
                    self.worker_id,
                    {"code": "UNSUPPORTED_OPERATION", "message": f"未知任务类型：{job.kind}"},
                    retryable=False,
                )
                self._project_terminal_failure(repository.get(job.id))
                return True
            try:
                result = handler(job) or {}
                current = repository.get(job.id)
                if current is not None and current.status in (
                    repository.OperationJobStatus.succeeded,
                    repository.OperationJobStatus.superseded,
                    repository.OperationJobStatus.failed,
                ):
                    # The handler committed business data and the job's
                    # terminal state atomically; nothing left to complete.
                    return True
                result = dict(result)
                result["__worker_runtime_mode"] = self.runtime_mode
                try:
                    repository.complete_if_current(
                        job.id,
                        self.worker_id,
                        current_revision=job.business_revision,
                        result=result,
                    )
                except ValueError:
                    # Ownership was lost to a lease-expired duplicate; the
                    # fencing commit in the handler already decided the outcome.
                    pass
            except SupersededOperation as exc:
                try:
                    repository.supersede(job.id, self.worker_id, str(exc) or "业务版本已经更新。")
                except ValueError:
                    # Ownership already lost (lease-expired duplicate took over);
                    # the new owner decides the outcome.
                    pass
            except RetryableOperation as exc:
                try:
                    repository.fail(
                        job.id,
                        self.worker_id,
                        {"code": "OPERATION_RETRYABLE", "message": str(exc)[:500]},
                        retryable=True,
                    )
                except ValueError:
                    pass
            except Exception as exc:
                from app.features.question_library import rubric_generation
                from app.lib.ai_runtime.adapters import RubricGenerationFailure
                from app.lib.ai_runtime.deep_runtime import DeepRuntimeError

                known = isinstance(exc, (RubricGenerationFailure, DeepRuntimeError))
                retryable = bool(getattr(exc, "retryable", False)) if known else False
                if known:
                    error = {"code": exc.code, "message": exc.message}
                elif job.kind == "question_cleanup":
                    # Cleanup failures must never be projected as rubric
                    # generation failures.
                    error = {"code": "OPERATION_FAILED", "message": "题目删除清理失败。"}
                else:
                    error = {"code": "OPERATION_FAILED", "message": "评分维度生成失败。"}
                try:
                    updated = repository.fail(
                        job.id, self.worker_id, _clean_error(error), retryable=retryable
                    )
                except ValueError:
                    return True
                if (
                    updated.status == repository.OperationJobStatus.failed
                    and job.kind == "rubric_generation"
                ):
                    rubric_generation.mark_generation_failed(
                        job, _clean_error(error), worker_id=self.worker_id
                    )
        finally:
            stop_heartbeat.set()
            heartbeat.join(timeout=0.1)
        return True

    def _project_terminal_failure(self, job: repository.OperationJob | None) -> None:
        if job is None or job.status != repository.OperationJobStatus.failed:
            return
        if job.target_type == "eval_question":
            from app.features.question_library import rubric_generation

            rubric_generation.mark_generation_failed(
                job,
                job.last_error or {"code": "OPERATION_FAILED", "message": "评分维度生成失败。"},
                worker_id=self.worker_id,
            )

    def run_forever(self, poll_seconds: float = 1.0) -> None:
        from app.lib.operations.guard import worker_process_lock

        with worker_process_lock():
            while True:
                try:
                    if not self.run_once():
                        time.sleep(poll_seconds)
                except Exception:
                    time.sleep(poll_seconds)


def _build_worker(runtime_mode: str) -> OperationWorker:
    from app.features.question_library import deletion, rubric_generation

    worker = OperationWorker(runtime_mode=runtime_mode)
    worker.register("rubric_generation", rubric_generation.process_rubric_generation)
    worker.register("question_cleanup", deletion.process_question_cleanup)
    return worker


def default_worker() -> OperationWorker:
    """Fake-mode worker used by acceptance scripts and local development."""

    from app.lib.ai_runtime.model import ModelConfigurationError
    from app.lib.database import engine

    if engine.dialect.name != "sqlite":
        raise ModelConfigurationError("Fake worker requires the SQLite business database.")
    return _build_worker("fake")


@contextmanager
def production_worker() -> Iterator[OperationWorker]:
    """Install real AI adapters for the context lifetime, then restore them.

    The provider model is built LAZILY inside the deep-agent generator: a
    missing or broken provider configuration must fail only the generation
    jobs that need it, never block model-free jobs (deletion cleanup) or
    worker startup.
    """

    from app.lib.ai_runtime import adapters as adapter_module

    previous = adapter_module.get_adapters()
    adapter_module.set_adapters(adapter_module.production_adapters())
    try:
        yield _build_worker("production")
    finally:
        adapter_module.set_adapters(previous)


def fake_worker() -> OperationWorker:
    worker = OperationWorker(runtime_mode="fake")

    def _noop(job: repository.OperationJob) -> dict[str, Any]:
        return {"kind": job.kind, "target_id": job.target_id}

    for kind in repository.OPERATION_KINDS:
        worker.register(kind, _noop)
    return worker


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "--help" in args or "-h" in args:
        print("usage: python -m app.lib.operations.worker [--once] [--fake]")
        return 0
    once = "--once" in args
    fake = "--fake" in args or settings.ai_runtime_mode == "fake"
    try:
        if fake:
            worker = default_worker()
            if once:
                worker.run_once()
            else:
                worker.run_forever()
        else:
            with production_worker() as production:
                if once:
                    production.run_once()
                else:
                    production.run_forever()
    except Exception:
        print("worker failed to start; check AI and database configuration", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
