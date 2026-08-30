from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from typing import Any
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.features.case_builder.cocreation_schemas import (
    BatchAnalysis,
    CoCreationAgentResult,
    CoCreationKind,
    CoCreationStatus,
    CoCreationQuestion,
    CoCreationDelta,
    ContractRevisionStatus,
    JudgmentPackageContent,
    ScenarioContractContent,
    SkillAttemptProposal,
    TaskGroupInput,
    TaskPackageStatus,
)
from app.lib.database import as_utc, session_scope
from app.lib.database.models import (
    CoCreationSessionRow,
    CoCreationTurnRow,
    EvidenceFileRow,
    ScenarioContractRevisionRow,
    SkillRunEvidenceRow,
    StandardPromotionProposalRow,
    TaskPackageRow,
    TeacherFeedbackRow,
    UploadBatchRow,
    WorkspaceRow,
)


class RepositoryConflict(RuntimeError):
    pass


class StaleProjection(RepositoryConflict):
    pass


@dataclass(frozen=True, slots=True)
class TaskPackageRecord:
    id: str
    workspace_id: str
    upload_batch_id: str
    status: str
    title: str
    evidence_file_ids: list[str]
    revision: int
    analysis: dict[str, Any] | None
    contract_revision_id: str | None
    draft: dict[str, Any] | None
    judgment_package: dict[str, Any] | None
    initialization_only: bool
    confirmed_by: str | None
    confirmed_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ContractRevisionRecord:
    id: str
    workspace_id: str
    revision: int
    status: str
    contract: dict[str, Any]
    source_session_id: str | None
    confirmed_by: str | None
    confirmed_at: datetime | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class CoCreationSessionRecord:
    id: str
    workspace_id: str
    task_package_id: str
    stable_thread_key: str
    command_id: str | None
    kind: str
    purpose: str | None
    initialization_only: bool
    status: str
    business_revision: int
    current_turn_revision: int
    accepted_checkpoint_id: str | None
    pending_interrupt: dict[str, Any] | None
    projection: dict[str, Any] | None
    contract_revision_id: str | None
    confirmation_command_id: str | None
    continuity_reset_from_id: str | None
    continuity_reset_to_id: str | None
    continuity_reset_reason: str | None
    ai_profile_version: str
    graph_schema_version: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class CoCreationTurnRecord:
    id: str
    session_id: str
    turn_revision: int
    question_id: str | None
    question: dict[str, Any] | None
    answer: str | None
    answer_command_id: str | None
    delta: dict[str, Any] | None
    base_checkpoint_id: str | None
    produced_checkpoint_id: str | None
    result_hash: str | None
    status: str
    created_at: datetime
    answered_at: datetime | None


@dataclass(frozen=True, slots=True)
class TeacherFeedbackRecord:
    id: str
    task_package_id: str
    source_id: str
    text: str
    scope: str
    confirmed_by: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class PromotionProposalRecord:
    id: str
    workspace_id: str
    source_feedback_id: str
    proposed_text: str
    status: str
    created_at: datetime
    decided_at: datetime | None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _json(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


def result_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(_json(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _task(row: TaskPackageRow) -> TaskPackageRecord:
    return TaskPackageRecord(
        id=row.id,
        workspace_id=row.workspace_id,
        upload_batch_id=row.upload_batch_id,
        status=row.status,
        title=row.title,
        evidence_file_ids=list(row.evidence_file_ids_json or []),
        revision=row.revision,
        analysis=dict(row.analysis_json) if row.analysis_json else None,
        contract_revision_id=row.contract_revision_id,
        draft=dict(row.draft_json) if row.draft_json else None,
        judgment_package=dict(row.judgment_package_json) if row.judgment_package_json else None,
        initialization_only=bool(row.initialization_only),
        confirmed_by=row.confirmed_by,
        confirmed_at=as_utc(row.confirmed_at) if row.confirmed_at else None,
        created_at=as_utc(row.created_at),
        updated_at=as_utc(row.updated_at),
    )


def _contract(row: ScenarioContractRevisionRow) -> ContractRevisionRecord:
    return ContractRevisionRecord(
        id=row.id,
        workspace_id=row.workspace_id,
        revision=row.revision,
        status=row.status,
        contract=dict(row.contract_json),
        source_session_id=row.source_session_id,
        confirmed_by=row.confirmed_by,
        confirmed_at=as_utc(row.confirmed_at) if row.confirmed_at else None,
        created_at=as_utc(row.created_at),
    )


def _session(row: CoCreationSessionRow) -> CoCreationSessionRecord:
    return CoCreationSessionRecord(
        id=row.id,
        workspace_id=row.workspace_id,
        task_package_id=row.task_package_id,
        stable_thread_key=row.stable_thread_key,
        command_id=row.command_id,
        kind=row.kind,
        purpose=row.purpose,
        initialization_only=bool(row.initialization_only),
        status=row.status,
        business_revision=row.business_revision,
        current_turn_revision=row.current_turn_revision,
        accepted_checkpoint_id=row.accepted_checkpoint_id,
        pending_interrupt=dict(row.pending_interrupt_json) if row.pending_interrupt_json else None,
        projection=dict(row.projection_json) if row.projection_json else None,
        contract_revision_id=row.contract_revision_id,
        confirmation_command_id=row.confirmation_command_id,
        continuity_reset_from_id=row.continuity_reset_from_id,
        continuity_reset_to_id=row.continuity_reset_to_id,
        continuity_reset_reason=row.continuity_reset_reason,
        ai_profile_version=row.ai_profile_version,
        graph_schema_version=row.graph_schema_version,
        created_at=as_utc(row.created_at),
        updated_at=as_utc(row.updated_at),
    )


def _turn(row: CoCreationTurnRow) -> CoCreationTurnRecord:
    return CoCreationTurnRecord(
        id=row.id,
        session_id=row.session_id,
        turn_revision=row.turn_revision,
        question_id=row.question_id,
        question=dict(row.question_json) if row.question_json else None,
        answer=row.answer_text,
        answer_command_id=row.answer_command_id,
        delta=dict(row.delta_json) if row.delta_json else None,
        base_checkpoint_id=row.base_checkpoint_id,
        produced_checkpoint_id=row.produced_checkpoint_id,
        result_hash=row.result_hash,
        status=row.status,
        created_at=as_utc(row.created_at),
        answered_at=as_utc(row.answered_at) if row.answered_at else None,
    )


def _feedback(row: TeacherFeedbackRow) -> TeacherFeedbackRecord:
    return TeacherFeedbackRecord(
        id=row.id,
        task_package_id=row.task_package_id,
        source_id=row.source_id,
        text=row.text,
        scope=row.scope,
        confirmed_by=row.confirmed_by,
        created_at=as_utc(row.created_at),
    )


def _promotion(row: StandardPromotionProposalRow) -> PromotionProposalRecord:
    return PromotionProposalRecord(
        id=row.id,
        workspace_id=row.workspace_id,
        source_feedback_id=row.source_feedback_id,
        proposed_text=row.proposed_text,
        status=row.status,
        created_at=as_utc(row.created_at),
        decided_at=as_utc(row.decided_at) if row.decided_at else None,
    )


def get_task_package(task_package_id: str) -> TaskPackageRecord | None:
    with session_scope() as session:
        row = session.get(TaskPackageRow, task_package_id)
        return _task(row) if row else None


def get_contract_revision(contract_revision_id: str) -> ContractRevisionRecord | None:
    with session_scope() as session:
        row = session.get(ScenarioContractRevisionRow, contract_revision_id)
        return _contract(row) if row else None


def list_contract_revisions(workspace_id: str, *, status: str | None = None) -> list[ContractRevisionRecord]:
    with session_scope() as session:
        statement = select(ScenarioContractRevisionRow).where(
            ScenarioContractRevisionRow.workspace_id == workspace_id
        )
        if status is not None:
            statement = statement.where(ScenarioContractRevisionRow.status == status)
        rows = session.scalars(
            statement.order_by(ScenarioContractRevisionRow.revision.desc())
        ).all()
        return [_contract(row) for row in rows]


def list_task_packages(upload_batch_id: str, *, include_replaced: bool = False) -> list[TaskPackageRecord]:
    with session_scope() as session:
        statement = select(TaskPackageRow).where(TaskPackageRow.upload_batch_id == upload_batch_id)
        if not include_replaced:
            statement = statement.where(TaskPackageRow.status != TaskPackageStatus.replaced.value)
        rows = session.scalars(statement.order_by(TaskPackageRow.created_at, TaskPackageRow.id)).all()
        return [_task(row) for row in rows]


def replace_proposals(batch_id: str, analysis: BatchAnalysis, *, expected_revision: int) -> list[TaskPackageRecord]:
    now = _now()
    with session_scope() as session:
        batch = session.scalar(select(UploadBatchRow).where(UploadBatchRow.id == batch_id).with_for_update())
        if batch is None:
            raise KeyError(batch_id)
        if batch.revision != expected_revision:
            raise RepositoryConflict("upload batch revision changed")
        existing = session.scalars(
            select(TaskPackageRow).where(
                TaskPackageRow.upload_batch_id == batch_id,
                TaskPackageRow.status == TaskPackageStatus.proposed.value,
            )
        ).all()
        analysis_digest = result_hash(analysis)
        if existing and all((row.analysis_json or {}).get("analysis_hash") == analysis_digest for row in existing):
            batch.status = "ready_for_confirmation"
            batch.updated_at = now
            session.flush()
            return [_task(row) for row in existing]
        for row in existing:
            row.status = TaskPackageStatus.replaced.value
            row.updated_at = now
        created: list[TaskPackageRow] = []
        for group in analysis.groups:
            row = TaskPackageRow(
                id=str(uuid4()),
                workspace_id=batch.workspace_id,
                upload_batch_id=batch_id,
                status=TaskPackageStatus.proposed.value,
                title=group.title,
                evidence_file_ids_json=list(group.evidence_file_ids),
                revision=0,
                analysis_json={
                    "analysis_hash": analysis_digest,
                    "proposal_key": group.proposal_key,
                    "summary": group.summary,
                    "attempts": [attempt.model_dump(mode="json") for attempt in group.attempts],
                    "evidence_refs": [ref.model_dump(mode="json") for ref in group.evidence_refs],
                    "warnings": group.warnings,
                    "unassigned_file_ids": analysis.unassigned_file_ids,
                    "file_roles": analysis.file_roles,
                },
                initialization_only=False,
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            created.append(row)
        batch.status = "ready_for_confirmation"
        batch.updated_at = now
        session.flush()
        return [_task(row) for row in created]


def confirm_grouping(
    batch_id: str,
    *,
    expected_revision: int,
    command_id: str,
    groups: list[TaskGroupInput],
    confirmed_by: str,
) -> list[TaskPackageRecord] | None:
    now = _now()
    payload_digest = result_hash({"groups": [group.model_dump(mode="json") for group in groups]})
    with session_scope() as session:
        batch = session.scalar(select(UploadBatchRow).where(UploadBatchRow.id == batch_id).with_for_update())
        if batch is None:
            raise KeyError(batch_id)
        existing_confirmed = session.scalars(
            select(TaskPackageRow).where(
                TaskPackageRow.upload_batch_id == batch_id,
                TaskPackageRow.status == TaskPackageStatus.confirmed.value,
            )
        ).all()
        for row in existing_confirmed:
            if (row.analysis_json or {}).get("grouping_command_id") == command_id:
                if (row.analysis_json or {}).get("grouping_payload_hash") != payload_digest:
                    raise RepositoryConflict("grouping command payload conflicts with the saved grouping")
                return [_task(item) for item in existing_confirmed]
        if existing_confirmed:
            raise RepositoryConflict("task grouping has already been confirmed")
        if batch.revision != expected_revision:
            return None
        file_rows = session.scalars(select(EvidenceFileRow).where(EvidenceFileRow.upload_batch_id == batch_id)).all()
        allowed = {row.id for row in file_rows}
        seen: set[str] = set()
        for group in groups:
            ids = set(group.evidence_file_ids)
            if not ids or ids - allowed or ids & seen:
                raise ValueError("group files must be unique files from the upload batch")
            seen |= ids
        for row in session.scalars(
            select(TaskPackageRow).where(
                TaskPackageRow.upload_batch_id == batch_id,
                TaskPackageRow.status == TaskPackageStatus.proposed.value,
            )
        ).all():
            row.status = TaskPackageStatus.replaced.value
            row.updated_at = now
        created: list[TaskPackageRow] = []
        for group in groups:
            row = TaskPackageRow(
                id=str(uuid4()),
                workspace_id=batch.workspace_id,
                upload_batch_id=batch_id,
                status=TaskPackageStatus.confirmed.value,
                title=group.title,
                evidence_file_ids_json=list(group.evidence_file_ids),
                revision=0,
                analysis_json={
                    "grouping_command_id": command_id,
                    "grouping_payload_hash": payload_digest,
                    "proposal_key": group.proposal_key,
                    "summary": group.summary,
                    "attempts": [attempt.model_dump(mode="json") for attempt in group.attempts],
                    "teacher_confirmed": True,
                },
                initialization_only=group.initialization_only,
                confirmed_by=confirmed_by,
                confirmed_at=now,
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            created.append(row)
            session.flush()
            for attempt in group.attempts:
                for file_id in attempt.evidence_file_ids:
                    session.add(
                        SkillRunEvidenceRow(
                            id=str(uuid4()),
                            task_package_id=row.id,
                            attempt_key=attempt.attempt_key,
                            evidence_file_id=file_id,
                            role=None,
                            metadata_json={"source": "teacher-confirmed"},
                            created_at=now,
                        )
                    )
        batch.revision += 1
        batch.updated_at = now
        session.flush()
        return [_task(row) for row in created]


def get_session(session_id: str) -> CoCreationSessionRecord | None:
    with session_scope() as session:
        row = session.scalar(select(CoCreationSessionRow).where(CoCreationSessionRow.id == session_id).with_for_update())
        return _session(row) if row else None


def get_active_session(task_package_id: str, kind: str) -> CoCreationSessionRecord | None:
    with session_scope() as session:
        row = session.scalar(
            select(CoCreationSessionRow)
            .where(
                CoCreationSessionRow.task_package_id == task_package_id,
                CoCreationSessionRow.kind == kind,
                CoCreationSessionRow.status != CoCreationStatus.confirmed.value,
                CoCreationSessionRow.status != CoCreationStatus.continuity_reset.value,
            )
            .order_by(CoCreationSessionRow.created_at.desc())
            .limit(1)
        )
        return _session(row) if row else None


def get_latest_session(task_package_id: str, kind: str) -> CoCreationSessionRecord | None:
    with session_scope() as session:
        row = session.scalar(
            select(CoCreationSessionRow)
            .where(
                CoCreationSessionRow.task_package_id == task_package_id,
                CoCreationSessionRow.kind == kind,
                CoCreationSessionRow.status != CoCreationStatus.continuity_reset.value,
            )
            .order_by(CoCreationSessionRow.created_at.desc())
            .limit(1)
        )
        return _session(row) if row else None


def get_session_by_command(task_package_id: str, kind: str, command_id: str) -> CoCreationSessionRecord | None:
    with session_scope() as session:
        row = session.scalar(
            select(CoCreationSessionRow).where(
                CoCreationSessionRow.task_package_id == task_package_id,
                CoCreationSessionRow.kind == kind,
                CoCreationSessionRow.command_id == command_id,
            )
        )
        return _session(row) if row else None


def create_session(
    *,
    workspace_id: str,
    task_package_id: str,
    kind: CoCreationKind,
    command_id: str,
    initialization_only: bool,
    ai_profile_version: str,
    graph_schema_version: str,
) -> CoCreationSessionRecord:
    now = _now()
    row = CoCreationSessionRow(
        id=str(uuid4()),
        workspace_id=workspace_id,
        task_package_id=task_package_id,
        stable_thread_key=f"cocreation-{uuid4()}",
        command_id=command_id,
        kind=kind.value,
        purpose="initialization" if initialization_only else None,
        initialization_only=initialization_only,
        status=CoCreationStatus.queued.value,
        business_revision=0,
        current_turn_revision=0,
        accepted_checkpoint_id=None,
        pending_interrupt_json=None,
        projection_json=None,
        contract_revision_id=None,
        confirmation_command_id=None,
        continuity_reset_from_id=None,
        continuity_reset_to_id=None,
        continuity_reset_reason=None,
        ai_profile_version=ai_profile_version,
        graph_schema_version=graph_schema_version,
        created_at=now,
        updated_at=now,
    )
    try:
        with session_scope() as session:
            task = session.scalar(
                select(TaskPackageRow).where(TaskPackageRow.id == task_package_id).with_for_update()
            )
            if task is None:
                raise KeyError(task_package_id)
            active = session.scalar(
                select(CoCreationSessionRow)
                .where(
                    CoCreationSessionRow.task_package_id == task_package_id,
                    CoCreationSessionRow.kind == kind.value,
                    CoCreationSessionRow.status != CoCreationStatus.confirmed.value,
                    CoCreationSessionRow.status != CoCreationStatus.continuity_reset.value,
                )
                .order_by(CoCreationSessionRow.created_at.desc())
                .limit(1)
            )
            if active is not None:
                return _session(active)
            session.add(row)
            session.flush()
            return _session(row)
    except IntegrityError:
        existing = get_session_by_command(task_package_id, kind.value, command_id)
        if existing is not None:
            return existing
        raise


def list_turns(session_id: str) -> list[CoCreationTurnRecord]:
    with session_scope() as session:
        rows = session.scalars(
            select(CoCreationTurnRow)
            .where(CoCreationTurnRow.session_id == session_id)
            .order_by(CoCreationTurnRow.turn_revision, CoCreationTurnRow.id)
        ).all()
        return [_turn(row) for row in rows]


def delete_session(session_id: str) -> None:
    with session_scope() as session:
        session.execute(delete(CoCreationSessionRow).where(CoCreationSessionRow.id == session_id))


def save_answer(
    session_id: str,
    *,
    expected_business_revision: int,
    question_id: str,
    answer: str,
    command_id: str,
) -> tuple[CoCreationSessionRecord, bool] | None:
    now = _now()
    with session_scope() as session:
        session_row = session.scalar(select(CoCreationSessionRow).where(CoCreationSessionRow.id == session_id).with_for_update())
        if session_row is None:
            raise KeyError(session_id)
        same_command = session.scalar(select(CoCreationTurnRow).where(CoCreationTurnRow.answer_command_id == command_id))
        if same_command is not None:
            if same_command.session_id != session_id:
                raise RepositoryConflict("answer command belongs to another session")
            if same_command.question_id != question_id or same_command.answer_text != answer:
                raise RepositoryConflict("answer command payload conflicts with the saved answer")
            return _session(session_row), True
        if session_row.business_revision != expected_business_revision:
            return None
        if session_row.status != CoCreationStatus.waiting_for_teacher.value:
            raise RepositoryConflict("there is no pending teacher question")
        current = session.scalar(
            select(CoCreationTurnRow).where(
                CoCreationTurnRow.session_id == session_id,
                CoCreationTurnRow.turn_revision == session_row.current_turn_revision,
            ).with_for_update()
        )
        if current is None or current.question_id != question_id or current.status != "pending":
            raise RepositoryConflict("question is stale or already answered")
        current.answer_text = answer
        current.answer_command_id = command_id
        current.status = "answered_pending_resume"
        current.answered_at = now
        session_row.business_revision += 1
        session_row.status = CoCreationStatus.processing.value
        session_row.updated_at = now
        session.flush()
        return _session(session_row), False


def _create_contract_revision(
    session,
    *,
    workspace_id: str,
    source_session_id: str,
    contract: ScenarioContractContent,
    status: str = ContractRevisionStatus.draft.value,
) -> ScenarioContractRevisionRow:
    # Contract revision numbers are scenario-wide, not session-wide. Lock the
    # owning workspace so two task sessions cannot both allocate the same next
    # revision number.
    session.scalar(select(WorkspaceRow).where(WorkspaceRow.id == workspace_id).with_for_update())
    latest = session.scalar(
        select(ScenarioContractRevisionRow)
        .where(ScenarioContractRevisionRow.workspace_id == workspace_id)
        .order_by(ScenarioContractRevisionRow.revision.desc())
        .limit(1)
    )
    contract_json = contract.model_dump(mode="json")
    if latest is not None and latest.contract_json == contract_json:
        return latest
    if latest is not None and latest.status == ContractRevisionStatus.draft.value:
        latest.status = ContractRevisionStatus.superseded.value
    row = ScenarioContractRevisionRow(
        id=str(uuid4()),
        workspace_id=workspace_id,
        revision=(latest.revision + 1) if latest else 1,
        status=status,
        contract_json=contract_json,
        source_session_id=source_session_id,
        created_at=_now(),
    )
    session.add(row)
    session.flush()
    return row


def commit_agent_result(
    session_id: str,
    *,
    expected_business_revision: int,
    expected_checkpoint_id: str | None,
    produced_checkpoint_id: str | None,
    result: CoCreationAgentResult,
) -> CoCreationSessionRecord:
    if not produced_checkpoint_id:
        raise RepositoryConflict("successful co-creation result must have a produced checkpoint")
    now = _now()
    with session_scope() as session:
        session_row = session.scalar(select(CoCreationSessionRow).where(CoCreationSessionRow.id == session_id).with_for_update())
        if session_row is None:
            raise KeyError(session_id)
        if (
            session_row.business_revision != expected_business_revision
            or session_row.accepted_checkpoint_id != expected_checkpoint_id
        ):
            raise StaleProjection("co-creation business branch is stale")
        projection = dict(session_row.projection_json or {})
        projection["delta"] = result.delta.model_dump(mode="json")
        projection["blocking_gaps"] = [gap.model_dump(mode="json") for gap in result.blocking_gaps]
        if result.contract is not None:
            projection["contract"] = result.contract.model_dump(mode="json")
            contract_row = _create_contract_revision(
                session,
                workspace_id=session_row.workspace_id,
                source_session_id=session_id,
                contract=result.contract,
            )
            session_row.contract_revision_id = contract_row.id
        if result.judgment_package is not None:
            projection["judgment_package"] = result.judgment_package.model_dump(mode="json")
        session_row.projection_json = projection
        session_row.accepted_checkpoint_id = produced_checkpoint_id
        session_row.business_revision += 1
        session_row.updated_at = now
        session_row.pending_interrupt_json = None
        answered = session.scalar(
            select(CoCreationTurnRow)
            .where(
                CoCreationTurnRow.session_id == session_id,
                CoCreationTurnRow.status == "answered_pending_resume",
            )
            .order_by(CoCreationTurnRow.turn_revision.desc())
            .limit(1)
        )
        if answered is not None:
            answered.delta_json = result.delta.model_dump(mode="json")
            answered.produced_checkpoint_id = produced_checkpoint_id
            answered.result_hash = result_hash(result)
            answered.status = "projected"
        if result.phase == "question":
            if result.question is None:
                raise RepositoryConflict("question result has no question")
            turn_revision = session_row.current_turn_revision + 1
            session.add(
                CoCreationTurnRow(
                    id=str(uuid4()),
                    session_id=session_id,
                    turn_revision=turn_revision,
                    question_id=result.question.id,
                    question_json=result.question.model_dump(mode="json"),
                    answer_text=None,
                    answer_command_id=None,
                    delta_json=result.delta.model_dump(mode="json"),
                    base_checkpoint_id=expected_checkpoint_id,
                    produced_checkpoint_id=produced_checkpoint_id,
                    result_hash=result_hash(result),
                    status="pending",
                    created_at=now,
                )
            )
            session_row.current_turn_revision = turn_revision
            session_row.pending_interrupt_json = result.question.model_dump(mode="json")
            session_row.status = CoCreationStatus.waiting_for_teacher.value
        else:
            session_row.status = CoCreationStatus.ready_for_confirmation.value
        session.flush()
        return _session(session_row)


def mark_continuity_reset(session_id: str, reason: str) -> CoCreationSessionRecord:
    with session_scope() as session:
        row = session.scalar(select(CoCreationSessionRow).where(CoCreationSessionRow.id == session_id).with_for_update())
        if row is None:
            raise KeyError(session_id)
        row.status = CoCreationStatus.continuity_reset.value
        row.pending_interrupt_json = {"reason": reason}
        row.continuity_reset_reason = reason
        row.updated_at = _now()
        session.flush()
        return _session(row)


def create_continuity_reset(
    session_id: str,
    *,
    command_id: str,
    reason: str,
    ai_profile_version: str | None = None,
    graph_schema_version: str | None = None,
) -> CoCreationSessionRecord:
    now = _now()
    with session_scope() as session:
        old = session.scalar(select(CoCreationSessionRow).where(CoCreationSessionRow.id == session_id).with_for_update())
        if old is None:
            raise KeyError(session_id)
        pending = old.pending_interrupt_json or {}
        if old.status == CoCreationStatus.continuity_reset.value and pending.get("reset_command_id") == command_id:
            new_id = pending.get("new_session_id")
            existing = session.get(CoCreationSessionRow, new_id) if new_id else None
            if existing is not None:
                return _session(existing)
        if old.status == CoCreationStatus.continuity_reset.value and pending.get("new_session_id"):
            raise RepositoryConflict("continuity reset already created a replacement session")
        if old.status != CoCreationStatus.continuity_reset.value:
            raise RepositoryConflict("continuity reset is not required for this session")
        new_row = CoCreationSessionRow(
            id=str(uuid4()),
            workspace_id=old.workspace_id,
            task_package_id=old.task_package_id,
            stable_thread_key=f"cocreation-{uuid4()}",
            command_id=f"reset-{uuid4()}",
            kind=old.kind,
            purpose="continuity_reset",
            initialization_only=bool(old.initialization_only),
            status=CoCreationStatus.queued.value,
            business_revision=0,
            current_turn_revision=0,
            accepted_checkpoint_id=None,
            pending_interrupt_json=None,
            projection_json=dict(old.projection_json) if old.projection_json else None,
            contract_revision_id=old.contract_revision_id,
            confirmation_command_id=None,
            continuity_reset_from_id=old.id,
            continuity_reset_to_id=None,
            continuity_reset_reason=reason,
            ai_profile_version=ai_profile_version or old.ai_profile_version,
            graph_schema_version=graph_schema_version or old.graph_schema_version,
            created_at=now,
            updated_at=now,
        )
        session.add(new_row)
        old.pending_interrupt_json = {
            "reason": reason,
            "reset_command_id": command_id,
            "new_session_id": new_row.id,
        }
        old.continuity_reset_to_id = new_row.id
        old.continuity_reset_reason = reason
        old.updated_at = now
        session.flush()
        return _session(new_row)


def mark_failed(session_id: str, error: dict[str, Any]) -> CoCreationSessionRecord:
    with session_scope() as session:
        row = session.scalar(select(CoCreationSessionRow).where(CoCreationSessionRow.id == session_id).with_for_update())
        if row is None:
            raise KeyError(session_id)
        row.status = CoCreationStatus.failed.value
        row.pending_interrupt_json = {"error": {"code": str(error.get("code", "AI_FAILED")), "message": "共创暂时未完成。"}}
        row.updated_at = _now()
        session.flush()
        return _session(row)


def mark_projection_pending(session_id: str, produced_checkpoint_id: str | None) -> CoCreationSessionRecord:
    with session_scope() as session:
        row = session.scalar(select(CoCreationSessionRow).where(CoCreationSessionRow.id == session_id).with_for_update())
        if row is None:
            raise KeyError(session_id)
        row.status = CoCreationStatus.projection_pending.value
        if produced_checkpoint_id:
            row.pending_interrupt_json = {"produced_checkpoint_id": produced_checkpoint_id}
        row.updated_at = _now()
        session.flush()
        return _session(row)


def queue_retry(session_id: str, *, expected_business_revision: int) -> CoCreationSessionRecord | None:
    with session_scope() as session:
        row = session.scalar(select(CoCreationSessionRow).where(CoCreationSessionRow.id == session_id).with_for_update())
        if row is None:
            raise KeyError(session_id)
        if row.business_revision != expected_business_revision:
            return None
        if row.status not in {CoCreationStatus.failed.value, CoCreationStatus.projection_pending.value}:
            raise RepositoryConflict("co-creation is not retryable")
        row.status = CoCreationStatus.processing.value
        row.updated_at = _now()
        session.flush()
        return _session(row)


def confirm_contract(
    session_id: str,
    *,
    expected_business_revision: int,
    confirmed_by: str,
    command_id: str,
) -> CoCreationSessionRecord:
    now = _now()
    with session_scope() as session:
        row = session.scalar(select(CoCreationSessionRow).where(CoCreationSessionRow.id == session_id).with_for_update())
        if row is None:
            raise KeyError(session_id)
        if row.kind != CoCreationKind.scenario_contract.value:
            raise RepositoryConflict("session is not a scenario contract session")
        if row.status == CoCreationStatus.confirmed.value:
            if row.confirmation_command_id == command_id:
                return _session(row)
            raise RepositoryConflict("contract confirmation already decided")
        if row.business_revision != expected_business_revision:
            raise StaleProjection("contract session has changed")
        if row.status != CoCreationStatus.ready_for_confirmation.value:
            raise RepositoryConflict("contract is not ready for confirmation")
        projection = row.projection_json or {}
        contract = projection.get("contract")
        if not contract:
            raise RepositoryConflict("contract projection is incomplete")
        contract_row = session.get(ScenarioContractRevisionRow, row.contract_revision_id) if row.contract_revision_id else None
        if contract_row is None:
            contract_row = _create_contract_revision(
                session,
                workspace_id=row.workspace_id,
                source_session_id=session_id,
                contract=ScenarioContractContent.model_validate(contract),
                status=ContractRevisionStatus.confirmed.value,
            )
        else:
            contract_row.status = ContractRevisionStatus.confirmed.value
            contract_row.confirmed_by = confirmed_by
            contract_row.confirmed_at = now
        task = session.get(TaskPackageRow, row.task_package_id)
        if task is not None:
            task.contract_revision_id = contract_row.id
            task.revision += 1
            task.updated_at = now
        row.status = CoCreationStatus.confirmed.value
        row.business_revision += 1
        row.updated_at = now
        row.contract_revision_id = contract_row.id
        row.confirmation_command_id = command_id
        session.flush()
        return _session(row)


def confirm_judgment(
    session_id: str,
    *,
    expected_business_revision: int,
    confirmed_by: str,
    command_id: str,
) -> CoCreationSessionRecord:
    now = _now()
    with session_scope() as session:
        row = session.scalar(select(CoCreationSessionRow).where(CoCreationSessionRow.id == session_id).with_for_update())
        if row is None:
            raise KeyError(session_id)
        if row.kind != CoCreationKind.task_judgment.value:
            raise RepositoryConflict("session is not a task judgment session")
        if row.status == CoCreationStatus.confirmed.value:
            if row.confirmation_command_id == command_id:
                return _session(row)
            raise RepositoryConflict("judgment confirmation already decided")
        if row.business_revision != expected_business_revision:
            raise StaleProjection("judgment session has changed")
        if row.status != CoCreationStatus.ready_for_confirmation.value:
            raise RepositoryConflict("judgment package is not ready for confirmation")
        package = (row.projection_json or {}).get("judgment_package")
        if not package:
            raise RepositoryConflict("judgment package is incomplete")
        judgment = JudgmentPackageContent.model_validate(package)
        if any(gap.blocking for gap in judgment.blocking_gaps):
            raise RepositoryConflict("blocking gaps must be resolved before confirmation")
        task = session.get(TaskPackageRow, row.task_package_id)
        if task is None:
            raise KeyError(row.task_package_id)
        task.judgment_package_json = judgment.model_dump(mode="json")
        task.draft_json = {
            "title": task.title,
            "task_package_id": task.id,
            "contract_revision_id": task.contract_revision_id,
            "reference_results": judgment.reference_results,
            "output_requirements": judgment.task_specific_rules,
            "minimum_quality_line": judgment.minimum_quality_line,
            "hard_gates": judgment.hard_gates,
        }
        task.confirmed_by = confirmed_by
        task.confirmed_at = now
        task.revision += 1
        task.updated_at = now
        row.status = CoCreationStatus.confirmed.value
        row.business_revision += 1
        row.updated_at = now
        row.confirmation_command_id = command_id
        session.flush()
        return _session(row)


def create_feedback(task_package_id: str, source_id: str, text: str, confirmed_by: str | None = None) -> TeacherFeedbackRecord:
    row = TeacherFeedbackRow(
        id=str(uuid4()),
        task_package_id=task_package_id,
        source_id=source_id,
        text=text,
        scope="question_only",
        confirmed_by=confirmed_by,
        created_at=_now(),
    )
    with session_scope() as session:
        session.add(row)
        session.flush()
        return _feedback(row)


def create_promotion(task_package_id: str, workspace_id: str, source_feedback_id: str, proposed_text: str) -> PromotionProposalRecord:
    with session_scope() as session:
        feedback = session.get(TeacherFeedbackRow, source_feedback_id)
        if feedback is None or feedback.task_package_id != task_package_id:
            raise RepositoryConflict("feedback does not belong to the task package")
        row = StandardPromotionProposalRow(
            id=str(uuid4()),
            workspace_id=workspace_id,
            source_feedback_id=source_feedback_id,
            proposed_text=proposed_text,
            status="pending",
            created_at=_now(),
        )
        session.add(row)
        session.flush()
        return _promotion(row)


def get_promotion(proposal_id: str) -> PromotionProposalRecord | None:
    with session_scope() as session:
        row = session.get(StandardPromotionProposalRow, proposal_id)
        return _promotion(row) if row else None


def decide_promotion(proposal_id: str, decision: str, *, confirmed_by: str | None = None) -> PromotionProposalRecord:
    with session_scope() as session:
        row = session.get(StandardPromotionProposalRow, proposal_id)
        if row is None:
            raise KeyError(proposal_id)
        if row.status != "pending":
            if row.status == decision:
                return _promotion(row)
            raise RepositoryConflict("promotion proposal already decided")
        if decision == "approve":
            feedback = session.get(TeacherFeedbackRow, row.source_feedback_id)
            if feedback is None:
                raise RepositoryConflict("promotion feedback is missing")
            latest = session.scalar(
                select(ScenarioContractRevisionRow)
                .where(
                    ScenarioContractRevisionRow.workspace_id == row.workspace_id,
                    ScenarioContractRevisionRow.status == ContractRevisionStatus.confirmed.value,
                )
                .order_by(ScenarioContractRevisionRow.revision.desc())
                .limit(1)
            )
            if latest is None:
                raise RepositoryConflict("there is no confirmed contract to promote into")
            contract = ScenarioContractContent.model_validate(latest.contract_json)
            if row.proposed_text not in contract.hard_gates:
                updated_contract = contract.model_copy(update={"hard_gates": [*contract.hard_gates, row.proposed_text]})
                new_revision = _create_contract_revision(
                    session,
                    workspace_id=row.workspace_id,
                    source_session_id=None,
                    contract=updated_contract,
                    status=ContractRevisionStatus.confirmed.value,
                )
                new_revision.confirmed_by = confirmed_by
                new_revision.confirmed_at = _now()
        row.status = decision
        if confirmed_by:
            feedback = session.get(TeacherFeedbackRow, row.source_feedback_id)
            if feedback is not None:
                feedback.confirmed_by = confirmed_by
        row.decided_at = _now()
        session.flush()
        return _promotion(row)
