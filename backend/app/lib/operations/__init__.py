from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

from app.lib.operations.repository import (
    OperationJob,
    OperationJobStatus,
    OPERATION_KINDS,
    claim_next,
    complete,
    complete_if_current,
    create_or_get,
    fail,
    get,
    list_for_target,
    release_expired,
    renew,
    supersede,
)
from app.lib.operations import attempts

if TYPE_CHECKING:
    from app.lib.operations.worker import OperationWorker, ProjectionPendingOperation, fake_worker


_LAZY_WORKER_EXPORTS = frozenset({"OperationWorker", "ProjectionPendingOperation", "fake_worker"})


def __getattr__(name: str):
    if name not in _LAZY_WORKER_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    worker_module = import_module(f"{__name__}.worker")
    value = getattr(worker_module, name)
    globals()[name] = value
    return value

__all__ = [
    "OperationJob",
    "OperationJobStatus",
    "OPERATION_KINDS",
    "claim_next",
    "complete",
    "complete_if_current",
    "create_or_get",
    "fail",
    "get",
    "list_for_target",
    "release_expired",
    "renew",
    "supersede",
    "OperationWorker",
    "ProjectionPendingOperation",
    "fake_worker",
    "attempts",
]
