from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.features.auth.repository import UserRecord
from app.features.case_builder import cocreation_repository as repository
from app.features.case_builder import ingestion_repository
from app.features.case_builder.cocreation_schemas import (
    BatchAnalysis,
    CoCreationAgentResult,
    CoCreationAnswerRequest,
    CoCreationConfirmRequest,
    CoCreationKind,
    CoCreationRetryRequest,
    CoCreationResetRequest,
    CoCreationSessionResponse,
    CoCreationSessionView,
    CoCreationDelta,
    CoCreationQuestion,
    CoCreationStartRequest,
    CoCreationStatus,
    CoCreationTurnView,
    ContractRevisionStatus,
    GroupingConfirmationRequest,
    PromotionCreateRequest,
    PromotionDecisionRequest,
    ScenarioContractContent,
    JudgmentPackageContent,
    SkillAttemptProposal,
    SkillAttemptView,
    TaskGroupInput,
    TaskPackageListResponse,
    TaskPackageResponse,
    TaskPackageStatus,
    TaskPackageSummary,
    EvaluationFileSnapshot,
    EvaluationTaskSnapshot,
)
from app.features.workspaces import service as workspace_service
from app.lib.ai_runtime import AgentRunContext, get_adapters, get_ai_profile
from app.lib.ai_runtime.profile import GRAPH_SCHEMA_VERSION
from app.lib.ai_runtime.adapters import AgentRunResult
from app.lib.ai_runtime.checkpoint import CheckpointIncompatible, CheckpointNotFound
from app.lib.ai_runtime.evidence import documents_for_files, validate_evidence_refs
from app.lib.errors import AppError
from app.lib.operations import attempts as attempt_repository
from app.lib.operations import repository as operation_repository
from app.lib.operations.repository import OperationJob, OperationJobStatus


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _summary(item: repository.TaskPackageRecord) -> TaskPackageSummary:
    return TaskPackageSummary(
        id=item.id,
        workspace_id=item.workspace_id,
        upload_batch_id=item.upload_batch_id,
        status=TaskPackageStatus(item.status),
        title=item.title,
        evidence_file_ids=list(item.evidence_file_ids),
        attempts=[
            SkillAttemptView(
                attempt_key=str(attempt["attempt_key"]),
                label=str(attempt["label"]),
                evidence_file_ids=list(attempt["evidence_file_ids"]),
            )
            for attempt in (item.analysis or {}).get("attempts", [])
        ],
        revision=item.revision,
        initialization_only=item.initialization_only,
        has_judgment_package=item.judgment_package is not None,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _authorized_batch(workspace_id: str, batch_id: str, user: UserRecord) -> ingestion_repository.UploadBatchRecord:
    workspace_service.assert_owner(workspace_id, user)
    batch = ingestion_repository.get_batch(batch_id)
    if batch is None:
        raise AppError(404, "RESOURCE_NOT_FOUND", "上传批次不存在。")
    if batch.workspace_id != workspace_id:
        raise AppError(403, "FORBIDDEN", "你无权访问这个上传批次。")
    return batch


def _authorized_package(workspace_id: str, task_package_id: str, user: UserRecord) -> repository.TaskPackageRecord:
    workspace_service.assert_owner(workspace_id, user)
    item = repository.get_task_package(task_package_id)
    if item is None:
        raise AppError(404, "RESOURCE_NOT_FOUND", "任务不存在。")
    if item.workspace_id != workspace_id:
        raise AppError(403, "FORBIDDEN", "你无权访问这个任务。")
    return item


def _authorized_session(workspace_id: str, session_id: str, user: UserRecord) -> repository.CoCreationSessionRecord:
    workspace_service.assert_owner(workspace_id, user)
    item = repository.get_session(session_id)
    if item is None:
        raise AppError(404, "RESOURCE_NOT_FOUND", "共创会话不存在。")
    if item.workspace_id != workspace_id:
        raise AppError(403, "FORBIDDEN", "你无权访问这个共创会话。")
    return item


def list_task_packages(workspace_id: str, batch_id: str, user: UserRecord) -> TaskPackageListResponse:
    batch = _authorized_batch(workspace_id, batch_id, user)
    return TaskPackageListResponse(
        batch_id=batch.id,
        batch_revision=batch.revision,
        task_packages=[_summary(item) for item in repository.list_task_packages(batch.id)],
    )


def confirm_task_groups(
    workspace_id: str,
    batch_id: str,
    payload: GroupingConfirmationRequest,
    user: UserRecord,
) -> TaskPackageListResponse:
    batch = _authorized_batch(workspace_id, batch_id, user)
    if batch.status != "ready_for_confirmation":
        raise AppError(409, "BATCH_NOT_READY", "资料仍在整理，暂时不能确认任务分组。")
    files = ingestion_repository.list_files(batch.id)
    if any(item.visibility == "unconfirmed" and not item.ignored for item in files):
        raise AppError(409, "FILE_ROLES_NOT_CONFIRMED", "请先确认每份资料的用途和可见范围。")
    normalized: list[TaskGroupInput] = []
    for group in payload.groups:
        file_by_id = {item.id: item for item in files}
        if any(file_by_id.get(file_id) is None or file_by_id[file_id].ignored for file_id in group.evidence_file_ids):
            raise AppError(422, "INVALID_TASK_GROUPING", "任务分组不能包含被忽略或不存在的资料。")
        if group.attempts:
            normalized.append(group)
            continue
        normalized.append(
            TaskGroupInput.model_validate(
                {
                    **group.model_dump(mode="json"),
                    "attempts": [
                        {
                            "attempt_key": f"{group.proposal_key or group.title}-attempt-1",
                            "label": "老师确认的任务证据",
                            "evidence_file_ids": list(group.evidence_file_ids),
                        }
                    ],
                }
            )
        )
    try:
        packages = repository.confirm_grouping(
            batch.id,
            expected_revision=payload.batch_revision,
            command_id=payload.command_id,
            groups=normalized,
            confirmed_by=user.id,
        )
    except ValueError as exc:
        raise AppError(422, "INVALID_TASK_GROUPING", "任务分组中的资料必须来自当前批次且不能重复。") from exc
    except repository.RepositoryConflict as exc:
        code = "GROUPING_ALREADY_CONFIRMED" if "already been confirmed" in str(exc) else "COMMAND_ID_REUSED"
        raise AppError(409, code, "任务分组已经确认，不能再创建第二套正式分组。" if code == "GROUPING_ALREADY_CONFIRMED" else "相同命令已经提交过不同的分组内容。") from exc
    if packages is None:
        raise AppError(409, "STALE_BATCH", "批次已经更新，请重新读取后确认分组。")
    refreshed = ingestion_repository.get_batch(batch.id)
    return TaskPackageListResponse(
        batch_id=batch.id,
        batch_revision=refreshed.revision if refreshed else batch.revision,
        task_packages=[_summary(item) for item in packages],
    )


def get_task_package(workspace_id: str, task_package_id: str, user: UserRecord) -> TaskPackageResponse:
    return TaskPackageResponse(task_package=_summary(_authorized_package(workspace_id, task_package_id, user)))


def get_latest_confirmed_contract(workspace_id: str) -> repository.ContractRevisionRecord | None:
    revisions = repository.list_contract_revisions(
        workspace_id,
        status=ContractRevisionStatus.confirmed.value,
    )
    return revisions[0] if revisions else None


def get_contract_revision_for_evaluation(
    workspace_id: str,
    contract_revision_id: str,
) -> repository.ContractRevisionRecord:
    revision = repository.get_contract_revision(contract_revision_id)
    if revision is None or revision.workspace_id != workspace_id:
        raise AppError(404, "RESOURCE_NOT_FOUND", "场景标准不存在。")
    return revision


def get_evaluation_task_snapshot(workspace_id: str, task_package_id: str) -> EvaluationTaskSnapshot:
    package = repository.get_task_package(task_package_id)
    if package is None or package.workspace_id != workspace_id:
        raise AppError(404, "RESOURCE_NOT_FOUND", "任务不存在。")
    if package.status != TaskPackageStatus.confirmed.value:
        raise AppError(409, "TASK_NOT_CONFIRMED", "任务尚未确认。")
    if not package.contract_revision_id or not package.judgment_package:
        raise AppError(409, "TASK_NOT_READY_FOR_VERSION", "任务缺少已确认的场景标准或判定依据。")
    contract = repository.get_contract_revision(package.contract_revision_id)
    if contract is None or contract.status != ContractRevisionStatus.confirmed.value:
        raise AppError(409, "CONTRACT_NOT_CONFIRMED", "任务引用的场景标准尚未确认。")
    judgment = JudgmentPackageContent.model_validate(package.judgment_package)
    files_by_id = {item.id: item for item in ingestion_repository.list_files(package.upload_batch_id)}
    batch = ingestion_repository.get_batch(package.upload_batch_id)
    files: list[EvaluationFileSnapshot] = []
    for file_id in package.evidence_file_ids:
        item = files_by_id.get(file_id)
        if item is None:
            raise AppError(409, "TASK_NOT_READY_FOR_VERSION", "任务引用的资料已经缺失。")
        if item.ignored or item.visibility == "unconfirmed" or item.role == "unknown":
            raise AppError(409, "TASK_NOT_READY_FOR_VERSION", "任务仍有资料用途或可见范围未确认。")
        if item.parse_state != "parsed":
            raise AppError(409, "TASK_NOT_READY_FOR_VERSION", "任务仍有不可读取的必需资料。")
        files.append(
            EvaluationFileSnapshot(
                file_id=item.id,
                name=item.original_name,
                media_type=item.media_type,
                size_bytes=item.size_bytes,
                sha256=item.sha256,
                parse_state=item.parse_state,
                role=item.role,
                required=item.required,
                ignored=item.ignored,
                visibility=item.visibility,
                storage_key=item.storage_key,
            )
        )
    return EvaluationTaskSnapshot(
        task_package_id=package.id,
        workspace_id=package.workspace_id,
        title=package.title,
        task_description=batch.task_description if batch else None,
        revision=package.revision,
        contract_revision_id=contract.id,
        contract=ScenarioContractContent.model_validate(contract.contract),
        draft=package.draft or {},
        judgment_package=judgment,
        files=files,
        attempts=[SkillAttemptProposal.model_validate(item) for item in (package.analysis or {}).get("attempts", [])],
        provenance={
            "task_package_revision": package.revision,
            "confirmed_by": package.confirmed_by,
            "confirmed_at": package.confirmed_at.isoformat() if package.confirmed_at else None,
            "analysis": package.analysis or {},
        },
    )


def _session_context(session: repository.CoCreationSessionRecord, package: repository.TaskPackageRecord) -> AgentRunContext:
    owner_id = workspace_service.owner_id_for_workspace(session.workspace_id)
    return AgentRunContext(
        user_id=owner_id,
        workspace_id=session.workspace_id,
        target_type="task_package",
        target_id=package.id,
        thread_key=session.stable_thread_key,
        business_revision=session.business_revision,
        evidence_file_ids=tuple(package.evidence_file_ids),
        evidence_scope=f"/evidence/task-package/{package.id}",
        ai_profile_version=session.ai_profile_version,
        graph_schema_version=session.graph_schema_version,
        deadline=None,
    )


def _job_for_session(session_id: str) -> OperationJob | None:
    jobs = operation_repository.list_for_target("co_creation_session", session_id)
    for job in jobs:
        if job.status in {
            OperationJobStatus.queued,
            OperationJobStatus.running,
            OperationJobStatus.failed,
            OperationJobStatus.projection_pending,
        }:
            return job
    return None


def _session_view(session: repository.CoCreationSessionRecord) -> CoCreationSessionView:
    projection = session.projection or {}
    contract = ScenarioContractContent.model_validate(projection["contract"]) if projection.get("contract") else None
    judgment = JudgmentPackageContent.model_validate(projection["judgment_package"]) if projection.get("judgment_package") else None
    turns = [
        CoCreationTurnView(
            id=item.id,
            turn_revision=item.turn_revision,
            question=item.question and CoCreationQuestion.model_validate(item.question),
            answer=item.answer,
            delta=item.delta and CoCreationDelta.model_validate(item.delta),
            status=item.status,
            created_at=item.created_at,
            answered_at=item.answered_at,
        )
        for item in repository.list_turns(session.id)
    ]
    pending = session.pending_interrupt
    pending_question = None
    if pending and pending.get("id"):
        pending_question = CoCreationQuestion.model_validate(pending)
    job = _job_for_session(session.id)
    if session.status == CoCreationStatus.continuity_reset.value:
        next_action = "continuity_reset"
    elif job and job.status in {OperationJobStatus.queued, OperationJobStatus.running}:
        next_action = "wait_for_processing"
    elif job and job.status in {OperationJobStatus.failed, OperationJobStatus.projection_pending}:
        next_action = "retry_processing"
    elif session.status in {CoCreationStatus.queued.value, CoCreationStatus.processing.value}:
        next_action = "wait_for_processing"
    elif session.status == CoCreationStatus.waiting_for_teacher.value:
        next_action = "answer_question"
    elif session.status == CoCreationStatus.ready_for_confirmation.value:
        next_action = "review_and_confirm"
    else:
        next_action = "none"
    blocking = [
        str(item.get("text"))
        for item in projection.get("blocking_gaps", [])
        if item.get("blocking")
    ]
    if pending and pending.get("reason"):
        blocking.append(str(pending["reason"]))
    return CoCreationSessionView(
        id=session.id,
        workspace_id=session.workspace_id,
        task_package_id=session.task_package_id,
        kind=CoCreationKind(session.kind),
        purpose=session.purpose,
        initialization_only=session.initialization_only,
        status=CoCreationStatus(session.status),
        business_revision=session.business_revision,
        pending_question=pending_question,
        contract=contract,
        judgment_package=judgment,
        turns=turns,
        next_action=next_action,
        active_operation_id=job.id if job and job.status in {OperationJobStatus.queued, OperationJobStatus.running, OperationJobStatus.failed, OperationJobStatus.projection_pending} else None,
        blocking_issues=blocking,
    )


def _session_response(session: repository.CoCreationSessionRecord) -> CoCreationSessionResponse:
    return CoCreationSessionResponse(session=_session_view(session))


def start_cocreation(
    workspace_id: str,
    task_package_id: str,
    payload: CoCreationStartRequest,
    user: UserRecord,
) -> CoCreationSessionResponse:
    package = _authorized_package(workspace_id, task_package_id, user)
    if package.status != TaskPackageStatus.confirmed.value:
        raise AppError(409, "TASK_NOT_CONFIRMED", "请先确认任务分组。")
    if payload.kind == CoCreationKind.task_judgment:
        contract = repository.get_contract_revision(package.contract_revision_id) if package.contract_revision_id else None
        if contract is None or contract.status != ContractRevisionStatus.confirmed.value:
            raise AppError(409, "CONTRACT_NOT_CONFIRMED", "请先确认场景标准，再形成单题判定依据。")
    if package.revision != payload.task_package_revision:
        raise AppError(409, "STALE_TASK_PACKAGE", "任务已经更新，请重新读取后再开始共创。")
    existing_by_command = repository.get_session_by_command(task_package_id, payload.kind.value, payload.command_id)
    if existing_by_command is not None:
        return _session_response(existing_by_command)
    existing = repository.get_active_session(task_package_id, payload.kind.value)
    if existing is not None:
        if existing.status == CoCreationStatus.queued.value and _job_for_session(existing.id) is None:
            operation_repository.create_or_get(
                kind="cocreation_start",
                target_type="co_creation_session",
                target_id=existing.id,
                command_id=existing.command_id or payload.command_id,
                business_revision=existing.business_revision,
                accepted_checkpoint_id=existing.accepted_checkpoint_id,
            )
        return _session_response(existing)
    latest = repository.get_latest_session(task_package_id, payload.kind.value)
    if latest is not None and latest.status == CoCreationStatus.confirmed.value and payload.kind == CoCreationKind.task_judgment:
        return _session_response(latest)
    profile = get_ai_profile()
    session = repository.create_session(
        workspace_id=workspace_id,
        task_package_id=task_package_id,
        kind=payload.kind,
        command_id=payload.command_id,
        initialization_only=payload.initialization_only,
        ai_profile_version=profile.version,
        graph_schema_version=GRAPH_SCHEMA_VERSION,
    )
    if session.command_id != payload.command_id:
        return _session_response(session)
    try:
        operation_repository.create_or_get(
            kind="cocreation_start",
            target_type="co_creation_session",
            target_id=session.id,
            command_id=payload.command_id,
            business_revision=session.business_revision,
        )
    except Exception:
        repository.delete_session(session.id)
        raise
    return _session_response(repository.get_session(session.id) or session)


def get_cocreation(workspace_id: str, session_id: str, user: UserRecord) -> CoCreationSessionResponse:
    return _session_response(_authorized_session(workspace_id, session_id, user))


def answer_cocreation(
    workspace_id: str,
    session_id: str,
    payload: CoCreationAnswerRequest,
    user: UserRecord,
) -> CoCreationSessionResponse:
    session = _authorized_session(workspace_id, session_id, user)
    try:
        updated, duplicate = repository.save_answer(
            session.id,
            expected_business_revision=payload.business_revision,
            question_id=payload.question_id,
            answer=payload.answer,
            command_id=payload.command_id,
        ) or (None, False)
    except repository.RepositoryConflict as exc:
        message = str(exc)
        if "payload conflicts" in message:
            raise AppError(409, "COMMAND_ID_REUSED", "相同命令已经提交过不同的回答。") from exc
        code = "QUESTION_ALREADY_ANSWERED" if "stale" in message or "already" in message else "QUESTION_NOT_PENDING"
        raise AppError(409, code, "当前问题已经回答或不再等待回答。") from exc
    if updated is None:
        raise AppError(409, "STALE_COCREATION", "共创状态已经更新，请重新读取后回答。")
    if duplicate:
        if updated.status == CoCreationStatus.processing.value and _job_for_session(updated.id) is None:
            operation_repository.create_or_get(
                kind="cocreation_resume",
                target_type="co_creation_session",
                target_id=updated.id,
                command_id=payload.command_id,
                business_revision=updated.business_revision,
                accepted_checkpoint_id=updated.accepted_checkpoint_id,
            )
        return _session_response(updated)
    try:
        operation_repository.create_or_get(
            kind="cocreation_resume",
            target_type="co_creation_session",
            target_id=updated.id,
            command_id=payload.command_id,
            business_revision=updated.business_revision,
            accepted_checkpoint_id=updated.accepted_checkpoint_id,
        )
    except Exception:
        repository.mark_failed(updated.id, {"code": "OPERATION_ENQUEUE_FAILED"})
        raise
    return _session_response(repository.get_session(updated.id) or updated)


def retry_cocreation(
    workspace_id: str,
    session_id: str,
    payload: CoCreationRetryRequest,
    user: UserRecord,
) -> CoCreationSessionResponse:
    session = _authorized_session(workspace_id, session_id, user)
    if session.business_revision != payload.business_revision:
        raise AppError(409, "STALE_COCREATION", "共创状态已经更新，请重新读取后重试。")
    latest_jobs = operation_repository.list_for_target("co_creation_session", session.id)
    latest = latest_jobs[0] if latest_jobs else None
    if latest and latest.status == OperationJobStatus.projection_pending:
        runs = attempt_repository.list_for_job(latest.id)
        produced = runs[-1].produced_checkpoint_id if runs else None
        if not produced:
            raise AppError(409, "RETRY_NOT_AVAILABLE", "没有可重投影的共创结果。")
        kind = "cocreation_reproject"
        accepted = produced
    else:
        turns = repository.list_turns(session.id)
        kind = "cocreation_resume" if any(item.status == "answered_pending_resume" for item in turns) else "cocreation_start"
        accepted = session.accepted_checkpoint_id
    if session.status == CoCreationStatus.processing.value and _job_for_session(session.id) is None:
        operation_repository.create_or_get(
            kind=kind,
            target_type="co_creation_session",
            target_id=session.id,
            command_id=payload.command_id,
            business_revision=session.business_revision,
            accepted_checkpoint_id=accepted,
        )
        return _session_response(repository.get_session(session.id) or session)
    try:
        queued = repository.queue_retry(session.id, expected_business_revision=payload.business_revision)
    except repository.RepositoryConflict as exc:
        raise AppError(409, "RETRY_NOT_AVAILABLE", "当前没有可重试的共创操作。") from exc
    if queued is None:
        raise AppError(409, "STALE_COCREATION", "共创状态已经更新，请重新读取后重试。")
    try:
        operation_repository.create_or_get(
            kind=kind,
            target_type="co_creation_session",
            target_id=session.id,
            command_id=payload.command_id,
            business_revision=queued.business_revision,
            accepted_checkpoint_id=accepted,
        )
    except Exception:
        repository.mark_failed(session.id, {"code": "OPERATION_ENQUEUE_FAILED"})
        raise
    return _session_response(repository.get_session(session.id) or queued)


def reset_cocreation(
    workspace_id: str,
    session_id: str,
    payload: CoCreationResetRequest,
    user: UserRecord,
) -> CoCreationSessionResponse:
    session = _authorized_session(workspace_id, session_id, user)
    try:
        reset = repository.create_continuity_reset(
            session.id,
            command_id=payload.command_id,
            reason=payload.reason,
            ai_profile_version=get_ai_profile().version,
            graph_schema_version=GRAPH_SCHEMA_VERSION,
        )
    except repository.RepositoryConflict as exc:
        raise AppError(409, "CONTINUITY_RESET_NOT_REQUIRED", "当前共创会话不需要重新建立连续性。") from exc
    try:
        operation_repository.create_or_get(
            kind="cocreation_start",
            target_type="co_creation_session",
            target_id=reset.id,
            command_id=payload.command_id,
            business_revision=reset.business_revision,
            accepted_checkpoint_id=None,
        )
    except Exception:
        repository.mark_failed(reset.id, {"code": "OPERATION_ENQUEUE_FAILED"})
        raise
    return _session_response(repository.get_session(reset.id) or reset)


def confirm_contract(
    workspace_id: str,
    session_id: str,
    payload: CoCreationConfirmRequest,
    user: UserRecord,
) -> CoCreationSessionResponse:
    session = _authorized_session(workspace_id, session_id, user)
    try:
        confirmed = repository.confirm_contract(
            session.id,
            expected_business_revision=payload.business_revision,
            confirmed_by=user.id,
            command_id=payload.command_id,
        )
    except repository.StaleProjection as exc:
        raise AppError(409, "STALE_COCREATION", "共创状态已经更新，请重新读取后确认。") from exc
    except repository.RepositoryConflict as exc:
        raise AppError(409, "CONTRACT_NOT_READY", "场景标准尚未完成或存在阻塞缺口。") from exc
    return _session_response(confirmed)


def confirm_judgment(
    workspace_id: str,
    session_id: str,
    payload: CoCreationConfirmRequest,
    user: UserRecord,
) -> CoCreationSessionResponse:
    session = _authorized_session(workspace_id, session_id, user)
    try:
        confirmed = repository.confirm_judgment(
            session.id,
            expected_business_revision=payload.business_revision,
            confirmed_by=user.id,
            command_id=payload.command_id,
        )
    except repository.StaleProjection as exc:
        raise AppError(409, "STALE_COCREATION", "共创状态已经更新，请重新读取后确认。") from exc
    except repository.RepositoryConflict as exc:
        raise AppError(409, "JUDGMENT_NOT_READY", "判定依据包尚未完成或存在阻塞缺口。") from exc
    return _session_response(confirmed)


def create_feedback(
    workspace_id: str,
    task_package_id: str,
    payload: PromotionCreateRequest,
    user: UserRecord,
) -> dict[str, Any]:
    package = _authorized_package(workspace_id, task_package_id, user)
    if payload.source_id not in {*package.evidence_file_ids, package.id}:
        raise AppError(422, "INVALID_FEEDBACK_SOURCE", "反馈来源不属于当前任务。")
    feedback = repository.create_feedback(package.id, payload.source_id, payload.text, user.id)
    proposal = repository.create_promotion(package.id, workspace_id, feedback.id, payload.text)
    return {"feedback_id": feedback.id, "promotion_id": proposal.id, "status": proposal.status}


def decide_promotion(
    workspace_id: str,
    proposal_id: str,
    payload: PromotionDecisionRequest,
    user: UserRecord,
) -> dict[str, Any]:
    workspace_service.assert_owner(workspace_id, user)
    proposal = repository.get_promotion(proposal_id)
    if proposal is None or proposal.workspace_id != workspace_id:
        raise AppError(404, "RESOURCE_NOT_FOUND", "标准升级提案不存在。")
    try:
        decided = repository.decide_promotion(proposal.id, payload.decision, confirmed_by=user.id)
    except repository.RepositoryConflict as exc:
        raise AppError(409, "PROMOTION_ALREADY_DECIDED", "标准升级提案已经处理。") from exc
    return {"promotion_id": decided.id, "status": decided.status, "decided_at": decided.decided_at}


def _batch_context(batch_id: str, workspace_id: str, target_id: str, revision: int) -> AgentRunContext:
    owner_id = workspace_service.owner_id_for_workspace(workspace_id)
    files = ingestion_repository.list_files(batch_id)
    return AgentRunContext(
        user_id=owner_id,
        workspace_id=workspace_id,
        target_type="upload_batch",
        target_id=target_id,
        thread_key=f"batch-analysis-{target_id}",
        business_revision=revision,
        evidence_file_ids=tuple(item.id for item in files),
        evidence_scope=f"/evidence/batch/{batch_id}",
        ai_profile_version=get_ai_profile().version,
        graph_schema_version="m0-batch-analysis-v1",
        deadline=None,
    )


def complete_batch_analysis(job: OperationJob) -> dict[str, Any]:
    batch = ingestion_repository.get_batch(job.target_id)
    if batch is None:
        raise AppError(404, "RESOURCE_NOT_FOUND", "上传批次不存在。")
    if batch.revision != job.business_revision:
        from app.lib.operations.worker import SupersededOperation

        raise SupersededOperation("上传批次已产生新修订。")
    if batch.status == "ready_for_confirmation":
        return {"batch_id": batch.id, "status": "ready_for_confirmation", "group_count": len(repository.list_task_packages(batch.id))}
    files = ingestion_repository.list_files(batch.id)
    context = _batch_context(batch.id, batch.workspace_id, batch.id, batch.revision)
    try:
        result = get_adapters().evidence_analyzer.analyze(context, documents_for_files([item.id for item in files]))
        if not isinstance(result.result, BatchAnalysis):
            raise RuntimeError("evidence analyzer returned an invalid result")
        known = {item.id for item in files}
        proposed = set()
        for group in result.result.groups:
            proposed.update(group.evidence_file_ids)
            validate_evidence_refs(group.evidence_refs, documents_for_files(group.evidence_file_ids))
        proposed.update(result.result.unassigned_file_ids)
        if proposed - known or set(result.result.file_roles) - known:
            raise RuntimeError("evidence analyzer returned an out-of-scope file")
        repository.replace_proposals(batch.id, result.result, expected_revision=job.business_revision)
    except repository.RepositoryConflict as exc:
        from app.lib.operations.worker import SupersededOperation

        raise SupersededOperation(str(exc)) from exc
    except Exception:
        ingestion_repository.update_status(batch.id, "failed", expected_revision=batch.revision)
        raise
    return {"batch_id": batch.id, "status": "ready_for_confirmation", "group_count": len(result.result.groups)}


def _run_cocreation_agent(job: OperationJob, mode: str) -> dict[str, Any]:
    session = repository.get_session(job.target_id)
    if session is None:
        raise AppError(404, "RESOURCE_NOT_FOUND", "共创会话不存在。")
    package = repository.get_task_package(session.task_package_id)
    if package is None:
        raise AppError(404, "RESOURCE_NOT_FOUND", "任务不存在。")
    if session.business_revision != job.business_revision:
        from app.lib.operations.worker import SupersededOperation

        runs = attempt_repository.list_for_job(job.id)
        if (
            session.business_revision > job.business_revision
            and runs
            and runs[-1].produced_checkpoint_id
            and runs[-1].produced_checkpoint_id == session.accepted_checkpoint_id
        ):
            return {"session_id": session.id, "status": session.status, "business_revision": session.business_revision}

        raise SupersededOperation("共创业务版本已经更新。")
    context = _session_context(session, package)
    adapters = get_adapters()
    try:
        if mode == "start":
            result = adapters.standard_cocreator.start(context, CoCreationKind(session.kind))
        elif mode == "resume":
            turns = repository.list_turns(session.id)
            answered = next((item for item in reversed(turns) if item.status == "answered_pending_resume"), None)
            if answered is None or not answered.answer or not session.accepted_checkpoint_id:
                raise RuntimeError("no accepted checkpoint and answer are available for resume")
            result = adapters.standard_cocreator.resume(
                context,
                CoCreationKind(session.kind),
                session.accepted_checkpoint_id,
                answered.answer,
            )
        else:
            if not job.accepted_checkpoint_id:
                raise RuntimeError("no produced checkpoint is available for reproject")
            result = adapters.standard_cocreator.reproject(
                context,
                CoCreationKind(session.kind),
                job.accepted_checkpoint_id,
            )
        if not isinstance(result, AgentRunResult) or not isinstance(result.result, CoCreationAgentResult):
            raise RuntimeError("standard_cocreator returned an invalid result")
        if result.result.phase == "complete":
            expected_field = "contract" if session.kind == CoCreationKind.scenario_contract.value else "judgment_package"
            if getattr(result.result, expected_field) is None:
                raise RuntimeError(f"complete {session.kind} result is missing {expected_field}")
            if result.result.blocking_gaps and any(gap.blocking for gap in result.result.blocking_gaps):
                raise RuntimeError("complete co-creation result still contains blocking gaps")
        elif result.result.contract is not None or result.result.judgment_package is not None:
            raise RuntimeError("question result cannot publish a completed projection")
        result_refs = list(result.result.evidence_refs)
        if result.result.question is not None:
            result_refs.extend(result.result.question.evidence_refs)
        if result.result.contract is not None:
            result_refs.extend(result.result.contract.evidence_refs)
        if result.result.judgment_package is not None:
            result_refs.extend(result.result.judgment_package.evidence_refs)
        for gap in result.result.blocking_gaps:
            result_refs.extend(gap.evidence_refs)
        result_refs.extend(ref for ref in result.result.delta.unresolved for ref in ref.evidence_refs)
        validate_evidence_refs(result_refs, documents_for_files(list(package.evidence_file_ids)))
        runs = attempt_repository.list_for_job(job.id)
        if not runs:
            raise RuntimeError("agent attempt was not created")
        if result.produced_checkpoint_id:
            attempt_repository.mark_produced(
                runs[-1].id,
                produced_checkpoint_id=result.produced_checkpoint_id,
                result_hash=repository.result_hash(result.result),
            )
        try:
            updated = repository.commit_agent_result(
                session.id,
                expected_business_revision=job.business_revision,
                expected_checkpoint_id=session.accepted_checkpoint_id,
                produced_checkpoint_id=result.produced_checkpoint_id,
                result=result.result,
            )
        except repository.StaleProjection as exc:
            from app.lib.operations.worker import SupersededOperation

            raise SupersededOperation(str(exc)) from exc
        except repository.RepositoryConflict:
            repository.mark_failed(session.id, {"code": "INVALID_AGENT_RESULT"})
            raise
        except Exception as exc:
            repository.mark_projection_pending(session.id, result.produced_checkpoint_id)
            from app.lib.operations.worker import ProjectionPendingOperation

            raise ProjectionPendingOperation(
                produced_checkpoint_id=result.produced_checkpoint_id,
                result_hash=repository.result_hash(result.result),
            ) from exc
    except (CheckpointNotFound, CheckpointIncompatible) as exc:
        reason = "accepted checkpoint is missing" if isinstance(exc, CheckpointNotFound) else "accepted checkpoint is incompatible"
        repository.mark_continuity_reset(session.id, reason)
        raise RuntimeError(f"{reason}; continuity reset required") from exc
    except Exception as exc:
        from app.lib.operations.worker import SupersededOperation

        current = repository.get_session(session.id)
        if current and current.status in {CoCreationStatus.queued.value, CoCreationStatus.processing.value} and not isinstance(exc, SupersededOperation):
            repository.mark_failed(session.id, {"code": "AI_FAILED", "message": str(exc)})
        raise
    return {"session_id": updated.id, "status": updated.status, "business_revision": updated.business_revision}


def handle_cocreation_start(job: OperationJob) -> dict[str, Any]:
    return _run_cocreation_agent(job, "start")


def handle_cocreation_resume(job: OperationJob) -> dict[str, Any]:
    return _run_cocreation_agent(job, "resume")


def handle_cocreation_reproject(job: OperationJob) -> dict[str, Any]:
    return _run_cocreation_agent(job, "reproject")


def handle_coverage_review(job: OperationJob) -> dict[str, Any]:
    context = AgentRunContext(
        user_id=workspace_service.owner_id_for_workspace(job.target_id),
        workspace_id=job.target_id,
        target_type="coverage",
        target_id=job.target_id,
        thread_key=f"coverage-{job.id}",
        business_revision=job.business_revision,
        evidence_file_ids=(),
        evidence_scope="/evidence/none",
        ai_profile_version=get_ai_profile().version,
        graph_schema_version="m0-coverage-v1",
    )
    result = get_adapters().coverage_reviewer.review(context, {})
    return {"coverage": result.result.model_dump(mode="json") if hasattr(result.result, "model_dump") else result.result}
