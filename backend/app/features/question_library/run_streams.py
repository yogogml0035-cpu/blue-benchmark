"""Durable run streams: thread registry, public event log and streaming reads.

Ownership: this module is the ONLY writer/reader of ``question_run_threads``
and ``question_run_events``. Events are persisted BEFORE they are handed to
any browser stream (SSE reads from the database, never from a process-local
queue), so a worker crash never loses content a teacher has already seen and
reconnects replay idempotently by sequence.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from app.lib.database import as_utc, session_scope
from app.lib.database.models import QuestionRunEventRow, QuestionRunThreadRow
from app.features.scenes.repository import new_id


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Thread registry
# ---------------------------------------------------------------------------

def generation_thread_id(question_id: str, materials_revision: int) -> str:
    """Stable thread identity per (question, materials revision).

    Technical retries reuse it so the checkpoint can resume; a confirmed
    regeneration bumps the revision and therefore starts a NEW thread.
    """
    return f"qgen-{question_id}-r{materials_revision}"


@dataclass(frozen=True)
class ThreadRegistration:
    thread_id: str
    question_id: str
    operation_id: str
    materials_revision: int
    materials_fingerprint: str
    runtime_fingerprint: str


def register_thread(registration: ThreadRegistration) -> ThreadRegistration:
    """Idempotently register the run thread inside the caller's flow.

    A conflicting fingerprint for the same thread means the materials changed
    without a revision bump — impossible through the CAS write path, so it is
    refused loudly instead of silently resuming on stale context.
    """
    now = _utc_now()
    with session_scope() as session:
        existing = session.execute(
            select(QuestionRunThreadRow).where(
                QuestionRunThreadRow.thread_id == registration.thread_id
            )
        ).scalar_one_or_none()
        if existing is not None:
            if existing.materials_fingerprint != registration.materials_fingerprint:
                raise ValueError("THREAD_MATERIALS_MISMATCH")
            return registration
        session.add(
            QuestionRunThreadRow(
                id=new_id(),
                question_id=registration.question_id,
                operation_id=registration.operation_id,
                thread_id=registration.thread_id,
                materials_revision=registration.materials_revision,
                materials_fingerprint=registration.materials_fingerprint,
                runtime_fingerprint=registration.runtime_fingerprint,
                created_at=now,
            )
        )
        try:
            session.flush()
        except IntegrityError:
            session.rollback()
            row = session.execute(
                select(QuestionRunThreadRow).where(
                    QuestionRunThreadRow.thread_id == registration.thread_id
                )
            ).scalar_one_or_none()
            if row is None or row.materials_fingerprint != registration.materials_fingerprint:
                raise ValueError("THREAD_MATERIALS_MISMATCH") from None
    return registration


def list_question_threads(question_id: str) -> list[str]:
    with session_scope() as session:
        rows = session.execute(
            select(QuestionRunThreadRow.thread_id).where(
                QuestionRunThreadRow.question_id == question_id
            )
        ).scalars().all()
    return list(rows)


# ---------------------------------------------------------------------------
# Public event log
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class StoredEvent:
    sequence: int
    kind: str
    stage: str | None
    text: str | None
    tool: str | None
    detail: str | None
    attempt: int
    created_at: str


def _row_to_event(row: QuestionRunEventRow) -> StoredEvent:
    return StoredEvent(
        sequence=row.sequence,
        kind=row.kind,
        stage=row.stage,
        text=row.text,
        tool=row.tool,
        detail=row.detail,
        attempt=row.attempt_number,
        created_at=as_utc(row.created_at).isoformat(),
    )


def read_events(
    question_id: str,
    operation_id: str,
    *,
    after_sequence: int = 0,
    limit: int = 500,
) -> list[StoredEvent]:
    """One page of the log, ordered by the per-operation monotonic sequence.

    The sequence is continuous across attempts, so a single cursor is enough
    for reconnects and pagination; ``attempt`` stays as an event attribute
    that marks which try produced each entry.
    """
    with session_scope() as session:
        statement = (
            select(QuestionRunEventRow)
            .where(
                QuestionRunEventRow.question_id == question_id,
                QuestionRunEventRow.operation_id == operation_id,
                QuestionRunEventRow.sequence > after_sequence,
            )
            .order_by(QuestionRunEventRow.sequence)
            .limit(min(max(limit, 1), 1000))
        )
        rows = session.execute(statement).scalars().all()
    return [_row_to_event(row) for row in rows]


def last_sequence(operation_id: str) -> int:
    with session_scope() as session:
        value = session.execute(
            select(func.max(QuestionRunEventRow.sequence)).where(
                QuestionRunEventRow.operation_id == operation_id,
            )
        ).scalar_one_or_none()
    return int(value or 0)


class PersistentEventSink:
    """Buffers adjacent message deltas and persists public events durably.

    Persistence happens in short transactional batches (never one row per
    token, never a process-local queue masquerading as a durable bridge).
    Ordering and content are preserved: deltas are merged, not dropped.
    """

    _MERGE_WINDOW_SECONDS = 0.4
    _MAX_BUFFERED_CHARS = 4_000

    def __init__(
        self,
        *,
        question_id: str,
        operation_id: str,
        attempt_number: int,
        thread_id: str,
    ) -> None:
        self.question_id = question_id
        self.operation_id = operation_id
        self.attempt_number = attempt_number
        self.thread_id = thread_id
        self._lock = threading.Lock()
        # Sequence is per-OPERATION and continuous across attempts: a retry
        # continues the log instead of restarting the cursor.
        self._sequence = last_sequence(operation_id)
        self._pending_text: list[str] = []
        self._pending_since = 0.0
        self._buffered_rows: list[tuple[str, str | None, str | None, str | None, str | None]] = []

    # -- public API ---------------------------------------------------------

    def emit(self, event: Any) -> None:
        """Accept a deep_runtime.PublicEvent and persist it (batched)."""
        with self._lock:
            if event.kind == "message_delta":
                now = time.monotonic()
                buffered = sum(len(t) for t in self._pending_text)
                if (
                    self._pending_text
                    and now - self._pending_since < self._MERGE_WINDOW_SECONDS
                    and buffered < self._MAX_BUFFERED_CHARS
                ):
                    self._pending_text.append(event.text or "")
                    return
                self._flush_pending_locked()
                self._pending_text = [event.text or ""]
                self._pending_since = now
                return
            self._flush_pending_locked()
            self._buffered_rows.append(
                (event.kind, event.stage, event.text, event.tool, event.detail)
            )
            self._flush_rows_locked()

    def close(self) -> None:
        with self._lock:
            self._flush_pending_locked()
            self._flush_rows_locked()

    # -- internals ----------------------------------------------------------

    def _flush_pending_locked(self) -> None:
        if self._pending_text:
            text = "".join(self._pending_text)
            if text:
                self._buffered_rows.append(("message_delta", None, text, None, None))
        self._pending_text = []

    def _flush_rows_locked(self) -> None:
        if not self._buffered_rows:
            return
        rows = self._buffered_rows
        self._buffered_rows = []
        now = _utc_now()
        with session_scope() as session:
            for kind, stage, text, tool, detail in rows:
                self._sequence += 1
                session.add(
                    QuestionRunEventRow(
                        id=new_id(),
                        question_id=self.question_id,
                        operation_id=self.operation_id,
                        thread_id=self.thread_id,
                        attempt_number=self.attempt_number,
                        sequence=self._sequence,
                        kind=kind[:32],
                        stage=stage[:120] if stage else None,
                        text=text,
                        tool=tool[:64] if tool else None,
                        detail=detail[:500] if detail else None,
                        created_at=now,
                    )
                )


def delete_question_run_rows(session, question_id: str) -> None:
    """Remove ALL run events and thread mappings inside a business transaction.

    Called only by the final deletion commit — after cross-store checkpoint
    cleanup succeeded — so the registry stays available as the cleanup's
    enumeration source until the very end.
    """
    session.execute(
        delete(QuestionRunEventRow).where(QuestionRunEventRow.question_id == question_id)
    )
    session.execute(
        delete(QuestionRunThreadRow).where(QuestionRunThreadRow.question_id == question_id)
    )
