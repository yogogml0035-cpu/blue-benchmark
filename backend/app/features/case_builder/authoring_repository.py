"""Database ownership for the user-visible authoring conversation.

This module stores only business projections.  Agent checkpoints and raw model
events remain outside the HTTP-facing aggregate.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from typing import Any
from uuid import uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from app.features.case_builder.authoring_schemas import (
    AuthoringConversationStatus,
    AuthoringEventKind,
    AuthoringMessageRole,
    AuthoringMessageType,
    QuestionDraftStatus,
)
from app.lib.database import as_utc, session_scope
from app.lib.database.models import (
    AuthoringConversationRow,
    AuthoringMessageRow,
    BenchmarkQuestionDraftRow,
    OperationJobRow,
    SafeStreamEventRow,
)


class RepositoryConflict(RuntimeError):
    pass


class StaleProjection(RepositoryConflict):
    pass


@dataclass(frozen=True, slots=True)
class AuthoringConversationRecord:
    id: str
    workspace_id: str
    upload_batch_id: str | None
    title: str
    task_instruction: str | None
    source_file_ids: list[str]
    command_id: str
    command_payload_hash: str
    status: str
    revision: int
    active_operation_id: str | None
    pending_question: dict[str, Any] | None
    command_receipts: dict[str, Any]
    created_by: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class AuthoringMessageRecord:
    id: str
    conversation_id: str
    sequence: int
    role: str
    message_type: str
    content: str
    attachment_ids: list[str]
    question_draft_id: str | None
    command_id: str | None
    verified: bool
    created_at: datetime


@dataclass(frozen=True, slots=True)
class QuestionDraftRecord:
    id: str
    conversation_id: str
    title: str
    summary: str
    status: str
    revision: int
    input: dict[str, Any]
    reference_answer_text: str | None
    reference_answer_source: str | None
    evidence_file_ids: list[str]
    source_refs: list[dict[str, Any]]
    question_checkpoint_id: str | None
    question_question_count: int
    question_input_revision: int | None
    question_prompt_sequence: int | None
    confirmed_revision: int | None
    confirmed_hash: str | None
    confirmed_by: str | None
    confirmed_at: datetime | None
    last_confirmation_command_id: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class SafeStreamEventRecord:
    sequence: int
    conversation_id: str
    kind: str
    payload: dict[str, Any]
    created_at: datetime


def now() -> datetime:
    return datetime.now(timezone.utc)


def payload_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _conversation(row: AuthoringConversationRow) -> AuthoringConversationRecord:
    return AuthoringConversationRecord(
        id=row.id,
        workspace_id=row.workspace_id,
        upload_batch_id=row.upload_batch_id,
        title=row.title,
        task_instruction=row.task_instruction,
        source_file_ids=list(row.source_file_ids_json or []),
        command_id=row.command_id,
        command_payload_hash=row.command_payload_hash,
        status=row.status,
        revision=row.revision,
        active_operation_id=row.active_operation_id,
        pending_question=dict(row.pending_question_json) if row.pending_question_json else None,
        command_receipts=dict(row.command_receipts_json or {}),
        created_by=row.created_by,
        created_at=as_utc(row.created_at),
        updated_at=as_utc(row.updated_at),
    )


def _message(row: AuthoringMessageRow) -> AuthoringMessageRecord:
    return AuthoringMessageRecord(
        id=row.id,
        conversation_id=row.conversation_id,
        sequence=row.sequence,
        role=row.role,
        message_type=row.message_type,
        content=row.content_text,
        attachment_ids=list(row.attachment_ids_json or []),
        question_draft_id=row.question_draft_id,
        command_id=row.command_id,
        verified=bool(row.verified),
        created_at=as_utc(row.created_at),
    )


def _draft(row: BenchmarkQuestionDraftRow) -> QuestionDraftRecord:
    return QuestionDraftRecord(
        id=row.id,
        conversation_id=row.conversation_id,
        title=row.title,
        summary=row.summary,
        status=row.status,
        revision=row.revision,
        input=dict(row.input_json or {}),
        reference_answer_text=row.reference_answer_text,
        reference_answer_source=row.reference_answer_source,
        evidence_file_ids=list(row.evidence_file_ids_json or []),
        source_refs=[dict(item) for item in (row.source_refs_json or []) if isinstance(item, dict)],
        question_checkpoint_id=row.question_checkpoint_id,
        question_question_count=int(row.question_question_count or 0),
        question_input_revision=row.question_input_revision,
        question_prompt_sequence=row.question_prompt_sequence,
        confirmed_revision=row.confirmed_revision,
        confirmed_hash=row.confirmed_hash,
        confirmed_by=row.confirmed_by,
        confirmed_at=as_utc(row.confirmed_at) if row.confirmed_at else None,
        last_confirmation_command_id=row.last_confirmation_command_id,
        created_at=as_utc(row.created_at),
        updated_at=as_utc(row.updated_at),
    )


def _event(row: SafeStreamEventRow) -> SafeStreamEventRecord:
    return SafeStreamEventRecord(
        sequence=row.sequence,
        conversation_id=row.conversation_id,
        kind=row.kind,
        payload=dict(row.payload_json or {}),
        created_at=as_utc(row.created_at),
    )


_EVENT_KEYS: dict[str, frozenset[str]] = {
    AuthoringEventKind.phase_started.value: frozenset({"phase", "label"}),
    AuthoringEventKind.phase_completed.value: frozenset({"phase", "label"}),
    AuthoringEventKind.action_summary.value: frozenset({"label", "count", "status"}),
    AuthoringEventKind.public_message_ready.value: frozenset({"text"}),
    AuthoringEventKind.snapshot_changed.value: frozenset({"revision", "status", "draft_count"}),
    AuthoringEventKind.waiting_for_teacher.value: frozenset({"text", "reason", "gap_type"}),
    AuthoringEventKind.failed.value: frozenset({"code", "message"}),
    AuthoringEventKind.completed.value: frozenset({"draft_count", "confirmed_count"}),
}
_SAFE_EVENT_RETENTION = 500
_FORBIDDEN_EVENT_TERMS = (
    "content_text",
    "storage_key",
    "absolute_path",
    "system_prompt",
    "private_reasoning",
    "checkpoint",
    "thread_id",
    "thread_key",
    "interrupt",
    "credential",
    "password",
    "api_key",
    "api key",
    "access token",
    "secret",
    "raw_token",
    "tool_args",
    "tool_result",
    "parsed_text",
    "private",
    "reasoning",
    "raw_output",
    "tool_call",
    "密码",
    "凭证",
    "访问令牌",
    "系统提示",
    "私有推理",
    "绝对路径",
    "存储键",
    "线程标识",
)


def _validate_safe_event(kind: str, payload: dict[str, Any]) -> None:
    allowed = _EVENT_KEYS.get(kind)
    if allowed is None:
        raise ValueError("unsupported safe stream event")
    if set(payload) - set(allowed):
        raise ValueError("safe stream event contains a non-public field")
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > 8_000:
        raise ValueError("safe stream event is too large")
    stack: list[Any] = [payload]
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            stack.extend(value.keys())
            stack.extend(value.values())
            continue
        if isinstance(value, (list, tuple)):
            stack.extend(value)
            continue
        if not isinstance(value, str):
            continue
        folded = value.casefold()
        if any(term in folded for term in _FORBIDDEN_EVENT_TERMS):
            raise ValueError("safe stream event contains an internal field")
        if value.startswith(("/", "\\")) or "file://" in folded:
            raise ValueError("safe stream event contains a host path")


def get_conversation(conversation_id: str) -> AuthoringConversationRecord | None:
    with session_scope() as session:
        row = session.get(AuthoringConversationRow, conversation_id)
        return _conversation(row) if row else None


def get_conversation_by_command(workspace_id: str, command_id: str) -> AuthoringConversationRecord | None:
    with session_scope() as session:
        row = session.scalar(
            select(AuthoringConversationRow).where(
                AuthoringConversationRow.workspace_id == workspace_id,
                AuthoringConversationRow.command_id == command_id,
            )
        )
        return _conversation(row) if row else None


def get_message_by_command(conversation_id: str, command_id: str) -> AuthoringMessageRecord | None:
    with session_scope() as session:
        row = session.scalar(
            select(AuthoringMessageRow).where(
                AuthoringMessageRow.conversation_id == conversation_id,
                AuthoringMessageRow.command_id == command_id,
            )
        )
        return _message(row) if row else None


def get_message_by_global_command(command_id: str) -> AuthoringMessageRecord | None:
    """Look up a teacher command without narrowing it to one conversation."""

    with session_scope() as session:
        row = session.scalar(
            select(AuthoringMessageRow).where(AuthoringMessageRow.command_id == command_id)
        )
        return _message(row) if row else None


def list_messages(conversation_id: str) -> list[AuthoringMessageRecord]:
    with session_scope() as session:
        rows = session.scalars(
            select(AuthoringMessageRow)
            .where(AuthoringMessageRow.conversation_id == conversation_id)
            .order_by(AuthoringMessageRow.sequence, AuthoringMessageRow.id)
        ).all()
        return [_message(row) for row in rows]


def list_drafts(conversation_id: str, *, include_discarded: bool = True) -> list[QuestionDraftRecord]:
    with session_scope() as session:
        statement = select(BenchmarkQuestionDraftRow).where(
            BenchmarkQuestionDraftRow.conversation_id == conversation_id
        )
        if not include_discarded:
            statement = statement.where(BenchmarkQuestionDraftRow.status != QuestionDraftStatus.discarded.value)
        rows = session.scalars(
            statement.order_by(BenchmarkQuestionDraftRow.created_at, BenchmarkQuestionDraftRow.id)
        ).all()
        return [_draft(row) for row in rows]


def list_events(conversation_id: str, after: int = 0, limit: int = 100) -> list[SafeStreamEventRecord]:
    safe_limit = max(1, min(limit, 200))
    with session_scope() as session:
        rows = session.scalars(
            select(SafeStreamEventRow)
            .where(
                SafeStreamEventRow.conversation_id == conversation_id,
                SafeStreamEventRow.sequence > max(0, after),
            )
            .order_by(SafeStreamEventRow.sequence)
            .limit(safe_limit)
        ).all()
        return [_event(row) for row in rows]


def latest_event_sequence(conversation_id: str) -> int:
    with session_scope() as session:
        return int(
            session.scalar(
                select(func.max(SafeStreamEventRow.sequence)).where(
                    SafeStreamEventRow.conversation_id == conversation_id
                )
            )
            or 0
        )


def create_conversation(
    *,
    workspace_id: str,
    upload_batch_id: str | None,
    title: str,
    task_instruction: str | None,
    source_file_ids: list[str],
    command_id: str,
    command_payload_hash: str,
    created_by: str,
    initial_message: str | None = None,
    initial_reference_answer: str | None = None,
) -> AuthoringConversationRecord:
    timestamp = now()
    row = AuthoringConversationRow(
        id=str(uuid4()),
        workspace_id=workspace_id,
        upload_batch_id=upload_batch_id,
        title=title,
        task_instruction=task_instruction,
        source_file_ids_json=list(source_file_ids),
        command_id=command_id,
        command_payload_hash=command_payload_hash,
        status=AuthoringConversationStatus.processing.value,
        revision=0,
        active_operation_id=None,
        pending_question_json=None,
        command_receipts_json={},
        created_by=created_by,
        created_at=timestamp,
        updated_at=timestamp,
    )
    try:
        with session_scope() as session:
            session.add(row)
            session.flush()
            sequence = 0
            if initial_message:
                sequence += 1
                session.add(
                    AuthoringMessageRow(
                        id=str(uuid4()),
                        conversation_id=row.id,
                        sequence=sequence,
                        role=AuthoringMessageRole.teacher.value,
                        message_type=AuthoringMessageType.chat.value,
                        content_text=initial_message,
                        attachment_ids_json=[],
                        # The conversation command is already the durable
                        # idempotency key for creation.  Do not consume the
                        # global teacher-message command namespace here.
                        command_id=None,
                        verified=True,
                        created_at=timestamp,
                    )
                )
            if initial_reference_answer:
                sequence += 1
                session.add(
                    AuthoringMessageRow(
                        id=str(uuid4()),
                        conversation_id=row.id,
                        sequence=sequence,
                        role=AuthoringMessageRole.teacher.value,
                        message_type=AuthoringMessageType.standard_answer.value,
                        content_text=initial_reference_answer,
                        attachment_ids_json=[],
                        question_draft_id=None,
                        command_id=None,
                        verified=True,
                        created_at=timestamp,
                    )
                )
            session.flush()
            return _conversation(row)
    except IntegrityError:
        existing = get_conversation_by_command(workspace_id, command_id)
        if existing is not None:
            return existing
        raise


def set_active_operation(
    conversation_id: str,
    operation_id: str,
    *,
    expected_revision: int,
) -> AuthoringConversationRecord:
    with session_scope() as session:
        row = session.scalar(
            select(AuthoringConversationRow).where(AuthoringConversationRow.id == conversation_id).with_for_update()
        )
        if row is None:
            raise KeyError(conversation_id)
        operation = session.get(OperationJobRow, operation_id, with_for_update=True)
        if operation is None or operation.target_type != "authoring_conversation" or operation.target_id != conversation_id:
            raise KeyError(operation_id)
        # Creating an OperationJob and attaching it to the public aggregate
        # are separate repository transactions.  The Worker can therefore
        # finish a very short Fake operation in between them.  Never attach a
        # terminal or stale job after its projection has already moved on.
        if row.revision != expected_revision:
            return _conversation(row)
        if row.active_operation_id and row.active_operation_id != operation_id:
            raise RepositoryConflict("authoring conversation already has another operation")
        if operation.status in {"queued", "running"}:
            row.active_operation_id = operation_id
            row.status = AuthoringConversationStatus.processing.value
            row.pending_question_json = None
        elif operation.status == "projection_pending":
            row.active_operation_id = None
            row.status = AuthoringConversationStatus.projection_pending.value
            row.pending_question_json = None
            _append_event_in_session(
                session,
                conversation_id,
                AuthoringEventKind.snapshot_changed.value,
                {"revision": row.revision, "status": row.status, "draft_count": 0},
                now(),
            )
        elif operation.status in {"failed", "superseded", "succeeded"}:
            row.active_operation_id = None
            row.status = AuthoringConversationStatus.failed.value
            row.pending_question_json = None
            _append_event_in_session(
                session,
                conversation_id,
                AuthoringEventKind.failed.value,
                {"code": "AUTHORING_PROCESS_FAILED", "message": "本轮整理没有完成，你的已保存内容仍然保留。"},
                now(),
            )
            _append_event_in_session(
                session,
                conversation_id,
                AuthoringEventKind.snapshot_changed.value,
                {"revision": row.revision, "status": row.status, "draft_count": 0},
                now(),
            )
        else:
            raise RepositoryConflict("authoring operation has an unknown status")
        row.updated_at = now()
        session.flush()
        return _conversation(row)


def append_teacher_message(
    conversation_id: str,
    *,
    expected_revision: int,
    command_id: str,
    content: str,
    message_type: str,
    question_draft_id: str | None,
    attachment_ids: list[str],
    command_payload_hash: str,
) -> tuple[AuthoringConversationRecord, AuthoringMessageRecord, bool]:
    timestamp = now()
    try:
        with session_scope() as session:
            row = session.scalar(
                select(AuthoringConversationRow).where(AuthoringConversationRow.id == conversation_id).with_for_update()
            )
            if row is None:
                raise KeyError(conversation_id)
            existing = session.scalar(
                select(AuthoringMessageRow).where(
                    AuthoringMessageRow.conversation_id == conversation_id,
                    AuthoringMessageRow.command_id == command_id,
                )
            )
            if existing is not None:
                if payload_hash(
                    {
                        "content": existing.content_text,
                        "message_type": existing.message_type,
                        "question_draft_id": existing.question_draft_id,
                        "attachment_ids": existing.attachment_ids_json or [],
                    }
                ) != command_payload_hash:
                    raise RepositoryConflict("message command payload conflicts")
                return _conversation(row), _message(existing), True
            if row.status == AuthoringConversationStatus.processing.value:
                raise RepositoryConflict("authoring conversation already has an active operation")
            if row.revision != expected_revision:
                raise StaleProjection("authoring conversation revision changed")
            max_sequence = session.scalar(
                select(func.max(AuthoringMessageRow.sequence)).where(
                    AuthoringMessageRow.conversation_id == conversation_id
                )
            ) or 0
            message = AuthoringMessageRow(
                id=str(uuid4()),
                conversation_id=conversation_id,
                sequence=int(max_sequence) + 1,
                role=AuthoringMessageRole.teacher.value,
                message_type=message_type,
                content_text=content,
                attachment_ids_json=list(attachment_ids),
                question_draft_id=question_draft_id,
                command_id=command_id,
                verified=True,
                created_at=timestamp,
            )
            session.add(message)
            # A normal chat is an upstream edit and invalidates every
            # confirmed draft.  A standard answer belongs to exactly one
            # draft, so it must not clear confirmations for other questions.
            drafts = session.scalars(
                select(BenchmarkQuestionDraftRow).where(
                    BenchmarkQuestionDraftRow.conversation_id == conversation_id,
                    BenchmarkQuestionDraftRow.status != QuestionDraftStatus.discarded.value,
                )
            ).all()
            for draft in drafts:
                if message_type != AuthoringMessageType.standard_answer.value:
                    # A normal chat is an upstream edit unless it is being
                    # used as the response to the single pending Agent
                    # question.  The service supplies that target explicitly.
                    if question_draft_id is None:
                        draft.question_checkpoint_id = None
                        draft.question_question_count = 0
                        draft.question_input_revision = None
                        draft.question_prompt_sequence = None
                if (
                    draft.status == QuestionDraftStatus.input_answer_confirmed.value
                    and (
                        message_type != AuthoringMessageType.standard_answer.value
                        or draft.id == question_draft_id
                    )
                ):
                    draft.status = QuestionDraftStatus.input_answer_drafting.value
                    draft.confirmed_revision = None
                    draft.confirmed_hash = None
                    draft.confirmed_by = None
                    draft.confirmed_at = None
                    draft.last_confirmation_command_id = None
            row.revision += 1
            row.status = AuthoringConversationStatus.processing.value
            row.pending_question_json = None
            row.active_operation_id = None
            row.updated_at = timestamp
            session.flush()
            return _conversation(row), _message(message), False
    except IntegrityError:
        # The global command constraint handles two sessions racing with the
        # same teacher command.  Re-read after rollback and make the loser a
        # deterministic 409 instead of leaking a database 500.
        existing = get_message_by_global_command(command_id)
        if existing is not None:
            if existing.conversation_id != conversation_id:
                raise RepositoryConflict("message command belongs to another conversation") from None
            if payload_hash(
                {
                    "content": existing.content,
                    "message_type": existing.message_type,
                    "question_draft_id": existing.question_draft_id,
                    "attachment_ids": existing.attachment_ids,
                }
            ) != command_payload_hash:
                raise RepositoryConflict("message command payload conflicts") from None
            conversation = get_conversation(conversation_id)
            if conversation is None:
                raise KeyError(conversation_id)
            return conversation, existing, True
        raise RepositoryConflict("authoring conversation was updated concurrently") from None


def _receipt_or_conflict(row: AuthoringConversationRow, command_id: str, digest: str) -> bool:
    receipt = (row.command_receipts_json or {}).get(command_id)
    if receipt is None:
        return False
    if receipt.get("payload_hash") != digest:
        raise RepositoryConflict("command payload conflicts")
    return True


def _remember_receipt(row: AuthoringConversationRow, command_id: str, digest: str) -> None:
    receipts = dict(row.command_receipts_json or {})
    receipts[command_id] = {"payload_hash": digest}
    # Keep every receipt so a delayed/replayed command can never acquire a
    # second side effect after an arbitrary number of later edits.
    row.command_receipts_json = receipts


def mutate_boundaries(
    conversation_id: str,
    *,
    expected_revision: int,
    command_id: str,
    action: str,
    draft_ids: list[str],
    groups: list[dict[str, Any]],
    digest: str,
) -> AuthoringConversationRecord:
    timestamp = now()
    with session_scope() as session:
        conversation = session.scalar(
            select(AuthoringConversationRow)
            .where(AuthoringConversationRow.id == conversation_id)
            .with_for_update()
        )
        if conversation is None:
            raise KeyError(conversation_id)
        if _receipt_or_conflict(conversation, command_id, digest):
            return _conversation(conversation)
        if conversation.revision != expected_revision:
            raise StaleProjection("authoring conversation revision changed")
        if conversation.status == AuthoringConversationStatus.processing.value:
            raise RepositoryConflict("authoring conversation already has an active operation")
        drafts = session.scalars(
            select(BenchmarkQuestionDraftRow).where(
                BenchmarkQuestionDraftRow.conversation_id == conversation_id,
                BenchmarkQuestionDraftRow.id.in_(draft_ids),
            )
        ).all()
        if len(drafts) != len(draft_ids):
            raise RepositoryConflict("question draft is outside this conversation")
        if any(item.status == QuestionDraftStatus.discarded.value for item in drafts):
            raise RepositoryConflict("discarded question draft cannot be changed")
        if any(item.status != QuestionDraftStatus.candidate.value for item in drafts):
            raise RepositoryConflict("only candidate question draft boundaries can be changed")
        if action == "confirm":
            for draft in drafts:
                draft.status = QuestionDraftStatus.input_answer_drafting.value
                draft.confirmed_revision = None
                draft.confirmed_hash = None
                draft.confirmed_by = None
                draft.confirmed_at = None
                draft.last_confirmation_command_id = None
                draft.updated_at = timestamp
        elif action == "discard":
            for draft in drafts:
                draft.status = QuestionDraftStatus.discarded.value
                draft.updated_at = timestamp
        elif action == "merge":
            evidence: list[str] = []
            materials_by_id: dict[str, dict[str, Any]] = {}
            for draft in drafts:
                for file_id in draft.evidence_file_ids_json or []:
                    if file_id not in evidence:
                        evidence.append(file_id)
                for material in (draft.input_json or {}).get("materials") or []:
                    if not isinstance(material, dict):
                        continue
                    file_id = str(material.get("file_id") or "")
                    if file_id and file_id not in materials_by_id:
                        materials_by_id[file_id] = dict(material)
            first = drafts[0]
            merged_input = dict(first.input_json or {})
            merged_materials: list[dict[str, Any]] = []
            for index, file_id in enumerate(evidence):
                merged_materials.append(
                    materials_by_id.get(
                        file_id,
                        {
                            "file_id": file_id,
                            "role": "unconfirmed",
                            "priority": index,
                            "rationale": None,
                        },
                    )
                )
            merged_input["materials"] = merged_materials
            merged = BenchmarkQuestionDraftRow(
                id=str(uuid4()),
                conversation_id=conversation_id,
                title="合并后的候选题",
                summary="老师将多个候选任务合并为一个独立题目，请继续审阅题目输入和标准答案。",
                status=QuestionDraftStatus.candidate.value,
                revision=0,
                input_json=merged_input,
                # Answers are question-specific.  A merge changes the
                # question boundary, so even a single inherited answer must
                # be reviewed again instead of being silently reassigned.
                reference_answer_text=None,
                reference_answer_source=None,
                evidence_file_ids_json=evidence,
                source_refs_json=[],
                question_checkpoint_id=None,
                question_question_count=0,
                question_input_revision=None,
                question_prompt_sequence=None,
                created_at=timestamp,
                updated_at=timestamp,
            )
            session.add(merged)
            for draft in drafts:
                draft.status = QuestionDraftStatus.discarded.value
                draft.updated_at = timestamp
        elif action == "split":
            if len(drafts) != 1 or len(groups) < 2:
                raise ValueError("split requires exactly one draft")
            original = drafts[0]
            original_ids = set(original.evidence_file_ids_json or [])
            used: set[str] = set()
            for group in groups:
                group_ids = list(group.get("evidence_file_ids") or [])
                if not group_ids or set(group_ids) - original_ids or used.intersection(group_ids):
                    raise ValueError("split groups must be disjoint subsets of the draft")
                used.update(group_ids)
            if used != original_ids:
                raise ValueError("split groups must cover the original draft evidence")
            for group in groups:
                input_json = dict(original.input_json or {})
                input_json["task_instruction"] = str(group["title"])
                input_json["materials"] = [
                    item
                    for item in (input_json.get("materials") or [])
                    if item.get("file_id") in set(group.get("evidence_file_ids") or [])
                ]
                session.add(
                    BenchmarkQuestionDraftRow(
                        id=str(uuid4()),
                        conversation_id=conversation_id,
                        title=str(group["title"]),
                        summary=str(group.get("summary") or "老师确认的一个独立任务。"),
                        status=QuestionDraftStatus.candidate.value,
                        revision=0,
                        input_json=input_json,
                        reference_answer_text=None,
                        reference_answer_source=None,
                        evidence_file_ids_json=list(group.get("evidence_file_ids") or []),
                        source_refs_json=[],
                        question_checkpoint_id=None,
                        question_question_count=0,
                        question_input_revision=None,
                        question_prompt_sequence=None,
                        created_at=timestamp,
                        updated_at=timestamp,
                    )
                )
            original.status = QuestionDraftStatus.discarded.value
            original.updated_at = timestamp
        else:
            raise ValueError("unsupported boundary action")
        _remember_receipt(conversation, command_id, digest)
        conversation.revision += 1
        conversation.status = AuthoringConversationStatus.review_ready.value
        active_after = [
            item
            for item in session.scalars(
                select(BenchmarkQuestionDraftRow).where(
                    BenchmarkQuestionDraftRow.conversation_id == conversation_id,
                    BenchmarkQuestionDraftRow.status != QuestionDraftStatus.discarded.value,
                )
            ).all()
        ]
        if action == "confirm":
            missing = next((item for item in active_after if not item.reference_answer_text), None)
            conversation.pending_question_json = (
                {
                    "id": f"standard-answer-{missing.id}",
                    "text": f"请提供“{missing.title}”的老师终版或明确认可的标准答案。",
                    "reason": "没有老师明确认可的终版，不能把 AI 候选当作标准答案。",
                    "gap_type": "standard_answer",
                    "question_draft_id": missing.id,
                }
                if missing is not None
                else None
            )
        else:
            conversation.pending_question_json = None
        conversation.updated_at = timestamp
        session.flush()
        return _conversation(conversation)


def update_draft_input(
    draft_id: str,
    *,
    expected_revision: int,
    command_id: str,
    digest: str,
    input_json: dict[str, Any],
    reference_answer_text: str | None,
    source_refs: list[dict[str, Any]],
) -> QuestionDraftRecord:
    timestamp = now()
    with session_scope() as session:
        draft = session.scalar(
            select(BenchmarkQuestionDraftRow).where(BenchmarkQuestionDraftRow.id == draft_id).with_for_update()
        )
        if draft is None:
            raise KeyError(draft_id)
        conversation = session.scalar(
            select(AuthoringConversationRow)
            .where(AuthoringConversationRow.id == draft.conversation_id)
            .with_for_update()
        )
        if conversation is None:
            raise KeyError(draft.conversation_id)
        if _receipt_or_conflict(conversation, command_id, digest):
            return _draft(draft)
        if conversation.status == AuthoringConversationStatus.processing.value:
            raise RepositoryConflict("authoring conversation already has an active operation")
        if draft.status in {QuestionDraftStatus.discarded.value, QuestionDraftStatus.candidate.value}:
            raise RepositoryConflict("confirm the question boundary before editing the question")
        if draft.revision != expected_revision:
            raise StaleProjection("question draft revision changed")
        materials = input_json.get("materials") or []
        draft.input_json = dict(input_json)
        draft.evidence_file_ids_json = [
            str(item["file_id"])
            for item in materials
            if item.get("role") != "ignored"
        ]
        draft.reference_answer_text = reference_answer_text
        draft.reference_answer_source = "teacher_input" if reference_answer_text else None
        draft.source_refs_json = list(source_refs)
        draft.question_checkpoint_id = None
        draft.question_question_count = 0
        draft.question_input_revision = None
        draft.question_prompt_sequence = None
        draft.revision += 1
        draft.status = QuestionDraftStatus.input_answer_drafting.value
        draft.confirmed_revision = None
        draft.confirmed_hash = None
        draft.confirmed_by = None
        draft.confirmed_at = None
        draft.last_confirmation_command_id = None
        draft.updated_at = timestamp
        _remember_receipt(conversation, command_id, digest)
        conversation.revision += 1
        conversation.status = AuthoringConversationStatus.review_ready.value
        active = session.scalars(
            select(BenchmarkQuestionDraftRow).where(
                BenchmarkQuestionDraftRow.conversation_id == conversation.id,
                BenchmarkQuestionDraftRow.status != QuestionDraftStatus.discarded.value,
            )
        ).all()
        missing = next((item for item in active if not item.reference_answer_text), None)
        conversation.pending_question_json = (
            {
                "id": f"standard-answer-{missing.id}",
                "text": f"请提供“{missing.title}”的老师终版或明确认可的标准答案。",
                "reason": "没有老师明确认可的终版，不能把 AI 候选当作标准答案。",
                "gap_type": "standard_answer",
                "question_draft_id": missing.id,
            }
            if missing is not None
            else None
        )
        conversation.updated_at = timestamp
        session.flush()
        return _draft(draft)


def confirm_draft(
    draft_id: str,
    *,
    expected_revision: int,
    command_id: str,
    confirmed_by: str,
    digest: str,
) -> QuestionDraftRecord:
    timestamp = now()
    with session_scope() as session:
        draft = session.scalar(
            select(BenchmarkQuestionDraftRow).where(BenchmarkQuestionDraftRow.id == draft_id).with_for_update()
        )
        if draft is None:
            raise KeyError(draft_id)
        conversation = session.scalar(
            select(AuthoringConversationRow)
            .where(AuthoringConversationRow.id == draft.conversation_id)
            .with_for_update()
        )
        if conversation is None:
            raise KeyError(draft.conversation_id)
        if _receipt_or_conflict(conversation, command_id, digest):
            return _draft(draft)
        if conversation.status == AuthoringConversationStatus.processing.value:
            raise RepositoryConflict("authoring conversation already has an active operation")
        if draft.status == QuestionDraftStatus.input_answer_confirmed.value:
            if draft.last_confirmation_command_id == command_id:
                return _draft(draft)
            raise RepositoryConflict("question draft confirmation already decided")
        if draft.revision != expected_revision:
            raise StaleProjection("question draft revision changed")
        if draft.status in {QuestionDraftStatus.discarded.value, QuestionDraftStatus.candidate.value}:
            raise RepositoryConflict("question draft boundary is not confirmed")
        if not draft.reference_answer_text or draft.reference_answer_source not in {"teacher_message", "teacher_input"}:
            raise RepositoryConflict("a teacher standard answer is required")
        materials = draft.input_json.get("materials") or []
        if any(item.get("role") == "unconfirmed" for item in materials):
            raise RepositoryConflict("question material roles are not confirmed")
        draft.status = QuestionDraftStatus.input_answer_confirmed.value
        draft.confirmed_revision = draft.revision
        draft.confirmed_hash = payload_hash(
            {
                "input": draft.input_json,
                "reference_answer_text": draft.reference_answer_text,
                "source_refs": draft.source_refs_json or [],
            }
        )
        draft.confirmed_by = confirmed_by
        draft.confirmed_at = timestamp
        draft.last_confirmation_command_id = command_id
        draft.question_checkpoint_id = None
        draft.question_question_count = 0
        draft.question_input_revision = None
        draft.question_prompt_sequence = None
        draft.updated_at = timestamp
        _remember_receipt(conversation, command_id, digest)
        conversation.revision += 1
        active = session.scalars(
            select(BenchmarkQuestionDraftRow).where(
                BenchmarkQuestionDraftRow.conversation_id == conversation.id,
                BenchmarkQuestionDraftRow.status != QuestionDraftStatus.discarded.value,
            )
        ).all()
        if active and all(item.status == QuestionDraftStatus.input_answer_confirmed.value for item in active):
            conversation.status = AuthoringConversationStatus.confirmed.value
        else:
            conversation.status = AuthoringConversationStatus.review_ready.value
        conversation.updated_at = timestamp
        session.flush()
        return _draft(draft)


def queue_retry(
    conversation_id: str,
    expected_revision: int,
    *,
    command_id: str,
    digest: str,
) -> tuple[AuthoringConversationRecord, bool] | None:
    with session_scope() as session:
        row = session.scalar(
            select(AuthoringConversationRow).where(AuthoringConversationRow.id == conversation_id).with_for_update()
        )
        if row is None:
            raise KeyError(conversation_id)
        if _receipt_or_conflict(row, command_id, digest):
            return _conversation(row), True
        if row.status == AuthoringConversationStatus.processing.value and row.active_operation_id:
            operation = session.get(OperationJobRow, row.active_operation_id)
            if operation and operation.status == "failed":
                row.status = AuthoringConversationStatus.failed.value
                row.active_operation_id = None
            elif operation and operation.status == "projection_pending":
                row.status = AuthoringConversationStatus.projection_pending.value
                row.active_operation_id = None
        if row.revision != expected_revision:
            return None
        if row.status not in {
            AuthoringConversationStatus.failed.value,
            AuthoringConversationStatus.projection_pending.value,
        }:
            raise RepositoryConflict("authoring conversation is not retryable")
        row.status = AuthoringConversationStatus.processing.value
        row.pending_question_json = None
        row.active_operation_id = None
        row.revision += 1
        _remember_receipt(row, command_id, digest)
        row.updated_at = now()
        session.flush()
        return _conversation(row), False


def reset_continuity(
    conversation_id: str,
    expected_revision: int,
    *,
    command_id: str,
    digest: str,
) -> tuple[AuthoringConversationRecord, bool] | None:
    """Move a reset-required conversation back to a fresh queued run.

    The first slice does not expose checkpoint identifiers.  Reset therefore
    deliberately starts from the durable transcript/draft snapshot and never
    pretends that an old Agent checkpoint is still usable.
    """

    with session_scope() as session:
        row = session.scalar(
            select(AuthoringConversationRow).where(AuthoringConversationRow.id == conversation_id).with_for_update()
        )
        if row is None:
            raise KeyError(conversation_id)
        if _receipt_or_conflict(row, command_id, digest):
            return _conversation(row), True
        if row.revision != expected_revision:
            return None
        if row.status != AuthoringConversationStatus.continuity_reset.value:
            raise RepositoryConflict("continuity reset is not required")
        row.status = AuthoringConversationStatus.processing.value
        row.pending_question_json = None
        row.active_operation_id = None
        row.revision += 1
        _remember_receipt(row, command_id, digest)
        row.updated_at = now()
        session.flush()
        return _conversation(row), False


def mark_continuity_reset(conversation_id: str, reason: str) -> AuthoringConversationRecord:
    timestamp = now()
    with session_scope() as session:
        row = session.scalar(
            select(AuthoringConversationRow).where(AuthoringConversationRow.id == conversation_id).with_for_update()
        )
        if row is None:
            raise KeyError(conversation_id)
        row.status = AuthoringConversationStatus.continuity_reset.value
        row.pending_question_json = {
            "id": "continuity-reset",
            "text": "会话连续性需要重新建立，请从当前业务快照继续。",
            "reason": "后台连续性不可用，已保留已经保存的题目和回答。",
            "gap_type": "evidence",
        }
        row.active_operation_id = None
        row.updated_at = timestamp
        _append_event_in_session(
            session,
            conversation_id,
            AuthoringEventKind.failed.value,
            {"code": "CONTINUITY_RESET", "message": "本轮连续性不可用，已保留已保存内容。"},
            timestamp,
        )
        _append_event_in_session(
            session,
            conversation_id,
            AuthoringEventKind.snapshot_changed.value,
            {"revision": row.revision, "status": row.status, "draft_count": 0},
            timestamp,
        )
        session.flush()
        return _conversation(row)


def mark_failed(
    conversation_id: str,
    code: str = "AUTHORING_FAILED",
    *,
    expected_revision: int | None = None,
    expected_operation_id: str | None = None,
    expected_operation_attempt: int | None = None,
    expected_worker_id: str | None = None,
) -> AuthoringConversationRecord:
    timestamp = now()
    with session_scope() as session:
        row = session.scalar(
            select(AuthoringConversationRow).where(AuthoringConversationRow.id == conversation_id).with_for_update()
        )
        if row is None:
            raise KeyError(conversation_id)
        if expected_revision is not None and row.revision != expected_revision:
            return _conversation(row)
        if expected_operation_id is not None and row.active_operation_id != expected_operation_id:
            return _conversation(row)
        if expected_operation_id is not None and (
            (operation := session.get(OperationJobRow, expected_operation_id)) is None
            or operation.status != "running"
            or (expected_operation_attempt is not None and operation.attempts != expected_operation_attempt)
            or (expected_worker_id is not None and operation.worker_id != expected_worker_id)
        ):
            return _conversation(row)
        row.status = AuthoringConversationStatus.failed.value
        row.pending_question_json = None
        row.active_operation_id = None
        row.updated_at = timestamp
        _append_event_in_session(
            session,
            conversation_id,
            AuthoringEventKind.failed.value,
            {"code": code, "message": "本轮整理没有完成，你的已保存内容仍然保留。"},
            timestamp,
        )
        _append_event_in_session(
            session,
            conversation_id,
            AuthoringEventKind.snapshot_changed.value,
            {"revision": row.revision, "status": row.status, "draft_count": 0},
            timestamp,
        )
        session.flush()
        return _conversation(row)


def mark_projection_pending(
    conversation_id: str,
    *,
    expected_revision: int | None = None,
    expected_operation_id: str | None = None,
) -> AuthoringConversationRecord:
    with session_scope() as session:
        row = session.scalar(
            select(AuthoringConversationRow).where(AuthoringConversationRow.id == conversation_id).with_for_update()
        )
        if row is None:
            raise KeyError(conversation_id)
        if expected_revision is not None and row.revision != expected_revision:
            return _conversation(row)
        if expected_operation_id is not None and row.active_operation_id != expected_operation_id:
            return _conversation(row)
        row.status = AuthoringConversationStatus.projection_pending.value
        row.pending_question_json = None
        row.active_operation_id = None
        row.updated_at = now()
        _append_event_in_session(
            session,
            conversation_id,
            AuthoringEventKind.snapshot_changed.value,
            {"revision": row.revision, "status": row.status, "draft_count": 0},
            row.updated_at,
        )
        session.flush()
        return _conversation(row)


def _append_event_in_session(
    session,
    conversation_id: str,
    kind: str,
    payload: dict[str, Any],
    timestamp: datetime,
) -> SafeStreamEventRow:
    _validate_safe_event(kind, payload)
    maximum = session.scalar(
        select(func.max(SafeStreamEventRow.sequence)).where(
            SafeStreamEventRow.conversation_id == conversation_id
        )
    ) or 0
    row = SafeStreamEventRow(
        id=str(uuid4()),
        conversation_id=conversation_id,
        sequence=int(maximum) + 1,
        kind=kind,
        payload_json=dict(payload),
        created_at=timestamp,
    )
    session.add(row)
    session.flush()
    stale_ids = session.scalars(
        select(SafeStreamEventRow.id)
        .where(SafeStreamEventRow.conversation_id == conversation_id)
        .order_by(SafeStreamEventRow.sequence.desc())
        .offset(_SAFE_EVENT_RETENTION)
    ).all()
    if stale_ids:
        session.execute(delete(SafeStreamEventRow).where(SafeStreamEventRow.id.in_(stale_ids)))
    return row


def append_event(conversation_id: str, kind: str, payload: dict[str, Any]) -> SafeStreamEventRecord:
    # SQLite does not implement SELECT ... FOR UPDATE.  A rare concurrent
    # append can therefore race on the per-conversation sequence; retry the
    # unique-key loser with a fresh transaction instead of leaking a 500.
    for attempt in range(3):
        timestamp = now()
        try:
            with session_scope() as session:
                row = session.get(AuthoringConversationRow, conversation_id)
                if row is None:
                    raise KeyError(conversation_id)
                event = _append_event_in_session(session, conversation_id, kind, payload, timestamp)
                return _event(event)
        except IntegrityError:
            if attempt == 2:
                raise RepositoryConflict("safe stream event sequence is busy") from None
    raise RepositoryConflict("safe stream event sequence is busy")


def commit_worker_projection(
    conversation_id: str,
    *,
    expected_revision: int,
    operation_job_id: str,
    operation_attempt: int,
    worker_id: str,
    drafts: list[dict[str, Any]],
    status: str,
    pending_question: dict[str, Any] | None,
    assistant_message: str,
    events: list[tuple[str, dict[str, Any]]],
) -> AuthoringConversationRecord:
    timestamp = now()
    with session_scope() as session:
        operation = session.scalar(
            select(OperationJobRow).where(OperationJobRow.id == operation_job_id).with_for_update()
        )
        if (
            operation is None
            or operation.target_type != "authoring_conversation"
            or operation.target_id != conversation_id
            or operation.business_revision != expected_revision
            or operation.kind not in {"authoring_process", "authoring_reproject"}
            or operation.status != "running"
            or operation.worker_id != worker_id
            or operation.attempts != operation_attempt
        ):
            raise StaleProjection("authoring operation attempt is stale")
        conversation = session.scalar(
            select(AuthoringConversationRow)
            .where(AuthoringConversationRow.id == conversation_id)
            .with_for_update()
        )
        if conversation is None:
            raise KeyError(conversation_id)
        if conversation.revision != expected_revision:
            raise StaleProjection("authoring conversation branch is stale")
        existing = {
            row.id: row
            for row in session.scalars(
                select(BenchmarkQuestionDraftRow).where(
                    BenchmarkQuestionDraftRow.conversation_id == conversation_id
                )
            ).all()
        }
        for spec in drafts:
            draft_id = str(spec.get("id") or uuid4())
            row = existing.get(draft_id)
            if row is None:
                row = BenchmarkQuestionDraftRow(
                    id=draft_id,
                    conversation_id=conversation_id,
                    title=str(spec["title"]),
                    summary=str(spec["summary"]),
                    status=str(spec.get("status", QuestionDraftStatus.candidate.value)),
                    revision=0,
                    input_json=dict(spec["input"]),
                    reference_answer_text=spec.get("reference_answer_text"),
                    reference_answer_source=spec.get("reference_answer_source"),
                    evidence_file_ids_json=list(spec.get("evidence_file_ids", [])),
                    source_refs_json=list(spec.get("source_refs", [])),
                    question_checkpoint_id=spec.get("question_checkpoint_id"),
                    question_question_count=int(spec.get("question_question_count") or 0),
                    question_input_revision=spec.get("question_input_revision"),
                    question_prompt_sequence=spec.get("question_prompt_sequence"),
                    created_at=timestamp,
                    updated_at=timestamp,
                )
                session.add(row)
            else:
                row.title = str(spec.get("title", row.title))
                row.summary = str(spec.get("summary", row.summary))
                row.input_json = dict(spec.get("input", row.input_json or {}))
                row.evidence_file_ids_json = list(spec.get("evidence_file_ids", row.evidence_file_ids_json or []))
                if "reference_answer_text" in spec:
                    row.reference_answer_text = spec.get("reference_answer_text")
                    row.reference_answer_source = spec.get("reference_answer_source")
                if "source_refs" in spec:
                    row.source_refs_json = list(spec.get("source_refs") or [])
                if "question_checkpoint_id" in spec:
                    row.question_checkpoint_id = spec.get("question_checkpoint_id")
                if "question_question_count" in spec:
                    row.question_question_count = int(spec.get("question_question_count") or 0)
                if "question_input_revision" in spec:
                    row.question_input_revision = spec.get("question_input_revision")
                if "question_prompt_sequence" in spec:
                    row.question_prompt_sequence = spec.get("question_prompt_sequence")
                if row.status != QuestionDraftStatus.input_answer_confirmed.value:
                    row.status = str(spec.get("status", row.status))
                row.revision += 1
                row.updated_at = timestamp
        if assistant_message:
            maximum = session.scalar(
                select(func.max(AuthoringMessageRow.sequence)).where(
                    AuthoringMessageRow.conversation_id == conversation_id
                )
            ) or 0
            session.add(
                AuthoringMessageRow(
                    id=str(uuid4()),
                    conversation_id=conversation_id,
                    sequence=int(maximum) + 1,
                    role=AuthoringMessageRole.assistant.value,
                    message_type=AuthoringMessageType.chat.value,
                    content_text=assistant_message,
                    attachment_ids_json=[],
                    question_draft_id=(pending_question or {}).get("question_draft_id"),
                    command_id=None,
                    verified=True,
                    created_at=timestamp,
                )
            )
        for kind, payload in events:
            _append_event_in_session(session, conversation_id, kind, payload, timestamp)
        conversation.status = status
        conversation.pending_question_json = dict(pending_question) if pending_question else None
        conversation.active_operation_id = None
        conversation.revision += 1
        conversation.updated_at = timestamp
        session.flush()
        return _conversation(conversation)
