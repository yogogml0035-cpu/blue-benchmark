"""Scene-scoped question library service: batch intake, editing, publication."""

from __future__ import annotations

import unicodedata
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.features.question_library import deletion, repository, rubric_generation
from app.features.question_library.schemas import (
    BatchUploadRequest,
    BatchUploadResponse,
    CaseReceipt,
    CriteriaPatchRequest,
    CriterionView,
    DeleteAcceptedResponse,
    DeleteStateView,
    GenerationErrorView,
    NextAction,
    OperationAcceptedResponse,
    QuestionCommandRequest,
    QuestionDeleteRequest,
    QuestionDetailResponse,
    QuestionLibraryResponse,
    QuestionListItem,
    QuestionSaveRegenerateRequest,
    QuestionStatus,
    QuestionTitleRequest,
    RunEventView,
    RunEventsResponse,
    assert_case_materials_private,
    assert_public_material_text,
    canonical_payload_hash,
    NEXT_ACTION_BY_STATUS,
)
from app.features.scenes.service import ScenePrincipal, ensure_scene_exists
from app.lib.database import session_scope
from app.lib.database.models import EvalQuestionRow
from app.lib.errors import AppError
from pydantic import ValidationError


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _next_action(status: str, criteria_confirmed: bool) -> NextAction:
    """`pending_review` splits on teacher confirmation: review vs. publish."""

    question_status = QuestionStatus(status)
    if question_status == QuestionStatus.pending_review:
        return NextAction.publish if criteria_confirmed else NextAction.review_criteria
    return NEXT_ACTION_BY_STATUS[question_status]


def _detail_response(record: repository.QuestionRecord) -> QuestionDetailResponse:
    return QuestionDetailResponse(
        id=record.id,
        scene_id=record.scene_id,
        scene_name=record.scene_name,
        client_case_id=record.client_case_id,
        title=record.title,
        task_prompt=record.task_prompt,
        reference_examples=[
            {
                "client_ref_id": item.get("client_ref_id", ""),
                "source_name": item.get("source_name"),
                "content_text": item.get("content_text", ""),
            }
            for item in record.reference_examples
        ],
        bad_cases=[
            {
                "content_text": item.get("content_text", ""),
                "teacher_feedback_texts": list(item.get("teacher_feedback_texts") or []),
                "reason_summary": item.get("reason_summary"),
            }
            for item in record.bad_cases
        ],
        reference_answer=record.reference_answer,
        memory_materials=[
            {
                "client_ref_id": item.get("client_ref_id", ""),
                "source_label": item.get("source_label"),
                "content_text": item.get("content_text", ""),
            }
            for item in record.memory_materials
        ],
        criteria=(
            [_criterion_view(item) for item in record.criteria]
            if record.criteria is not None
            else None
        ),
        status=QuestionStatus(record.status),
        next_action=_next_action(record.status, record.criteria_confirmed),
        content_revision=record.content_revision,
        active_operation_id=record.active_operation_id,
        last_error=(
            GenerationErrorView(
                code=str(record.last_error.get("code", "")),
                message=str(record.last_error.get("message", "")),
            )
            if record.last_error
            else None
        ),
        deletion=_deletion_view(record.id),
        criteria_confirmed=record.criteria_confirmed,
        delete_confirmation_required=record.ever_published,
        created_at=_iso(record.created_at) or "",
        updated_at=_iso(record.updated_at) or "",
        published_at=_iso(record.published_at),
    )


def _criterion_view(item: dict) -> CriterionView:
    """Project one stored criterion dict onto the complete view contract.

    The stored shape IS the contract shape (one-shot cutover; no legacy
    two-field records are read or back-filled).
    """
    return CriterionView.model_validate(item)


def _deletion_view(question_id: str) -> DeleteStateView | None:
    job = deletion.get_active_cleanup(question_id)
    if job is None:
        return None
    error = None
    if job.last_error and job.status.value == "failed":
        error = GenerationErrorView(
            code=str(job.last_error.get("code", "")),
            message=str(job.last_error.get("message", "")),
        )
    return DeleteStateView(operation_id=job.id, phase=job.status.value, error=error)


def _ensure_not_frozen(row, operation: str) -> None:
    if row.status == QuestionStatus.deleting.value:
        raise AppError(
            409,
            "QUESTION_DELETING",
            f"题目删除清理中，{operation}已被冻结；清理完成前不可继续。",
        )


# ---------------------------------------------------------------------------
# Batch intake
# ---------------------------------------------------------------------------


def batch_upload(principal: ScenePrincipal, payload: BatchUploadRequest) -> BatchUploadResponse:
    payload_hash = canonical_payload_hash(payload)
    now = _utc_now()
    try:
        with session_scope() as session:
            existing = repository.get_command(session, principal.scene_id, payload.command_id)
            replay = _replay_response(existing, payload, payload_hash, principal.scene_id)
            if replay is not None:
                return replay

            _validate_batch_cases(session, principal.scene_id, payload)

            try:
                receipt = repository.reserve_command(
                    session,
                    scene_id=principal.scene_id,
                    credential_id=principal.credential_id,
                    command_id=payload.command_id,
                    payload_hash=payload_hash,
                    now=now,
                )
            except ValueError as exc:
                if str(exc) != "COMMAND_EXISTS":
                    raise
                current = repository.get_command(
                    session, principal.scene_id, payload.command_id
                )
                replay = _replay_response(current, payload, payload_hash, principal.scene_id)
                if replay is not None:
                    return replay
                raise AppError(409, "COMMAND_IN_PROGRESS", "相同命令正在处理中。") from exc
            case_receipts: list[CaseReceipt] = []
            for case in payload.cases:
                record = repository.create_question(
                    session,
                    scene_id=principal.scene_id,
                    client_case_id=case.client_case_id,
                    title=case.title,
                    task_prompt=case.task_prompt,
                    reference_examples=[item.model_dump() for item in case.reference_examples],
                    bad_cases=[item.model_dump() for item in case.bad_cases],
                    reference_answer=case.reference_answer,
                    memory_materials=[item.model_dump() for item in case.memory_materials],
                    now=now,
                )
                job_id = rubric_generation.enqueue_generation(
                    session,
                    question_id=record.id,
                    content_revision=record.content_revision,
                    command_id=rubric_generation.derived_command_id(
                        "rubric-gen", payload.command_id, case.client_case_id
                    ),
                )
                updated = repository.update_fields(
                    session,
                    record.id,
                    expected_revision=record.content_revision,
                    now=now,
                    active_operation_id=job_id,
                )
                if updated is None:  # pragma: no cover - same transaction, cannot conflict
                    raise AppError(500, "INTERNAL_ERROR", "题目写入失败。")
                case_receipts.append(
                    CaseReceipt(
                        client_case_id=case.client_case_id,
                        question_id=record.id,
                        status=QuestionStatus.generating,
                    )
                )
            repository.complete_command(
                session,
                receipt.id,
                result={"cases": [item.model_dump() for item in case_receipts]},
                now=now,
            )
        return BatchUploadResponse(
            command_id=payload.command_id,
            scene_id=principal.scene_id,
            accepted_case_count=len(case_receipts),
            cases=case_receipts,
        )
    except IntegrityError as exc:
        # Distinguish the expected concurrent client_case_id collision from any
        # other integrity failure, which must surface as a conflict rather than
        # a misleading CASE_ALREADY_EXISTS.
        detail = str(exc.orig) if exc.orig else str(exc)
        if "uq_eval_question_scene_client_case" in detail or "client_case_id" in detail:
            raise AppError(
                409,
                "CASE_ALREADY_EXISTS",
                "该场景已存在相同 client_case_id 的题目，整批未创建。",
            ) from exc
        if "uq_batch_upload_command" in detail:
            raise AppError(409, "COMMAND_IN_PROGRESS", "相同命令正在处理中。") from exc
        raise AppError(409, "BATCH_CONFLICT", "批量写入发生冲突，整批未创建。") from exc


def _replay_response(
    receipt: repository.CommandReceipt | None,
    payload: BatchUploadRequest,
    payload_hash: str,
    scene_id: str,
) -> BatchUploadResponse | None:
    """Return the stored result for an identical replayed command, or raise."""

    if receipt is None:
        return None
    if receipt.payload_hash != payload_hash:
        raise AppError(
            409,
            "COMMAND_ID_REUSED",
            "相同命令已经用于另一份上传内容；内容变化后必须使用新命令。",
        )
    if receipt.status == "ready" and receipt.result:
        cases = [CaseReceipt(**item) for item in receipt.result.get("cases", [])]
        return BatchUploadResponse(
            command_id=payload.command_id,
            scene_id=scene_id,
            accepted_case_count=len(cases),
            cases=cases,
        )
    raise AppError(409, "COMMAND_IN_PROGRESS", "相同命令正在处理中。")


def _validate_batch_cases(session, scene_id: str, payload: BatchUploadRequest) -> None:
    problems: list[dict[str, Any]] = []
    for index, case in enumerate(payload.cases):
        case_problems: list[dict[str, Any]] = []
        try:
            assert_case_materials_private(case)
        except AppError as exc:
            case_problems.append({"code": exc.code, "message": exc.message})
        existing = session.execute(
            select(EvalQuestionRow.id).where(
                EvalQuestionRow.scene_id == scene_id,
                EvalQuestionRow.client_case_id == case.client_case_id,
            )
        ).first()
        if existing is not None:
            case_problems.append(
                {"code": "CASE_ALREADY_EXISTS", "message": "该场景已存在相同 client_case_id 的题目。"}
            )
        if case_problems:
            problems.append(
                {"index": index, "client_case_id": case.client_case_id, "problems": case_problems}
            )
    if problems:
        raise AppError(
            422,
            "BATCH_CASE_INVALID",
            "批次内容校验失败，未创建任何题目。",
            details={"cases": problems},
        )


# ---------------------------------------------------------------------------
# Library queries
# ---------------------------------------------------------------------------


def list_library(
    *, scene_id: str, status: QuestionStatus | None = None
) -> QuestionLibraryResponse:
    ensure_scene_exists(scene_id)
    with session_scope() as session:
        records = repository.list_questions(
            session, scene_id=scene_id, status=status.value if status else None
        )
    items = [
        QuestionListItem(
            id=record.id,
            scene_id=record.scene_id,
            scene_name=record.scene_name,
            client_case_id=record.client_case_id,
            title=record.title,
            status=QuestionStatus(record.status),
            rubric_criterion_count=(
                len(record.criteria) if record.criteria is not None else None
            ),
            criteria_confirmed=record.criteria_confirmed,
            next_action=_next_action(record.status, record.criteria_confirmed),
            created_at=_iso(record.created_at) or "",
            updated_at=_iso(record.updated_at) or "",
            published_at=_iso(record.published_at),
        )
        for record in records
    ]
    return QuestionLibraryResponse(items=items, total=len(items))


def get_detail(question_id: str) -> QuestionDetailResponse:
    with session_scope() as session:
        record = repository.get_question(session, question_id)
    if record is None:
        raise AppError(404, "RESOURCE_NOT_FOUND", "题目不存在。")
    return _detail_response(record)


# ---------------------------------------------------------------------------
# Editing, generation, publication
# ---------------------------------------------------------------------------


def update_title(question_id: str, payload: QuestionTitleRequest) -> QuestionDetailResponse:
    """Title-only edits never touch the six materials or rubric generation."""

    title = payload.title.strip()
    assert_public_material_text(title, field_label="用例标题")
    now = _utc_now()
    with session_scope() as session:
        existing = session.get(EvalQuestionRow, question_id)
        if existing is None:
            raise AppError(404, "RESOURCE_NOT_FOUND", "题目不存在。")
        _ensure_not_frozen(existing, "标题修改")
        record = repository.update_fields(
            session,
            question_id,
            expected_revision=payload.content_revision,
            now=now,
            title=title,
        )
    if record is None:
        _raise_stale_or_missing(question_id)
    return _detail_response(record)


def save_and_regenerate(
    question_id: str, payload: QuestionSaveRegenerateRequest
) -> OperationAcceptedResponse:
    """The only material edit action: overwrite content and queue regeneration.

    Publishing state is deliberately not consulted — editing a published
    question overwrites it and returns the question to pending processing.
    The material overwrite and the revision bump commit through one
    conditional UPDATE keyed on ``content_revision``; the queued generation
    job lives in the same transaction and rolls back with it.
    """

    now = _utc_now()
    with session_scope() as session:
        row = session.get(EvalQuestionRow, question_id)
        if row is None:
            raise AppError(404, "RESOURCE_NOT_FOUND", "题目不存在。")
        if row.content_revision != payload.content_revision:
            raise AppError(409, "STALE_REVISION", "题目内容已被更新，请基于最新内容重试。")
        _ensure_not_frozen(row, "材料保存与重新生成")

        new_title = payload.title.strip() if payload.title is not None else row.title
        new_prompt = payload.task_prompt.strip() if payload.task_prompt is not None else row.task_prompt
        new_answer = (
            payload.reference_answer.strip()
            if payload.reference_answer is not None
            else row.reference_answer
        )
        new_examples = (
            [item.model_dump() for item in payload.reference_examples]
            if payload.reference_examples is not None
            else list(row.reference_examples_json or [])
        )
        new_bad_cases = (
            [item.model_dump() for item in payload.bad_cases]
            if payload.bad_cases is not None
            else list(row.bad_cases_json or [])
        )
        new_memory = (
            [item.model_dump() for item in payload.memory_materials]
            if payload.memory_materials is not None
            else list(row.memory_materials_json or [])
        )

        # A no-op save would destroy reviewed criteria and burn an AI call
        # without changing any material; reject it explicitly.
        if (
            new_title == row.title
            and new_prompt == row.task_prompt
            and new_answer == row.reference_answer
            and new_examples == list(row.reference_examples_json or [])
            and new_bad_cases == list(row.bad_cases_json or [])
            and new_memory == list(row.memory_materials_json or [])
        ):
            raise AppError(409, "NO_MATERIAL_CHANGE", "材料没有变化，无需重新生成。")

        # Backstop privacy scan on the merged content before persisting it.
        from app.features.question_library.schemas import (
            BadCaseIn,
            CaseIn,
            MemoryMaterialIn,
            ReferenceExampleIn,
        )

        try:
            merged_case = CaseIn(
                client_case_id=row.client_case_id,
                title=new_title,
                task_prompt=new_prompt,
                reference_examples=[ReferenceExampleIn(**item) for item in new_examples],
                bad_cases=[BadCaseIn(**item) for item in new_bad_cases],
                reference_answer=new_answer,
                memory_materials=[MemoryMaterialIn(**item) for item in new_memory],
            )
        except ValidationError as exc:
            first = exc.errors()[0] if exc.errors() else {}
            raise AppError(
                422,
                "VALIDATION_ERROR",
                str(first.get("msg") or "材料内容无效。"),
                details={"fields": [{"loc": list(first.get("loc", [])), "message": str(first.get("msg", ""))}]},
            ) from exc
        assert_case_materials_private(merged_case)

        new_revision = row.content_revision + 1
        job_id = rubric_generation.enqueue_generation(
            session,
            question_id=question_id,
            content_revision=new_revision,
            command_id=rubric_generation.derived_command_id(
                "regenerate", question_id, str(new_revision), payload.command_id
            ),
        )
        record = repository.update_fields(
            session,
            question_id,
            expected_revision=payload.content_revision,
            now=now,
            title=new_title,
            task_prompt=new_prompt,
            reference_answer=new_answer,
            reference_examples_json=new_examples,
            bad_cases_json=new_bad_cases,
            memory_materials_json=new_memory,
            content_revision=new_revision,
            criteria_json=None,
            criteria_confirmed=False,
            status=QuestionStatus.generating.value,
            published_at=None,
            last_error_json=None,
            active_operation_id=job_id,
        )
        if record is None:
            raise AppError(409, "STALE_REVISION", "题目内容已被更新，请基于最新内容重试。")
    return OperationAcceptedResponse(
        question_id=question_id,
        status=QuestionStatus.generating,
        operation_id=job_id,
    )


def patch_criteria(question_id: str, payload: CriteriaPatchRequest) -> QuestionDetailResponse:
    now = _utc_now()
    criteria = [item.model_dump() for item in payload.criteria]
    with session_scope() as session:
        row = session.get(EvalQuestionRow, question_id)
        if row is None:
            raise AppError(404, "RESOURCE_NOT_FOUND", "题目不存在。")
        if row.content_revision != payload.content_revision:
            raise AppError(409, "STALE_REVISION", "题目内容已被更新，请基于最新内容重试。")
        _ensure_not_frozen(row, "评分维度修改")
        if row.status == QuestionStatus.generating.value:
            raise AppError(
                409,
                "RUBRIC_GENERATING",
                "评分维度生成中，等待生成完成后再修改。",
            )
        if row.status == QuestionStatus.published.value:
            raise AppError(
                409,
                "PUBLISHED_REOPEN_REQUIRED",
                "已发布题目必须先重新打开审改，才能修改评分维度。",
            )
        values: dict[str, Any] = {
            "criteria_json": criteria,
            "criteria_confirmed": True,
            "active_operation_id": None,
        }
        if row.status == QuestionStatus.generation_failed.value:
            values["status"] = QuestionStatus.pending_review.value
            values["last_error_json"] = None
        record = repository.update_fields(
            session,
            question_id,
            expected_revision=payload.content_revision,
            now=now,
            extra_conditions=[
                EvalQuestionRow.status.in_(
                    [
                        QuestionStatus.pending_review.value,
                        QuestionStatus.generation_failed.value,
                    ]
                )
            ],
            **values,
        )
        if record is None:
            raise AppError(409, "STALE_REVISION", "题目内容已被更新，请基于最新内容重试。")
    return get_detail(question_id)


def retry_generation(question_id: str, payload: QuestionCommandRequest) -> OperationAcceptedResponse:
    now = _utc_now()
    with session_scope() as session:
        row = session.get(EvalQuestionRow, question_id)
        if row is None:
            raise AppError(404, "RESOURCE_NOT_FOUND", "题目不存在。")
        _ensure_not_frozen(row, "生成重试")
        if row.status != QuestionStatus.generation_failed.value:
            raise AppError(
                409,
                "RETRY_NOT_AVAILABLE",
                "只有评分维度生成失败的题目可以重试。",
            )
        if payload.content_revision != row.content_revision:
            raise AppError(409, "STALE_REVISION", "题目内容已被更新，请基于最新内容重试。")
        job_id = rubric_generation.enqueue_generation(
            session,
            question_id=question_id,
            content_revision=row.content_revision,
            command_id=rubric_generation.derived_command_id(
                "retry", question_id, str(row.content_revision), payload.command_id
            ),
        )
        record = repository.update_fields(
            session,
            question_id,
            expected_revision=payload.content_revision,
            now=now,
            expected_status=QuestionStatus.generation_failed.value,
            status=QuestionStatus.generating.value,
            active_operation_id=job_id,
            last_error_json=None,
        )
        if record is None:
            raise AppError(409, "STALE_REVISION", "题目内容已被更新，请基于最新内容重试。")
    return OperationAcceptedResponse(
        question_id=question_id,
        status=QuestionStatus.generating,
        operation_id=job_id,
    )


def publish(question_id: str, payload: QuestionCommandRequest) -> QuestionDetailResponse:
    now = _utc_now()
    with session_scope() as session:
        row = session.get(EvalQuestionRow, question_id)
        if row is None:
            raise AppError(404, "RESOURCE_NOT_FOUND", "题目不存在。")
        if payload.content_revision != row.content_revision:
            raise AppError(409, "STALE_REVISION", "题目内容已被更新，请基于最新内容重试。")
        _ensure_not_frozen(row, "发布")
        if row.status == QuestionStatus.generating.value:
            raise AppError(409, "RUBRIC_GENERATING", "评分维度生成中，无法发布。")
        if row.status == QuestionStatus.generation_failed.value:
            raise AppError(409, "GENERATION_FAILED", "评分维度生成失败，请先重试生成。")
        if row.status == QuestionStatus.published.value:
            raise AppError(409, "ALREADY_PUBLISHED", "题目已经发布，无需重复发布。")
        if not row.criteria_json:
            raise AppError(409, "CRITERIA_MISSING", "题目缺少评分维度，无法发布。")
        if not row.criteria_confirmed:
            raise AppError(
                409,
                "CRITERIA_NOT_CONFIRMED",
                "AI 候选维度必须经老师保存确认后才能发布。",
            )
        # Fold the source-state and confirmation gates into the atomic CAS:
        # a concurrent criteria patch or publish cannot slip in between the
        # snapshot checks above and this commit.
        record = repository.update_fields(
            session,
            question_id,
            expected_revision=payload.content_revision,
            now=now,
            expected_status=QuestionStatus.pending_review.value,
            extra_conditions=[
                EvalQuestionRow.criteria_confirmed.is_(True),
                EvalQuestionRow.criteria_json.is_not(None),
            ],
            status=QuestionStatus.published.value,
            published_at=now,
            ever_published=True,
        )
        if record is None:
            raise AppError(409, "STALE_REVISION", "题目内容已被更新，请基于最新内容重试。")
    return get_detail(question_id)


def review_reopen(question_id: str, payload: QuestionCommandRequest) -> QuestionDetailResponse:
    """Reopen a published question for review without regenerating.

    Materials, criteria and the teacher-confirmation fact are preserved; only
    the current publication timestamp is cleared. No version, snapshot or
    history is created.
    """

    now = _utc_now()
    with session_scope() as session:
        row = session.get(EvalQuestionRow, question_id)
        if row is None:
            raise AppError(404, "RESOURCE_NOT_FOUND", "题目不存在。")
        if payload.content_revision != row.content_revision:
            raise AppError(409, "STALE_REVISION", "题目内容已被更新，请基于最新内容重试。")
        _ensure_not_frozen(row, "重新打开审改")
        if row.status != QuestionStatus.published.value:
            raise AppError(
                409,
                "REVIEW_REOPEN_NOT_AVAILABLE",
                "只有已发布的题目可以重新打开审改。",
            )
        record = repository.update_fields(
            session,
            question_id,
            expected_revision=payload.content_revision,
            now=now,
            expected_status=QuestionStatus.published.value,
            status=QuestionStatus.pending_review.value,
            published_at=None,
        )
        if record is None:
            raise AppError(409, "STALE_REVISION", "题目内容已被更新，请基于最新内容重试。")
    return get_detail(question_id)


def delete_question(question_id: str, payload: QuestionDeleteRequest) -> DeleteAcceptedResponse:
    """Protected delete ACCEPTANCE: freeze + durable cleanup operation.

    Gates, in order: stale revision, already deleting, generating, still
    published, and — for any question that was ever published — an exact title
    confirmation checked against the persisted ``ever_published`` fact.
    Acceptance atomically freezes the question and enqueues the cross-store
    cleanup in ONE business transaction; success is reported only after every
    online trace is verified gone (the old "204 = deleted" early-success path
    is removed, not wrapped).
    """

    now = _utc_now()
    with session_scope() as session:
        row = session.get(EvalQuestionRow, question_id)
        if row is None:
            existing = deletion.get_active_cleanup(question_id)
            if existing is not None:
                # The question row is already gone but the receipt survives:
                # replay the acceptance idempotently instead of 404-ing a
                # client that is still polling cleanup status.
                raise AppError(
                    404,
                    "RESOURCE_NOT_FOUND",
                    "题目不存在。",
                )
            raise AppError(404, "RESOURCE_NOT_FOUND", "题目不存在。")
        if row.status == QuestionStatus.deleting.value:
            active = deletion.get_active_cleanup(question_id)
            if active is None:
                raise AppError(500, "INTERNAL_ERROR", "删除状态不一致，请联系管理员。")
            return DeleteAcceptedResponse(
                question_id=question_id,
                status=QuestionStatus.deleting,
                operation_id=active.id,
            )
        if payload.content_revision != row.content_revision:
            raise AppError(409, "STALE_REVISION", "题目内容已被更新，请基于最新内容重试。")
        if row.status == QuestionStatus.generating.value:
            raise AppError(
                409,
                "RUBRIC_GENERATING",
                "评分维度生成中，等待生成完成或失败后再删除。",
            )
        if row.status == QuestionStatus.published.value:
            raise AppError(
                409,
                "PUBLISHED_REOPEN_REQUIRED",
                "已发布题目必须先重新打开审改，才能删除。",
            )
        if row.ever_published:
            provided = (
                unicodedata.normalize("NFC", payload.confirmation_title).strip()
                if payload.confirmation_title is not None
                else ""
            )
            current = unicodedata.normalize("NFC", row.title).strip()
            if provided != current:
                raise AppError(
                    422,
                    "DELETE_CONFIRMATION_MISMATCH",
                    "该题目曾经发布过，必须输入当前完整题目标题确认删除。",
                )
        try:
            operation_id = deletion.accept_delete(
                session, question_row=row, command_id=payload.command_id, now=now
            )
        except ValueError as exc:
            if str(exc) == "CLEANUP_ALREADY_SUCCEEDED":
                raise AppError(404, "RESOURCE_NOT_FOUND", "题目不存在。") from exc
            raise
    return DeleteAcceptedResponse(
        question_id=question_id,
        status=QuestionStatus.deleting,
        operation_id=operation_id,
    )


# ---------------------------------------------------------------------------
# Public run events (persisted log; SSE reads from the database)
# ---------------------------------------------------------------------------


def get_run_events(
    question_id: str, operation_id: str, *, after_sequence: int = 0
) -> RunEventsResponse:
    """One page of the complete public event log for an operation.

    Authorization: admin session (enforced by the router). Replay is frozen
    once deletion is accepted — cleanup must not keep serving originals.
    """
    with session_scope() as session:
        row = session.get(EvalQuestionRow, question_id)
        if row is None:
            raise AppError(404, "RESOURCE_NOT_FOUND", "题目不存在。")
        if row.status == QuestionStatus.deleting.value:
            raise AppError(409, "QUESTION_DELETING", "题目删除清理中，运行记录已冻结。")
        status = QuestionStatus(row.status)
        if row.active_operation_id is not None and row.active_operation_id != operation_id:
            raise AppError(409, "OPERATION_SUPERSEDED", "该运行已被新一轮任务取代。")
    from app.features.question_library import run_streams

    events = run_streams.read_events(
        question_id, operation_id, after_sequence=after_sequence
    )
    return RunEventsResponse(
        question_id=question_id,
        operation_id=operation_id,
        status=status,
        events=[
            RunEventView(
                sequence=event.sequence,
                kind=event.kind,
                stage=event.stage,
                text=event.text,
                tool=event.tool,
                detail=event.detail,
                attempt=event.attempt,
                created_at=event.created_at,
            )
            for event in events
        ],
        last_sequence=events[-1].sequence if events else after_sequence,
    )


def _raise_stale_or_missing(question_id: str) -> None:
    with session_scope() as session:
        exists = repository.question_exists(session, question_id)
    if not exists:
        raise AppError(404, "RESOURCE_NOT_FOUND", "题目不存在。")
    raise AppError(409, "STALE_REVISION", "题目内容已被更新，请基于最新内容重试。")
