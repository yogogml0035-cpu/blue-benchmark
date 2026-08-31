from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.lib.database import as_utc, session_scope
from app.lib.database.models import (
    AgentRunAttemptRow,
    ContractImpactReviewRow,
    CoverageSnapshotRow,
    EvaluationSetVersionRow,
    WorkingSetCommandRow,
    WorkingSetDraftRow,
    WorkingSetMemberRow,
    WorkspaceRow,
    OperationJobRow,
)

from app.features.evaluation_sets.schemas import (
    BatchImpactReviewRequest,
    CoverageConfirmationRequest,
    ImpactReviewDecisionRequest,
    MemberMutationRequest,
    MemberStatus,
    ImpactReviewStatus,
)


class RepositoryConflict(RuntimeError):
    pass


class StaleDraft(RepositoryConflict):
    pass


@dataclass(frozen=True, slots=True)
class WorkingSetDraftRecord:
    id: str
    workspace_id: str
    base_version_id: str | None
    revision: int
    contract_revision_id: str
    status: str
    freeze_intent: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime
    discarded_at: datetime | None


@dataclass(frozen=True, slots=True)
class WorkingSetMemberRecord:
    id: str
    draft_id: str
    task_package_id: str
    task_package_revision: int
    contract_revision_id: str
    status: str
    review_status: str
    deterministic_conflicts: list[str]
    ai_suggestions: list[str]
    teacher_note: str | None
    sort_order: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ContractImpactReviewRecord:
    id: str
    draft_id: str
    task_package_id: str
    from_contract_revision_id: str | None
    to_contract_revision_id: str
    status: str
    deterministic_conflicts: list[str]
    ai_suggestions: list[str]
    teacher_note: str | None
    confirmed_by: str | None
    confirmed_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class CoverageSnapshotRecord:
    id: str
    draft_id: str
    draft_revision: int
    snapshot: dict[str, Any]
    risk_confirmed: bool
    risk_confirmation_note: str | None
    confirmed_by: str | None
    confirmed_at: datetime | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class EvaluationSetVersionRecord:
    id: str
    workspace_id: str
    version_number: int
    draft_id: str
    contract_revision_id: str
    schema_version: str
    freeze_command_id: str
    manifest_key: str
    runtime_key: str
    judge_key: str
    provenance_key: str
    package_key: str
    manifest_sha256: str
    runtime_sha256: str
    judge_sha256: str
    provenance_sha256: str
    overall_sha256: str
    risk_confirmation: dict[str, Any]
    frozen_by: str
    frozen_at: datetime
    created_at: datetime


def _now() -> datetime:
    return datetime.now(timezone.utc)


def payload_hash(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _recover_duplicate_command(session, draft_id: str, command_id: str, digest: str) -> WorkingSetDraftRecord | None:
    session.rollback()
    command = session.scalar(
        select(WorkingSetCommandRow).where(
            WorkingSetCommandRow.draft_id == draft_id,
            WorkingSetCommandRow.command_id == command_id,
        )
    )
    if command is None:
        return None
    if command.payload_hash != digest:
        raise RepositoryConflict("working-set command payload changed")
    draft = session.get(WorkingSetDraftRow, draft_id)
    return _draft(draft) if draft else None


def _draft(row: WorkingSetDraftRow) -> WorkingSetDraftRecord:
    return WorkingSetDraftRecord(
        id=row.id,
        workspace_id=row.workspace_id,
        base_version_id=row.base_version_id,
        revision=row.revision,
        contract_revision_id=row.contract_revision_id,
        status=row.status,
        freeze_intent=dict(row.freeze_intent_json) if row.freeze_intent_json else None,
        created_at=as_utc(row.created_at),
        updated_at=as_utc(row.updated_at),
        discarded_at=as_utc(row.discarded_at) if row.discarded_at else None,
    )


def _member(row: WorkingSetMemberRow) -> WorkingSetMemberRecord:
    return WorkingSetMemberRecord(
        id=row.id,
        draft_id=row.draft_id,
        task_package_id=row.task_package_id,
        task_package_revision=row.task_package_revision,
        contract_revision_id=row.contract_revision_id,
        status=row.status,
        review_status=row.review_status,
        deterministic_conflicts=list(row.deterministic_conflicts_json or []),
        ai_suggestions=list(row.ai_suggestions_json or []),
        teacher_note=row.teacher_note,
        sort_order=row.sort_order,
        created_at=as_utc(row.created_at),
        updated_at=as_utc(row.updated_at),
    )


def _review(row: ContractImpactReviewRow) -> ContractImpactReviewRecord:
    return ContractImpactReviewRecord(
        id=row.id,
        draft_id=row.draft_id,
        task_package_id=row.task_package_id,
        from_contract_revision_id=row.from_contract_revision_id,
        to_contract_revision_id=row.to_contract_revision_id,
        status=row.status,
        deterministic_conflicts=list(row.deterministic_conflicts_json or []),
        ai_suggestions=list(row.ai_suggestions_json or []),
        teacher_note=row.teacher_note,
        confirmed_by=row.confirmed_by,
        confirmed_at=as_utc(row.confirmed_at) if row.confirmed_at else None,
        created_at=as_utc(row.created_at),
        updated_at=as_utc(row.updated_at),
    )


def _coverage(row: CoverageSnapshotRow) -> CoverageSnapshotRecord:
    return CoverageSnapshotRecord(
        id=row.id,
        draft_id=row.draft_id,
        draft_revision=row.draft_revision,
        snapshot=dict(row.snapshot_json),
        risk_confirmed=bool(row.risk_confirmed),
        risk_confirmation_note=row.risk_confirmation_note,
        confirmed_by=row.confirmed_by,
        confirmed_at=as_utc(row.confirmed_at) if row.confirmed_at else None,
        created_at=as_utc(row.created_at),
    )


def _version(row: EvaluationSetVersionRow) -> EvaluationSetVersionRecord:
    return EvaluationSetVersionRecord(
        id=row.id,
        workspace_id=row.workspace_id,
        version_number=row.version_number,
        draft_id=row.draft_id,
        contract_revision_id=row.contract_revision_id,
        schema_version=row.schema_version,
        freeze_command_id=row.freeze_command_id,
        manifest_key=row.manifest_key,
        runtime_key=row.runtime_key,
        judge_key=row.judge_key,
        provenance_key=row.provenance_key,
        package_key=row.package_key,
        manifest_sha256=row.manifest_sha256,
        runtime_sha256=row.runtime_sha256,
        judge_sha256=row.judge_sha256,
        provenance_sha256=row.provenance_sha256,
        overall_sha256=row.overall_sha256,
        risk_confirmation=dict(row.risk_confirmation_json or {}),
        frozen_by=row.frozen_by,
        frozen_at=as_utc(row.frozen_at),
        created_at=as_utc(row.created_at),
    )


def get_draft(draft_id: str) -> WorkingSetDraftRecord | None:
    with session_scope() as session:
        row = session.get(WorkingSetDraftRow, draft_id)
        return _draft(row) if row else None


def get_active_draft(workspace_id: str) -> WorkingSetDraftRecord | None:
    with session_scope() as session:
        row = session.scalar(
            select(WorkingSetDraftRow).where(
                WorkingSetDraftRow.workspace_id == workspace_id,
                WorkingSetDraftRow.active_key == workspace_id,
                WorkingSetDraftRow.status == "active",
            )
        )
        return _draft(row) if row else None


def get_draft_by_create_command(
    workspace_id: str,
    command_id: str,
) -> WorkingSetDraftRecord | None:
    """Find a draft created by this command, including discarded drafts."""

    with session_scope() as session:
        rows = session.execute(
            select(WorkingSetDraftRow, WorkingSetCommandRow)
            .join(WorkingSetCommandRow, WorkingSetCommandRow.draft_id == WorkingSetDraftRow.id)
            .where(
                WorkingSetDraftRow.workspace_id == workspace_id,
                WorkingSetCommandRow.command_id == command_id,
            )
            .order_by(WorkingSetCommandRow.created_at.desc(), WorkingSetCommandRow.id.desc())
        ).all()
        for draft, command in rows:
            if (command.result_json or {}).get("draft_id") == draft.id:
                return _draft(draft)
    return None


def get_member(draft_id: str, task_package_id: str) -> WorkingSetMemberRecord | None:
    with session_scope() as session:
        row = session.scalar(
            select(WorkingSetMemberRow).where(
                WorkingSetMemberRow.draft_id == draft_id,
                WorkingSetMemberRow.task_package_id == task_package_id,
            )
        )
        return _member(row) if row else None


def list_members(draft_id: str, *, included_only: bool = False) -> list[WorkingSetMemberRecord]:
    with session_scope() as session:
        statement = select(WorkingSetMemberRow).where(WorkingSetMemberRow.draft_id == draft_id)
        if included_only:
            statement = statement.where(WorkingSetMemberRow.status == MemberStatus.included.value)
        rows = session.scalars(statement.order_by(WorkingSetMemberRow.sort_order, WorkingSetMemberRow.id)).all()
        return [_member(row) for row in rows]


def list_reviews(draft_id: str) -> list[ContractImpactReviewRecord]:
    with session_scope() as session:
        rows = session.scalars(
            select(ContractImpactReviewRow)
            .where(ContractImpactReviewRow.draft_id == draft_id)
            .order_by(ContractImpactReviewRow.created_at, ContractImpactReviewRow.id)
        ).all()
        return [_review(row) for row in rows]


def get_latest_coverage(draft_id: str) -> CoverageSnapshotRecord | None:
    with session_scope() as session:
        row = session.scalar(
            select(CoverageSnapshotRow)
            .where(CoverageSnapshotRow.draft_id == draft_id)
            .order_by(CoverageSnapshotRow.created_at.desc(), CoverageSnapshotRow.id.desc())
            .limit(1)
        )
        return _coverage(row) if row else None


def get_version(version_id: str) -> EvaluationSetVersionRecord | None:
    with session_scope() as session:
        row = session.get(EvaluationSetVersionRow, version_id)
        return _version(row) if row else None


def get_version_by_freeze_command(workspace_id: str, command_id: str) -> EvaluationSetVersionRecord | None:
    with session_scope() as session:
        row = session.scalar(
            select(EvaluationSetVersionRow).where(
                EvaluationSetVersionRow.workspace_id == workspace_id,
                EvaluationSetVersionRow.freeze_command_id == command_id,
            )
        )
        return _version(row) if row else None


def list_versions(workspace_id: str) -> list[EvaluationSetVersionRecord]:
    with session_scope() as session:
        rows = session.scalars(
            select(EvaluationSetVersionRow)
            .where(EvaluationSetVersionRow.workspace_id == workspace_id)
            .order_by(EvaluationSetVersionRow.version_number.desc())
        ).all()
        return [_version(row) for row in rows]


def create_draft(
    *,
    workspace_id: str,
    contract_revision_id: str,
    base_version_id: str | None,
    base_members: list[tuple[str, int, str]],
    command_id: str,
) -> WorkingSetDraftRecord:
    now = _now()
    row = WorkingSetDraftRow(
        id=str(uuid4()),
        workspace_id=workspace_id,
        base_version_id=base_version_id,
        active_key=workspace_id,
        revision=0,
        contract_revision_id=contract_revision_id,
        status="active",
        freeze_intent_json=None,
        created_at=now,
        updated_at=now,
        discarded_at=None,
    )
    try:
        with session_scope() as session:
            session.add(row)
            session.flush()
            for order, (task_id, task_revision, task_contract_id) in enumerate(base_members):
                member = WorkingSetMemberRow(
                    id=str(uuid4()),
                    draft_id=row.id,
                    task_package_id=task_id,
                    task_package_revision=task_revision,
                    contract_revision_id=task_contract_id,
                    status=MemberStatus.included.value,
                    review_status=(
                        ImpactReviewStatus.not_required.value
                        if task_contract_id == contract_revision_id
                        else ImpactReviewStatus.review_required.value
                    ),
                    deterministic_conflicts_json=([] if task_contract_id == contract_revision_id else ["题引用了不同的场景标准修订。"]),
                    ai_suggestions_json=[],
                    sort_order=order,
                    created_at=now,
                    updated_at=now,
                )
                session.add(member)
                if task_contract_id != contract_revision_id:
                    session.add(
                        ContractImpactReviewRow(
                            id=str(uuid4()),
                            draft_id=row.id,
                            task_package_id=task_id,
                            from_contract_revision_id=task_contract_id,
                            to_contract_revision_id=contract_revision_id,
                            status=ImpactReviewStatus.review_required.value,
                            deterministic_conflicts_json=["题引用了不同的场景标准修订。"],
                            ai_suggestions_json=["逐题核对新场景标准与本题判定依据。"],
                            created_at=now,
                            updated_at=now,
                        )
                    )
            session.add(
                WorkingSetCommandRow(
                    id=str(uuid4()),
                    draft_id=row.id,
                    command_id=command_id,
                    payload_hash=payload_hash({"contract_revision_id": contract_revision_id, "base_version_id": base_version_id, "members": base_members}),
                    result_json={"draft_id": row.id},
                    created_at=now,
                )
            )
            session.flush()
            return _draft(row)
    except IntegrityError:
        existing = get_active_draft(workspace_id)
        if existing is not None:
            return existing
        raise


def mutate_member(
    draft_id: str,
    *,
    payload: MemberMutationRequest,
    contract_revision_id: str,
    task_contract_revision_id: str | None = None,
    deterministic_conflicts: list[str],
    ai_suggestions: list[str] | None = None,
) -> WorkingSetDraftRecord:
    now = _now()
    digest = payload_hash(payload.model_dump(mode="json"))
    with session_scope() as session:
        draft = session.scalar(select(WorkingSetDraftRow).where(WorkingSetDraftRow.id == draft_id).with_for_update())
        if draft is None:
            raise KeyError(draft_id)
        prior_command = session.scalar(
            select(WorkingSetCommandRow).where(
                WorkingSetCommandRow.draft_id == draft_id,
                WorkingSetCommandRow.command_id == payload.command_id,
            )
        )
        if prior_command is not None:
            if prior_command.payload_hash != digest:
                raise RepositoryConflict("working-set command payload changed")
            return _draft(draft)
        if draft.status != "active":
            raise RepositoryConflict("working-set draft is not editable")
        if draft.revision != payload.draft_revision:
            raise StaleDraft("working-set draft revision changed")
        member = session.scalar(
            select(WorkingSetMemberRow).where(
                WorkingSetMemberRow.draft_id == draft_id,
                WorkingSetMemberRow.task_package_id == payload.task_package_id,
            )
        )
        if member is None:
            if payload.action != "include":
                raise RepositoryConflict("task is not a working-set member")
            member = WorkingSetMemberRow(
                id=str(uuid4()),
                draft_id=draft_id,
                task_package_id=payload.task_package_id,
                task_package_revision=payload.task_package_revision,
                contract_revision_id=task_contract_revision_id or contract_revision_id,
                status=MemberStatus.included.value,
                review_status=(ImpactReviewStatus.review_required.value if deterministic_conflicts else ImpactReviewStatus.not_required.value),
                deterministic_conflicts_json=list(deterministic_conflicts),
                ai_suggestions_json=list(ai_suggestions or []),
                sort_order=(session.scalar(select(func.max(WorkingSetMemberRow.sort_order)).where(WorkingSetMemberRow.draft_id == draft_id)) or -1) + 1,
                created_at=now,
                updated_at=now,
            )
            session.add(member)
        else:
            member.task_package_revision = payload.task_package_revision
            member.contract_revision_id = task_contract_revision_id or member.contract_revision_id or contract_revision_id
            member.status = MemberStatus.included.value if payload.action == "include" else MemberStatus.removed.value
            member.review_status = (
                ImpactReviewStatus.review_required.value
                if payload.action == "include" and deterministic_conflicts
                else ImpactReviewStatus.not_required.value
            )
            member.deterministic_conflicts_json = list(deterministic_conflicts)
            member.ai_suggestions_json = list(ai_suggestions or [])
            member.teacher_note = None
            member.updated_at = now
        if payload.action == "include" and deterministic_conflicts:
            review = session.scalar(
                select(ContractImpactReviewRow).where(
                    ContractImpactReviewRow.draft_id == draft_id,
                    ContractImpactReviewRow.task_package_id == payload.task_package_id,
                )
            )
            if review is None:
                session.add(
                    ContractImpactReviewRow(
                        id=str(uuid4()),
                        draft_id=draft_id,
                        task_package_id=payload.task_package_id,
                        from_contract_revision_id=task_contract_revision_id,
                        to_contract_revision_id=contract_revision_id,
                        status=ImpactReviewStatus.review_required.value,
                        deterministic_conflicts_json=list(deterministic_conflicts),
                        ai_suggestions_json=list(ai_suggestions or []),
                        created_at=now,
                        updated_at=now,
                    )
                )
            else:
                review.status = ImpactReviewStatus.review_required.value
                review.deterministic_conflicts_json = list(deterministic_conflicts)
                review.ai_suggestions_json = list(ai_suggestions or [])
                review.updated_at = now
        draft.revision += 1
        draft.updated_at = now
        session.add(
            WorkingSetCommandRow(
                id=str(uuid4()),
                draft_id=draft_id,
                command_id=payload.command_id,
                payload_hash=digest,
                result_json={"task_package_id": payload.task_package_id, "action": payload.action},
                created_at=now,
            )
        )
        try:
            session.flush()
        except IntegrityError:
            recovered = _recover_duplicate_command(session, draft_id, payload.command_id, digest)
            if recovered is not None:
                return recovered
            raise RepositoryConflict("working-set was updated concurrently")
        return _draft(draft)


def decide_impact(
    draft_id: str,
    task_package_id: str,
    *,
    payload: ImpactReviewDecisionRequest,
    confirmed_by: str,
    current_task_revision: int | None = None,
) -> WorkingSetDraftRecord:
    now = _now()
    digest = payload_hash(payload.model_dump(mode="json"))
    with session_scope() as session:
        draft = session.scalar(select(WorkingSetDraftRow).where(WorkingSetDraftRow.id == draft_id).with_for_update())
        if draft is None:
            raise KeyError(draft_id)
        command = session.scalar(select(WorkingSetCommandRow).where(WorkingSetCommandRow.draft_id == draft_id, WorkingSetCommandRow.command_id == payload.command_id))
        if command is not None:
            if command.payload_hash != digest:
                raise RepositoryConflict("impact review command payload changed")
            return _draft(draft)
        if draft.status != "active" or draft.revision != payload.draft_revision:
            raise StaleDraft("working-set draft revision changed")
        member = session.scalar(select(WorkingSetMemberRow).where(WorkingSetMemberRow.draft_id == draft_id, WorkingSetMemberRow.task_package_id == task_package_id))
        if member is None or member.status != MemberStatus.included.value:
            raise RepositoryConflict("task is not included in the draft")
        if payload.decision == "confirm_no_conflict" and member.deterministic_conflicts_json:
            raise RepositoryConflict("deterministic contract conflicts require individual review")
        if payload.decision == "reviewed" and member.deterministic_conflicts_json and not (payload.note or "").strip():
            raise RepositoryConflict("individual impact review requires a teacher note")
        review = session.scalar(select(ContractImpactReviewRow).where(ContractImpactReviewRow.draft_id == draft_id, ContractImpactReviewRow.task_package_id == task_package_id))
        if review is None:
            review = ContractImpactReviewRow(
                id=str(uuid4()),
                draft_id=draft_id,
                task_package_id=task_package_id,
                from_contract_revision_id=member.contract_revision_id,
                to_contract_revision_id=draft.contract_revision_id,
                status=ImpactReviewStatus.reviewed.value,
                deterministic_conflicts_json=list(member.deterministic_conflicts_json),
                ai_suggestions_json=list(member.ai_suggestions_json),
                created_at=now,
                updated_at=now,
            )
            session.add(review)
        review.status = ImpactReviewStatus.no_conflict_confirmed.value if payload.decision == "confirm_no_conflict" else ImpactReviewStatus.reviewed.value
        review.teacher_note = payload.note
        review.confirmed_by = confirmed_by
        review.confirmed_at = now
        review.updated_at = now
        member.review_status = review.status
        if current_task_revision is not None:
            member.task_package_revision = current_task_revision
        member.teacher_note = payload.note
        member.updated_at = now
        draft.revision += 1
        draft.updated_at = now
        session.add(WorkingSetCommandRow(id=str(uuid4()), draft_id=draft_id, command_id=payload.command_id, payload_hash=digest, result_json={"task_package_id": task_package_id, "status": review.status}, created_at=now))
        try:
            session.flush()
        except IntegrityError:
            recovered = _recover_duplicate_command(session, draft_id, payload.command_id, digest)
            if recovered is not None:
                return recovered
            raise RepositoryConflict("impact review was updated concurrently")
        return _draft(draft)


def confirm_no_conflict_batch(draft_id: str, *, payload: BatchImpactReviewRequest, confirmed_by: str) -> WorkingSetDraftRecord:
    now = _now()
    digest = payload_hash(payload.model_dump(mode="json"))
    with session_scope() as session:
        draft = session.scalar(select(WorkingSetDraftRow).where(WorkingSetDraftRow.id == draft_id).with_for_update())
        if draft is None:
            raise KeyError(draft_id)
        command = session.scalar(select(WorkingSetCommandRow).where(WorkingSetCommandRow.draft_id == draft_id, WorkingSetCommandRow.command_id == payload.command_id))
        if command is not None:
            if command.payload_hash != digest:
                raise RepositoryConflict("impact review command payload changed")
            return _draft(draft)
        if draft.status != "active" or draft.revision != payload.draft_revision:
            raise StaleDraft("working-set draft revision changed")
        members = session.scalars(select(WorkingSetMemberRow).where(WorkingSetMemberRow.draft_id == draft_id, WorkingSetMemberRow.status == MemberStatus.included.value)).all()
        if any(row.deterministic_conflicts_json for row in members):
            raise RepositoryConflict("deterministic contract conflicts require individual review")
        reviews = session.scalars(select(ContractImpactReviewRow).where(ContractImpactReviewRow.draft_id == draft_id)).all()
        for member in members:
            member.review_status = ImpactReviewStatus.no_conflict_confirmed.value
            member.teacher_note = payload.note
            member.updated_at = now
        for review in reviews:
            review.status = ImpactReviewStatus.no_conflict_confirmed.value
            review.teacher_note = payload.note
            review.confirmed_by = confirmed_by
            review.confirmed_at = now
            review.updated_at = now
        draft.revision += 1
        draft.updated_at = now
        session.add(WorkingSetCommandRow(id=str(uuid4()), draft_id=draft_id, command_id=payload.command_id, payload_hash=digest, result_json={"status": "no_conflict_confirmed"}, created_at=now))
        try:
            session.flush()
        except IntegrityError:
            recovered = _recover_duplicate_command(session, draft_id, payload.command_id, digest)
            if recovered is not None:
                return recovered
            raise RepositoryConflict("impact review was updated concurrently")
        return _draft(draft)


def save_coverage(
    draft_id: str,
    *,
    draft_revision: int,
    snapshot: dict[str, Any],
    operation_job_id: str | None = None,
    operation_attempt: int | None = None,
    worker_id: str | None = None,
) -> CoverageSnapshotRecord:
    now = _now()
    with session_scope() as session:
        attempt = None
        if operation_job_id is not None:
            if operation_attempt is None or not worker_id:
                raise StaleDraft("coverage operation identity is incomplete")
            operation = session.scalar(
                select(OperationJobRow).where(OperationJobRow.id == operation_job_id).with_for_update()
            )
            if (
                operation is None
                or operation.status != "running"
                or operation.worker_id != worker_id
                or operation.attempts != operation_attempt
            ):
                raise StaleDraft("coverage operation attempt is stale")
            attempt = session.scalar(
                select(AgentRunAttemptRow)
                .where(
                    AgentRunAttemptRow.operation_job_id == operation_job_id,
                    AgentRunAttemptRow.attempt_number == operation_attempt,
                )
                .with_for_update()
            )
            if attempt is None:
                raise StaleDraft("coverage operation attempt is missing")
        draft = session.scalar(select(WorkingSetDraftRow).where(WorkingSetDraftRow.id == draft_id).with_for_update())
        if draft is None:
            raise KeyError(draft_id)
        if draft.status != "active" or draft.revision != draft_revision:
            raise StaleDraft("working-set draft revision changed")
        existing = session.scalar(
            select(CoverageSnapshotRow)
            .where(CoverageSnapshotRow.draft_id == draft_id, CoverageSnapshotRow.draft_revision == draft_revision)
            .order_by(CoverageSnapshotRow.created_at.desc())
            .limit(1)
        )
        if existing is not None and existing.snapshot_json == snapshot:
            return _coverage(existing)
        row = CoverageSnapshotRow(id=str(uuid4()), draft_id=draft_id, draft_revision=draft_revision, snapshot_json=snapshot, risk_confirmed=False, created_at=now)
        session.add(row)
        if attempt is not None:
            attempt.result_hash = payload_hash(snapshot)
            attempt.status = "produced"
        session.flush()
        return _coverage(row)


def confirm_coverage(draft_id: str, *, payload: CoverageConfirmationRequest, confirmed_by: str) -> WorkingSetDraftRecord:
    now = _now()
    digest = payload_hash(payload.model_dump(mode="json"))
    with session_scope() as session:
        draft = session.scalar(select(WorkingSetDraftRow).where(WorkingSetDraftRow.id == draft_id).with_for_update())
        if draft is None:
            raise KeyError(draft_id)
        command = session.scalar(select(WorkingSetCommandRow).where(WorkingSetCommandRow.draft_id == draft_id, WorkingSetCommandRow.command_id == payload.command_id))
        if command is not None:
            if command.payload_hash != digest:
                raise RepositoryConflict("coverage command payload changed")
            return _draft(draft)
        if draft.status != "active" or draft.revision != payload.draft_revision:
            raise StaleDraft("working-set draft revision changed")
        snapshot = session.scalar(select(CoverageSnapshotRow).where(CoverageSnapshotRow.draft_id == draft_id, CoverageSnapshotRow.draft_revision == draft.revision).order_by(CoverageSnapshotRow.created_at.desc()).limit(1))
        if snapshot is None:
            raise RepositoryConflict("coverage review is required before confirmation")
        snapshot.risk_confirmed = payload.confirmed
        snapshot.risk_confirmation_note = payload.note
        snapshot.confirmed_by = confirmed_by if payload.confirmed else None
        snapshot.confirmed_at = now if payload.confirmed else None
        session.add(WorkingSetCommandRow(id=str(uuid4()), draft_id=draft_id, command_id=payload.command_id, payload_hash=digest, result_json={"risk_confirmed": payload.confirmed}, created_at=now))
        try:
            session.flush()
        except IntegrityError:
            recovered = _recover_duplicate_command(session, draft_id, payload.command_id, digest)
            if recovered is not None:
                return recovered
            raise RepositoryConflict("coverage confirmation was updated concurrently")
        return _draft(draft)


def set_freeze_intent(draft_id: str, *, expected_revision: int, intent: dict[str, Any]) -> WorkingSetDraftRecord:
    with session_scope() as session:
        draft = session.scalar(select(WorkingSetDraftRow).where(WorkingSetDraftRow.id == draft_id).with_for_update())
        if draft is None:
            raise KeyError(draft_id)
        if draft.status != "active" or draft.revision != expected_revision:
            raise StaleDraft("working-set draft revision changed")
        existing = draft.freeze_intent_json
        if existing is not None:
            if existing == intent:
                return _draft(draft)
            raise RepositoryConflict("another freeze intent is already pending")
        draft.freeze_intent_json = intent
        draft.updated_at = _now()
        session.flush()
        return _draft(draft)


def clear_freeze_intent(draft_id: str, command_id: str | None) -> WorkingSetDraftRecord:
    with session_scope() as session:
        draft = session.scalar(select(WorkingSetDraftRow).where(WorkingSetDraftRow.id == draft_id).with_for_update())
        if draft is None:
            raise KeyError(draft_id)
        if draft.freeze_intent_json and draft.freeze_intent_json.get("freeze_command_id") != command_id:
            raise RepositoryConflict("freeze intent does not match the requested command")
        draft.freeze_intent_json = None
        draft.updated_at = _now()
        session.flush()
        return _draft(draft)


def discard_draft(draft_id: str, *, expected_revision: int, command_id: str) -> WorkingSetDraftRecord:
    digest = payload_hash({"draft_revision": expected_revision, "action": "discard"})
    with session_scope() as session:
        row = session.scalar(select(WorkingSetDraftRow).where(WorkingSetDraftRow.id == draft_id).with_for_update())
        if row is None:
            raise KeyError(draft_id)
        command = session.scalar(
            select(WorkingSetCommandRow).where(
                WorkingSetCommandRow.draft_id == draft_id,
                WorkingSetCommandRow.command_id == command_id,
            )
        )
        if command is not None:
            if command.payload_hash != digest:
                raise RepositoryConflict("discard command payload changed")
            return _draft(row)
        if row.status != "active" or row.revision != expected_revision:
            raise StaleDraft("working-set draft revision changed")
        row.status = "discarded"
        row.active_key = None
        row.discarded_at = _now()
        row.updated_at = row.discarded_at
        session.add(
            WorkingSetCommandRow(
                id=str(uuid4()),
                draft_id=draft_id,
                command_id=command_id,
                payload_hash=digest,
                result_json={"status": "discarded"},
                created_at=row.discarded_at,
            )
        )
        session.flush()
        return _draft(row)


def create_version_if_current(
    draft_id: str,
    *,
    version_id: str,
    expected_revision: int,
    version_number: int,
    contract_revision_id: str,
    freeze_command_id: str,
    schema_version: str,
    keys: dict[str, str],
    hashes: dict[str, str],
    overall_sha256: str,
    risk_confirmation: dict[str, Any],
    frozen_by: str,
    frozen_at: datetime,
) -> EvaluationSetVersionRecord:
    now = _now()
    draft_before = get_draft(draft_id)
    workspace_id = draft_before.workspace_id if draft_before else ""
    try:
        with session_scope() as session:
            draft = session.scalar(select(WorkingSetDraftRow).where(WorkingSetDraftRow.id == draft_id).with_for_update())
            if draft is None:
                raise KeyError(draft_id)
            session.scalar(select(WorkspaceRow).where(WorkspaceRow.id == draft.workspace_id).with_for_update())
            latest_number = session.scalar(
                select(func.max(EvaluationSetVersionRow.version_number)).where(
                    EvaluationSetVersionRow.workspace_id == draft.workspace_id
                )
            ) or 0
            existing = session.scalar(
                select(EvaluationSetVersionRow).where(
                    EvaluationSetVersionRow.workspace_id == draft.workspace_id,
                    EvaluationSetVersionRow.freeze_command_id == freeze_command_id,
                )
            )
            if existing is not None:
                return _version(existing)
            if draft.status != "active" or draft.revision != expected_revision:
                raise StaleDraft("working-set draft changed during freeze")
            if version_number != latest_number + 1:
                raise RepositoryConflict("evaluation-set version line advanced")
            row = EvaluationSetVersionRow(
                id=version_id,
                workspace_id=draft.workspace_id,
                version_number=version_number,
                draft_id=draft.id,
                contract_revision_id=contract_revision_id,
                schema_version=schema_version,
                freeze_command_id=freeze_command_id,
                manifest_key=keys["manifest"],
                runtime_key=keys["runtime"],
                judge_key=keys["judge"],
                provenance_key=keys["provenance"],
                package_key=keys["package"],
                manifest_sha256=hashes["manifest"],
                runtime_sha256=hashes["runtime"],
                judge_sha256=hashes["judge"],
                provenance_sha256=hashes["provenance"],
                overall_sha256=overall_sha256,
                risk_confirmation_json=risk_confirmation,
                frozen_by=frozen_by,
                frozen_at=frozen_at,
                created_at=now,
            )
            session.add(row)
            draft.status = "discarded"
            draft.active_key = None
            draft.discarded_at = now
            draft.updated_at = now
            session.flush()
            return _version(row)
    except IntegrityError:
        existing = get_version_by_freeze_command(workspace_id, freeze_command_id)
        if existing is not None:
            return existing
        raise


def latest_version_number(workspace_id: str) -> int:
    with session_scope() as session:
        value = session.scalar(select(EvaluationSetVersionRow.version_number).where(EvaluationSetVersionRow.workspace_id == workspace_id).order_by(EvaluationSetVersionRow.version_number.desc()).limit(1))
        return int(value or 0)
