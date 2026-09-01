"""Business orchestration for rubric co-creation and question publication."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.features.auth.repository import UserRecord
from app.features.case_builder import authoring_service
from app.features.case_builder import cocreation_service as case_service
from app.features.case_builder import ingestion_repository
from app.features.case_builder.authoring_schemas import AuthoringQuestion, QuestionInput, QuestionMaterialRole
from app.features.evaluation_sets import rubric_repository as repository
from app.features.evaluation_sets.rubric_schemas import (
    CriticalMode,
    RubricConfirmationRequest,
    RubricContent,
    RubricDeriveRequest,
    RubricDraftResponse,
    RubricDraftStatus,
    RubricGenerateRequest,
    RubricPatchRequest,
    RubricPublishRequest,
    RubricRevisionListResponse,
    RubricRevisionSummary,
    RubricDraftView,
    public_text_error,
)
from app.features.workspaces import service as workspace_service
from app.lib.ai_runtime import AgentRunContext, get_adapters, get_ai_profile
from app.lib.ai_runtime.adapters import AgentRunResult
from app.lib.errors import AppError
from app.lib.operations import repository as operation_repository
from app.lib.operations.repository import OperationJob, OperationJobStatus
from app.lib.version_packages.v2 import (
    QuestionRevisionPackageFile,
    QuestionRevisionPackageTask,
)


_ACTIVE_STATUSES = {OperationJobStatus.queued, OperationJobStatus.running}
_VISIBLE_STATUSES = {
    OperationJobStatus.queued,
    OperationJobStatus.running,
    OperationJobStatus.failed,
    OperationJobStatus.projection_pending,
}


@dataclass(frozen=True, slots=True)
class _ReferenceOutcome:
    total: int
    critical_passed: bool
    passed: bool


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _authorized_rubric(
    workspace_id: str,
    rubric_id: str,
    user: UserRecord,
) -> repository.RubricDraftRecord:
    workspace_service.assert_owner(workspace_id, user)
    draft = repository.get_draft(rubric_id)
    if draft is None:
        raise AppError(404, "RESOURCE_NOT_FOUND", "打分规则草稿不存在。")
    if draft.workspace_id != workspace_id:
        raise AppError(403, "FORBIDDEN", "你无权访问这份打分规则。")
    return draft


def _source(workspace_id: str, question_draft_id: str) -> authoring_service.ConfirmedQuestionSource:
    return authoring_service.get_confirmed_question_source(workspace_id, question_draft_id)


def _active_operation(rubric_id: str) -> OperationJob | None:
    jobs = operation_repository.list_for_target("rubric_draft", rubric_id)
    for job in jobs:
        if job.kind in {"rubric_process", "rubric_reproject"} and job.status in _VISIBLE_STATUSES:
            return job
    return None


def _has_saved_projection(
    job: OperationJob | None,
    source: authoring_service.ConfirmedQuestionSource,
) -> bool:
    """Return whether a failed projection has a validated result to replay.

    A projection-pending job is deliberately different from a normal model
    failure.  When the Worker has already produced a rubric, retrying must use
    the internal handoff payload and avoid charging the model a second time.
    """

    if not job or not isinstance(job.result, dict):
        return False
    projection = job.result.get("__rubric_projection")
    return bool(
        isinstance(projection, dict)
        and projection.get("__source_question_revision") == source.confirmed_revision
        and projection.get("__source_question_hash") == source.confirmed_hash
    )


def _safe_public_text(value: str, *, require_chinese: bool = True) -> None:
    error = public_text_error(value)
    if error == "not_chinese" and require_chinese:
        raise AppError(422, "RUBRIC_TEXT_NOT_CHINESE", "打分规则的面向老师文字必须使用中文。")
    if error == "not_safe":
        raise AppError(422, "RUBRIC_TEXT_NOT_SAFE", "打分规则不能包含内部运行信息或主机路径。")


def _validate_rubric_text(rubric: RubricContent) -> None:
    for criterion in rubric.criteria:
        for value in (
            criterion.name,
            criterion.purpose,
            *criterion.award_points,
            *criterion.deduction_points,
            *criterion.hard_fail_conditions,
            criterion.reference_score_reason,
        ):
            _safe_public_text(value)


def _reference_outcome(rubric: RubricContent) -> _ReferenceOutcome:
    total = sum(item.reference_expected_score for item in rubric.criteria)
    critical_passed = True
    for criterion in rubric.criteria:
        if not criterion.critical:
            continue
        if criterion.critical_mode == CriticalMode.minimum:
            critical_passed = critical_passed and criterion.critical_min_score is not None and criterion.reference_expected_score >= criterion.critical_min_score
        elif criterion.critical_mode == CriticalMode.hard_fail:
            critical_passed = critical_passed and not criterion.reference_hard_fail_triggered
    return _ReferenceOutcome(total=total, critical_passed=critical_passed, passed=total >= rubric.pass_threshold and critical_passed)


def _question_evidence_snapshot(
    source: authoring_service.ConfirmedQuestionSource,
    *,
    require_present: bool = False,
) -> list[dict[str, Any]]:
    materials = {item.file_id: item for item in source.input.materials}
    result: list[dict[str, Any]] = []
    for file_id in source.evidence_file_ids:
        file = ingestion_repository.get_file(file_id)
        if file is None or file.workspace_id != source.workspace_id:
            if require_present:
                raise AppError(409, "QUESTION_NOT_READY", "已确认题目引用的资料已经不存在。")
            continue
        material = materials.get(file_id)
        result.append(
            {
                "file_id": file.id,
                "name": file.original_name,
                "media_type": file.media_type,
                "size_bytes": file.size_bytes,
                "sha256": file.sha256,
                "role": material.role.value if material else file.role,
                "file_role": file.role,
                "required": file.required,
                "ignored": file.ignored,
                "visibility": file.visibility,
            }
        )
    return result


def _question_snapshot(
    source: authoring_service.ConfirmedQuestionSource,
    *,
    require_evidence_present: bool = False,
) -> dict[str, Any]:
    # Source refs are useful provenance, but never copy model quotes or source
    # text into an immutable question snapshot.
    refs = []
    for item in source.source_refs:
        if not isinstance(item, dict) or not item.get("source_id"):
            continue
        refs.append({"source_id": item["source_id"], "locator": item.get("locator")})
    return {
        "id": source.id,
        "title": source.title,
        "summary": source.summary,
        "input": source.input.model_dump(mode="json"),
        "evidence_file_ids": list(source.evidence_file_ids),
        "source_refs": refs,
        "evidence_files": _question_evidence_snapshot(
            source,
            require_present=require_evidence_present,
        ),
        "confirmed_revision": source.confirmed_revision,
        "confirmed_hash": source.confirmed_hash,
    }


def get_question_revision_for_version(
    workspace_id: str,
    revision_id: str,
) -> QuestionRevisionPackageTask:
    """Project one published question revision into the v2 package boundary.

    The published row is immutable, but the referenced evidence objects are
    still checked at freeze time.  A missing, unreadable, ignored, or
    non-runtime-visible file therefore blocks the version instead of silently
    changing the task's evidence boundary.
    """

    revision = repository.get_revision(revision_id)
    if revision is None:
        raise AppError(404, "RESOURCE_NOT_FOUND", "已发布的题目修订不存在。")
    if revision.workspace_id != workspace_id:
        raise AppError(403, "FORBIDDEN", "你无权把这道题加入版本。")
    snapshot = revision.question_snapshot
    if not isinstance(snapshot, dict):
        raise AppError(500, "QUESTION_REVISION_INVALID", "已发布的题目修订无法读取。")
    try:
        question_input = QuestionInput.model_validate(snapshot.get("input") or {})
        rubric = RubricContent.model_validate(revision.rubric)
    except (AttributeError, TypeError, ValueError) as exc:
        raise AppError(500, "QUESTION_REVISION_INVALID", "已发布的题目修订无法读取。") from exc
    outcome = _reference_outcome(rubric)
    if not outcome.passed:
        raise AppError(409, "QUESTION_REVISION_NOT_READY", "已发布题目的标准答案不满足当前规则。")

    allowed_file_ids = snapshot.get("evidence_file_ids") or []
    if not isinstance(allowed_file_ids, list):
        raise AppError(500, "QUESTION_REVISION_INVALID", "已发布题目的资料边界无效。")
    allowed = {str(item) for item in allowed_file_ids}
    raw_evidence_metadata = snapshot.get("evidence_files") or []
    if not isinstance(raw_evidence_metadata, list):
        raise AppError(500, "QUESTION_REVISION_INVALID", "已发布题目的资料快照无效。")
    evidence_metadata = {
        str(item.get("file_id")): item
        for item in raw_evidence_metadata
        if isinstance(item, dict) and item.get("file_id")
    }
    materials = [
        material
        for material in question_input.materials
        if material.role != QuestionMaterialRole.ignored
    ]
    files: list[QuestionRevisionPackageFile] = []
    issues: list[str] = []
    for material in materials:
        if material.file_id not in allowed or material.role == QuestionMaterialRole.unconfirmed:
            issues.append("题目引用了未经确认的资料范围。")
            continue
        file = ingestion_repository.get_file(material.file_id)
        if file is None or file.workspace_id != workspace_id:
            issues.append("题目引用的资料已经不存在。")
            continue
        published_file = evidence_metadata.get(material.file_id)
        if published_file is None or any(
            file_value != published_file.get(field)
            for field, file_value in {
                "name": file.original_name,
                "media_type": file.media_type,
                "size_bytes": file.size_bytes,
                "sha256": file.sha256,
                "role": material.role.value,
                "file_role": file.role,
                "required": file.required,
                "ignored": file.ignored,
                "visibility": file.visibility,
            }.items()
        ):
            issues.append(f"资料“{file.original_name}”在发布后发生变化。")
            continue
        if file.parse_state != "parsed" or file.ignored or file.visibility != "runtime":
            issues.append(f"资料“{file.original_name}”还不是可供运行的输入。")
            continue
        files.append(
            QuestionRevisionPackageFile(
                file_id=file.id,
                name=file.original_name,
                media_type=file.media_type,
                size_bytes=file.size_bytes,
                sha256=file.sha256,
                storage_key=file.storage_key,
                role=material.role.value,
                required=file.required,
                visibility=file.visibility,
            )
        )
    if issues:
        raise AppError(409, "QUESTION_REVISION_NOT_READY", "题目的运行资料还不完整。", {"issues": issues})

    runtime_input = {
        "task_instruction": question_input.task_instruction,
        "must_include": list(question_input.must_include),
        "prohibited": list(question_input.prohibited),
        "background": question_input.background,
        "materials": [
            {
                "file_id": item.file_id,
                "role": item.role.value,
                "priority": item.priority,
                "rationale": item.rationale,
            }
            for item in materials
        ],
    }
    source_refs = []
    for item in snapshot.get("source_refs") or []:
        if isinstance(item, dict) and item.get("source_id"):
            source_refs.append({"source_id": item["source_id"], "locator": item.get("locator")})
    return QuestionRevisionPackageTask(
        task_id=revision.id,
        revision=revision.revision_number,
        title=str(snapshot.get("title") or "已发布题目"),
        brief=str(snapshot.get("summary") or question_input.task_instruction),
        input=runtime_input,
        files=tuple(files),
        question_revision_id=revision.id,
        content_sha256=revision.content_sha256,
        judge={
            "question_input": question_input.model_dump(mode="json"),
            "reference_answer_text": revision.reference_answer_text,
            "rubric": rubric.model_dump(mode="json"),
            "pass_threshold": revision.pass_threshold,
        },
        provenance={
            "source_question_revision": revision.source_question_revision,
            "source_question_hash": revision.source_question_hash,
            "contract_revision_id": revision.contract_revision_id,
            "published_by": revision.published_by,
            "published_at": revision.published_at.isoformat(),
            "source_refs": source_refs,
        },
    )


def _rubric_content(record: repository.RubricDraftRecord) -> RubricContent | None:
    if record.rubric is None:
        return None
    try:
        return RubricContent.model_validate(record.rubric)
    except ValueError as exc:
        raise AppError(500, "RUBRIC_PROJECTION_INVALID", "已保存的打分规则草稿无法读取。") from exc


def _view(record: repository.RubricDraftRecord, source: authoring_service.ConfirmedQuestionSource) -> RubricDraftResponse:
    content = _rubric_content(record)
    outcome = _reference_outcome(content) if content else None
    active = _active_operation(record.id)
    if active is not None and active.business_revision != record.revision:
        # A terminal retry job from an older rubric revision must not mask the
        # projection committed by the current operation.
        active = None
    stale = (
        record.source_question_revision != source.confirmed_revision
        or record.source_question_hash != source.confirmed_hash
    )
    status = record.status
    blocking = []
    if stale:
        status = RubricDraftStatus.stale.value
        content = None
        outcome = None
        blocking.append("题目输入或标准答案已经更新，请回到第一阶段重新确认。")
    elif active and active.status == OperationJobStatus.failed:
        status = RubricDraftStatus.failed.value
        blocking.append("本轮规则整理失败，已保存的题目内容仍然保留。")
    elif active and active.status == OperationJobStatus.projection_pending:
        status = RubricDraftStatus.projection_pending.value
        blocking.append("规则结果已生成，正在恢复业务快照。")
    if content is None and not stale and status not in {RubricDraftStatus.processing.value, RubricDraftStatus.queued.value}:
        blocking.append("还没有可审阅的打分规则。")
    if outcome is not None and not outcome.passed:
        blocking.append("标准答案按当前规则未通过，请调整规则或标准答案后再确认。")
    if active and active.status in _ACTIVE_STATUSES:
        next_action = "wait_for_processing"
    elif active and active.status in {OperationJobStatus.failed, OperationJobStatus.projection_pending}:
        next_action = "retry_processing"
    elif stale:
        next_action = "stale_upstream"
    elif status in {RubricDraftStatus.queued.value, RubricDraftStatus.processing.value}:
        next_action = "wait_for_processing"
    elif status in {RubricDraftStatus.failed.value, RubricDraftStatus.projection_pending.value}:
        next_action = "retry_processing"
    elif status == RubricDraftStatus.review_ready.value:
        next_action = "confirm_rubric"
    elif status == RubricDraftStatus.confirmed.value:
        next_action = "publish"
    else:
        next_action = "none"
    revisions = repository.list_revisions(record.question_draft_id)
    return RubricDraftResponse(
        rubric=RubricDraftView(
            id=record.id,
            workspace_id=record.workspace_id,
            question_draft_id=record.question_draft_id,
            question_title=source.title,
            source_question_revision=source.confirmed_revision,
            status=RubricDraftStatus(status),
            revision=record.revision,
            question_input=source.input,
            reference_answer_text=source.reference_answer_text,
            rubric=content,
            reference_total_score=outcome.total if outcome else None,
            reference_critical_passed=outcome.critical_passed if outcome else None,
            reference_passed=outcome.passed if outcome else None,
            pending_question=AuthoringQuestion.model_validate(record.pending_question) if record.pending_question else None,
            blocking_issues=blocking,
            next_action=next_action,
            active_operation=(
                {"kind": active.kind, "status": active.status.value}
                if active and active.status in _VISIBLE_STATUSES
                else None
            ),
            published_revision_id=revisions[0].id if revisions else None,
            confirmed_at=record.confirmed_at,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )
    )


def _not_started_view(
    source: authoring_service.ConfirmedQuestionSource,
) -> RubricDraftResponse:
    """Return a readable 200 snapshot for the normal pre-generation state."""

    timestamp = source.confirmed_at
    return RubricDraftResponse(
        rubric=RubricDraftView(
            id=f"pending-{source.id}",
            workspace_id=source.workspace_id,
            question_draft_id=source.id,
            question_title=source.title,
            source_question_revision=source.confirmed_revision,
            status=RubricDraftStatus.not_started,
            revision=0,
            question_input=source.input,
            reference_answer_text=source.reference_answer_text,
            rubric=None,
            blocking_issues=[],
            next_action="start_rubric",
            active_operation=None,
            published_revision_id=None,
            confirmed_at=None,
            created_at=timestamp,
            updated_at=timestamp,
        )
    )


def get_rubric(workspace_id: str, rubric_id: str, user: UserRecord) -> RubricDraftResponse:
    record = _authorized_rubric(workspace_id, rubric_id, user)
    return _view(record, _source(workspace_id, record.question_draft_id))


def get_rubric_for_question(
    workspace_id: str,
    question_draft_id: str,
    user: UserRecord,
) -> RubricDraftResponse:
    workspace_service.assert_owner(workspace_id, user)
    source = _source(workspace_id, question_draft_id)
    record = repository.get_by_question(question_draft_id)
    if record is None:
        return _not_started_view(source)
    return _view(record, source)


def start_rubric(
    workspace_id: str,
    question_draft_id: str,
    payload: RubricGenerateRequest,
    user: UserRecord,
) -> RubricDraftResponse:
    workspace_service.assert_owner(workspace_id, user)
    source = _source(workspace_id, question_draft_id)
    if payload.question_revision != source.confirmed_revision:
        raise AppError(409, "STALE_QUESTION_DRAFT", "题目已经更新，请重新读取后再生成打分规则。")
    previous_job = None
    existing = repository.get_by_question(question_draft_id)
    if existing is not None:
        previous_job = _active_operation(existing.id)
    digest = repository.payload_hash(payload.model_dump(mode="json"))
    try:
        record, duplicate = repository.create_or_reset(
            workspace_id=workspace_id,
            question_draft_id=question_draft_id,
            source_question_revision=source.confirmed_revision,
            source_question_hash=source.confirmed_hash,
            command_id=payload.command_id,
            digest=digest,
        )
    except repository.RepositoryConflict as exc:
        raise AppError(409, "RUBRIC_NOT_EDITABLE", "当前打分规则仍有操作进行中或已发布。") from exc
    if duplicate and record.status in {"confirmed", "published", "review_ready"}:
        return _view(record, source)
    if record.status == "queued":
        operation_kind = (
            "rubric_reproject"
            if previous_job
            and previous_job.status == OperationJobStatus.projection_pending
            and _has_saved_projection(previous_job, source)
            else "rubric_process"
        )
        try:
            job = operation_repository.create_or_get(
                kind=operation_kind,
                target_type="rubric_draft",
                target_id=record.id,
                command_id=payload.command_id,
                business_revision=record.revision,
            )
            record = repository.set_active_operation(record.id, job.id, expected_revision=record.revision)
        except operation_repository.OperationCommandConflict as exc:
            raise AppError(409, "COMMAND_ID_REUSED", "相同命令已经用于另一种规则操作。") from exc
    return _view(record, source)


def patch_rubric(
    workspace_id: str,
    rubric_id: str,
    payload: RubricPatchRequest,
    user: UserRecord,
) -> RubricDraftResponse:
    record = _authorized_rubric(workspace_id, rubric_id, user)
    source = _source(workspace_id, record.question_draft_id)
    _validate_rubric_text(payload.rubric)
    try:
        changed = repository.patch_rubric(
            record.id,
            expected_revision=payload.rubric_revision,
            source_question_revision=source.confirmed_revision,
            source_question_hash=source.confirmed_hash,
            command_id=payload.command_id,
            digest=repository.payload_hash(payload.model_dump(mode="json")),
            rubric=payload.rubric.model_dump(mode="json"),
        )
    except repository.StaleRubric as exc:
        raise AppError(409, "STALE_RUBRIC", "打分规则或上游题目已经更新，请重新读取。") from exc
    except repository.RepositoryConflict as exc:
        code = "RUBRIC_ACTIVE" if "active" in str(exc) else "RUBRIC_NOT_EDITABLE"
        raise AppError(409, code, "本轮规则仍在处理，请完成后再修改。" if code == "RUBRIC_ACTIVE" else "当前打分规则不能修改。") from exc
    return _view(changed, source)


def confirm_rubric(
    workspace_id: str,
    rubric_id: str,
    payload: RubricConfirmationRequest,
    user: UserRecord,
) -> RubricDraftResponse:
    record = _authorized_rubric(workspace_id, rubric_id, user)
    source = _source(workspace_id, record.question_draft_id)
    content = _rubric_content(record)
    if content is None:
        raise AppError(409, "RUBRIC_NOT_READY", "请先生成或保存完整的打分规则。")
    outcome = _reference_outcome(content)
    if not outcome.passed:
        raise AppError(409, "REFERENCE_RUBRIC_FAILED", "标准答案按当前规则未通过，不能确认或发布。")
    try:
        changed = repository.confirm_rubric(
            record.id,
            expected_revision=payload.rubric_revision,
            source_question_revision=source.confirmed_revision,
            source_question_hash=source.confirmed_hash,
            command_id=payload.command_id,
            digest=repository.payload_hash(payload.model_dump(mode="json")),
            confirmed_by=user.id,
        )
    except repository.StaleRubric as exc:
        raise AppError(409, "STALE_RUBRIC", "打分规则或上游题目已经更新，请重新读取。") from exc
    except repository.RepositoryConflict as exc:
        raise AppError(409, "RUBRIC_NOT_READY", "当前打分规则还不能确认。") from exc
    return _view(changed, source)


def publish_rubric(
    workspace_id: str,
    rubric_id: str,
    payload: RubricPublishRequest,
    user: UserRecord,
) -> RubricDraftResponse:
    record = _authorized_rubric(workspace_id, rubric_id, user)
    source = _source(workspace_id, record.question_draft_id)
    content = _rubric_content(record)
    if content is None or not _reference_outcome(content).passed:
        raise AppError(409, "REFERENCE_RUBRIC_FAILED", "标准答案按当前规则未通过，不能发布。")
    latest_contract = case_service.get_latest_confirmed_contract(workspace_id)
    try:
        changed, _revision = repository.publish_rubric(
            record.id,
            expected_revision=payload.rubric_revision,
            source_question_revision=source.confirmed_revision,
            source_question_hash=source.confirmed_hash,
            command_id=payload.command_id,
            digest=repository.payload_hash(payload.model_dump(mode="json")),
            question_snapshot=_question_snapshot(source, require_evidence_present=True),
            reference_answer_text=source.reference_answer_text,
            published_by=user.id,
            pass_threshold=content.pass_threshold,
            contract_revision_id=latest_contract.id if latest_contract is not None else None,
        )
    except repository.StaleRubric as exc:
        raise AppError(409, "STALE_RUBRIC", "打分规则或上游题目已经更新，请重新读取。") from exc
    except repository.RepositoryConflict as exc:
        raise AppError(409, "RUBRIC_NOT_READY", "当前打分规则尚未完成确认或发布冲突。") from exc
    return _view(changed, source)


def list_revisions(workspace_id: str, question_draft_id: str, user: UserRecord) -> RubricRevisionListResponse:
    workspace_service.assert_owner(workspace_id, user)
    _source(workspace_id, question_draft_id)
    return RubricRevisionListResponse(
        question_draft_id=question_draft_id,
        revisions=[
            RubricRevisionSummary(
                id=item.id,
                question_draft_id=item.question_draft_id,
                revision=item.revision_number,
                source_question_revision=item.source_question_revision,
                pass_threshold=item.pass_threshold,
                content_sha256=item.content_sha256,
                published_at=item.published_at,
            )
            for item in repository.list_revisions(question_draft_id)
        ],
    )


def derive_draft(
    workspace_id: str,
    question_draft_id: str,
    revision_id: str,
    payload: RubricDeriveRequest,
    user: UserRecord,
) -> RubricDraftResponse:
    workspace_service.assert_owner(workspace_id, user)
    source = _source(workspace_id, question_draft_id)
    published = repository.get_revision(revision_id)
    if published is None or published.question_draft_id != question_draft_id:
        raise AppError(404, "RESOURCE_NOT_FOUND", "已发布的题目修订不存在。")
    try:
        changed = repository.derive_draft(
            revision_id=revision_id,
            workspace_id=workspace_id,
            source_question_revision=source.confirmed_revision,
            source_question_hash=source.confirmed_hash,
            command_id=payload.command_id,
            digest=repository.payload_hash(payload.model_dump(mode="json")),
        )
    except repository.StaleRubric as exc:
        raise AppError(409, "STALE_RUBRIC", "当前确认的题目已经变化，不能从旧修订派生。") from exc
    except repository.RepositoryConflict as exc:
        raise AppError(409, "RUBRIC_NOT_EDITABLE", "当前打分规则仍在处理，不能派生新草稿。") from exc
    return _view(changed, source)


def _context(source: authoring_service.ConfirmedQuestionSource, record: repository.RubricDraftRecord) -> AgentRunContext:
    profile = get_ai_profile()
    return AgentRunContext(
        user_id=source.confirmed_by,
        workspace_id=source.workspace_id,
        target_type="rubric_draft",
        target_id=record.id,
        # A rubric is one-shot for a particular business revision.  Keeping
        # the revision in the stable key prevents a fresh model retry from
        # accidentally resuming an unaccepted checkpoint from an older failed
        # generation; projection retries still use the saved result only.
        thread_key=f"rubric-{record.id}-r{record.revision}",
        business_revision=record.revision,
        teacher_answers=(),
        evidence_file_ids=tuple(source.evidence_file_ids),
        evidence_scope=f"/evidence/rubric/{record.id}",
        ai_profile_version=profile.version,
        graph_schema_version="m0-rubric-graph-v1",
        deadline=None,
    )


def _projection_payload(
    content: RubricContent,
    source: authoring_service.ConfirmedQuestionSource,
) -> dict[str, Any]:
    return {
        "rubric": content.model_dump(mode="json"),
        "status": "review_ready",
        "pending_question": None,
        "__source_question_revision": source.confirmed_revision,
        "__source_question_hash": source.confirmed_hash,
    }


def process_rubric(job: OperationJob) -> dict[str, Any]:
    from app.lib.operations.worker import ProjectionPendingOperation, SupersededOperation

    record = repository.get_draft(job.target_id)
    if record is None:
        raise AppError(404, "RESOURCE_NOT_FOUND", "打分规则草稿不存在。")
    source = _source(record.workspace_id, record.question_draft_id)
    if (
        record.revision != job.business_revision
        or record.source_question_revision != source.confirmed_revision
        or record.source_question_hash != source.confirmed_hash
    ):
        raise SupersededOperation("打分规则上游已经更新。")
    adapter = get_adapters().rubric_cocreator
    if adapter is None:
        raise RuntimeError("rubric co-creator is unavailable")
    result = adapter.generate(
        _context(source, record),
        {
            "question": _question_snapshot(source),
            "reference_answer_text": source.reference_answer_text,
        },
    )
    if not isinstance(result, AgentRunResult) or not isinstance(result.result, RubricContent):
        raise RuntimeError("rubric co-creator returned an invalid result")
    content = result.result
    _validate_rubric_text(content)
    projection = _projection_payload(content, source)
    try:
        updated = repository.commit_worker_projection(
            record.id,
            expected_revision=job.business_revision,
            operation_job_id=job.id,
            operation_attempt=job.attempts,
            worker_id=job.worker_id or "",
            source_question_revision=source.confirmed_revision,
            source_question_hash=source.confirmed_hash,
            rubric=projection["rubric"],
            status=projection["status"],
        )
    except repository.StaleRubric as exc:
        raise SupersededOperation(str(exc)) from exc
    except Exception as exc:
        operation_repository.save_result(
            job.id,
            job.worker_id or "",
            {"__rubric_projection": projection},
        )
        raise ProjectionPendingOperation(
            result_hash=repository.payload_hash(projection),
        ) from exc
    return {"rubric_id": updated.id, "status": updated.status, "revision": updated.revision}


def reproject_rubric(job: OperationJob) -> dict[str, Any]:
    from app.lib.operations.worker import ProjectionPendingOperation, SupersededOperation

    record = repository.get_draft(job.target_id)
    if record is None:
        raise AppError(404, "RESOURCE_NOT_FOUND", "打分规则草稿不存在。")
    source = _source(record.workspace_id, record.question_draft_id)
    if record.revision != job.business_revision:
        raise SupersededOperation("打分规则已经产生新修订。")
    saved = None
    for previous in operation_repository.list_for_target("rubric_draft", job.target_id):
        candidate = (previous.result or {}).get("__rubric_projection")
        if isinstance(candidate, dict):
            saved = candidate
            break
    if saved is None:
        raise RuntimeError("没有可重投影的打分规则结果")
    if (
        saved.get("__source_question_revision") != source.confirmed_revision
        or saved.get("__source_question_hash") != source.confirmed_hash
    ):
        raise SupersededOperation("已保存的规则结果属于旧题目修订。")
    content = RubricContent.model_validate(saved.get("rubric") or {})
    _validate_rubric_text(content)
    try:
        updated = repository.commit_worker_projection(
            record.id,
            expected_revision=job.business_revision,
            operation_job_id=job.id,
            operation_attempt=job.attempts,
            worker_id=job.worker_id or "",
            source_question_revision=source.confirmed_revision,
            source_question_hash=source.confirmed_hash,
            rubric=content.model_dump(mode="json"),
            status="review_ready",
        )
    except repository.StaleRubric as exc:
        raise SupersededOperation(str(exc)) from exc
    except Exception as exc:
        operation_repository.save_result(
            job.id,
            job.worker_id or "",
            {"__rubric_projection": saved},
        )
        raise ProjectionPendingOperation(result_hash=repository.payload_hash(saved)) from exc
    return {"rubric_id": updated.id, "status": updated.status, "revision": updated.revision}
