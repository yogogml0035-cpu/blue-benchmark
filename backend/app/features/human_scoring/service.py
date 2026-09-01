"""Business rules for submitting and deterministically scoring one answer."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any, TYPE_CHECKING
from uuid import uuid4

from fastapi import UploadFile

from app.features.auth.repository import UserRecord
from app.features.case_builder.authoring_schemas import BadSample, QuestionInput
from app.features.evaluation_sets import service as evaluation_sets_service
from app.features.evaluation_sets.rubric_schemas import (
    CriticalMode,
    RubricContent,
    validate_public_rubric_text,
)
from app.features.human_scoring import repository
from app.features.human_scoring.schemas import (
    MAX_SUBMISSION_BYTES,
    HumanScoreHistoryResponse,
    HumanScoreItemView,
    HumanScoreResponse,
    HumanScoreView,
    HumanSubmissionResponse,
    QuestionRevisionView,
    ScoreCreateRequest,
    SubmissionCreateRequest,
    SubmissionView,
)
from app.features.workspaces import service as workspace_service
from app.lib.errors import AppError
from app.lib.storage import LocalStorage, StorageError, sha256_bytes

if TYPE_CHECKING:
    from app.features.evaluation_sets.rubric_repository import QuestionRevisionRecord


_ALLOWED_EXTENSIONS = {"md": "text/markdown", "txt": "text/plain"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _authorized_revision(
    workspace_id: str,
    question_revision_id: str,
    user: UserRecord,
) -> QuestionRevisionRecord:
    workspace_service.assert_owner(workspace_id, user)
    revision = evaluation_sets_service.get_published_question_revision(workspace_id, question_revision_id)
    evaluation_sets_service.assert_accepts_evaluation_write(workspace_id, revision.question_draft_id, "提交待评结果")
    return revision


def _authorized_submission(
    workspace_id: str,
    submission_id: str,
    user: UserRecord,
) -> repository.SubmissionRecord:
    workspace_service.assert_owner(workspace_id, user)
    submission = repository.get_submission(submission_id)
    if submission is None:
        raise AppError(404, "RESOURCE_NOT_FOUND", "待评答卷不存在。")
    if submission.workspace_id != workspace_id:
        raise AppError(403, "FORBIDDEN", "你无权访问这份待评答卷。")
    try:
        revision = evaluation_sets_service.get_published_question_revision(
            workspace_id,
            submission.question_revision_id,
        )
    except AppError as exc:
        if exc.code in {"RESOURCE_NOT_FOUND", "FORBIDDEN"}:
            raise AppError(500, "SUBMISSION_REVISION_INVALID", "待评答卷绑定的题目修订无法读取。") from exc
        raise
    if revision.workspace_id != workspace_id:
        raise AppError(500, "SUBMISSION_REVISION_INVALID", "待评答卷绑定的题目修订无法读取。")
    return submission


def _validated_revision_view(
    revision: QuestionRevisionRecord,
) -> QuestionRevisionView:
    try:
        snapshot = revision.question_snapshot
        if not isinstance(snapshot, dict):
            raise ValueError("question snapshot is not an object")
        question_input = QuestionInput.model_validate(snapshot.get("input") or {})
        rubric = RubricContent.model_validate(revision.rubric)
        validate_public_rubric_text(rubric)
        title = str(snapshot.get("title") or "已发布题目").strip()
        summary = str(snapshot.get("summary") or question_input.task_instruction).strip()
        if not title or not summary or revision.pass_threshold != rubric.pass_threshold:
            raise ValueError("question revision snapshot is incomplete")
    except (AttributeError, TypeError, ValueError) as exc:
        raise AppError(500, "QUESTION_REVISION_INVALID", "已发布的题目修订无法读取。") from exc
    return QuestionRevisionView(
        id=revision.id,
        revision_number=revision.revision_number,
        title=title,
        summary=summary,
        question_input=question_input,
        bad_samples=[BadSample.model_validate(item) for item in revision.bad_samples],
        reference_answer_text=revision.reference_answer_text,
        criteria=rubric.criteria,
        pass_threshold=revision.pass_threshold,
    )


def _revision_views_for_submission(
    submission: repository.SubmissionRecord,
    original_revision: QuestionRevisionRecord,
) -> dict[str, QuestionRevisionView]:
    revisions = evaluation_sets_service.get_published_question_revisions_for_question(
        submission.workspace_id,
        original_revision.question_draft_id,
    )
    views = {item.id: _validated_revision_view(item) for item in revisions}
    views.setdefault(original_revision.id, _validated_revision_view(original_revision))
    return views


def _score_revision(
    workspace_id: str,
    submission: repository.SubmissionRecord,
    original_revision: QuestionRevisionRecord,
    question_revision_id: str,
) -> QuestionRevisionRecord:
    revision = evaluation_sets_service.get_published_question_revision(
        workspace_id,
        question_revision_id,
    )
    if revision.question_draft_id != original_revision.question_draft_id:
        raise AppError(409, "SCORE_REVISION_MISMATCH", "重评只能使用同一道逻辑题的已发布修订。")
    return revision


def _read_submission_text(submission: repository.SubmissionRecord) -> str:
    storage = LocalStorage()
    try:
        if not storage.is_ready(submission.content_storage_key):
            raise StorageError("submission is not ready")
        content = storage.read_bytes(submission.content_storage_key)
    except (StorageError, OSError) as exc:
        raise AppError(500, "SUBMISSION_STORAGE_INVALID", "待评答卷暂时无法读取。") from exc
    if len(content) != submission.size_bytes or sha256_bytes(content) != submission.sha256:
        raise AppError(500, "SUBMISSION_STORAGE_INVALID", "待评答卷完整性校验失败。")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise AppError(500, "SUBMISSION_STORAGE_INVALID", "待评答卷暂时无法读取。") from exc
    if not text.strip():
        raise AppError(500, "SUBMISSION_STORAGE_INVALID", "待评答卷内容为空。")
    return text


def _submission_view(submission: repository.SubmissionRecord, content_text: str) -> SubmissionView:
    return SubmissionView(
        id=submission.id,
        workspace_id=submission.workspace_id,
        question_revision_id=submission.question_revision_id,
        source=submission.source,
        original_name=submission.original_name,
        media_type=submission.media_type,
        size_bytes=submission.size_bytes,
        sha256=submission.sha256,
        content_text=content_text,
        submitted_at=submission.submitted_at,
    )


def _score_view(score: repository.ScoreRecord) -> HumanScoreView:
    return HumanScoreView(
        id=score.id,
        submission_id=score.submission_id,
        question_revision_id=score.question_revision_id,
        parent_score_id=score.parent_score_id,
        status="submitted",
        items=[
            HumanScoreItemView(
                criterion_id=item.criterion_id,
                score=item.score,
                reason=item.reason,
                hard_fail_triggered=item.hard_fail_triggered,
                critical_passed=item.critical_passed,
            )
            for item in score.items
        ],
        overall_reason=score.overall_reason,
        total_score=score.total_score,
        critical_passed=score.critical_passed,
        passed=score.passed,
        submitted_at=score.submitted_at,
    )


def _submission_response(
    submission: repository.SubmissionRecord,
) -> HumanSubmissionResponse:
    revision = evaluation_sets_service.get_published_question_revision(
        submission.workspace_id,
        submission.question_revision_id,
    )
    if revision.workspace_id != submission.workspace_id:
        raise AppError(500, "SUBMISSION_REVISION_INVALID", "待评答卷绑定的题目修订无法读取。")
    content_text = _read_submission_text(submission)
    question_revisions = _revision_views_for_submission(submission, revision)
    return HumanSubmissionResponse(
        submission=_submission_view(submission, content_text),
        question_revision=_validated_revision_view(revision),
        question_revisions=question_revisions,
        scores=[_score_view(item) for item in repository.list_scores(submission.id)],
    )


def get_submission(
    workspace_id: str,
    submission_id: str,
    user: UserRecord,
) -> HumanSubmissionResponse:
    return _submission_response(_authorized_submission(workspace_id, submission_id, user))


def get_score_history(
    workspace_id: str,
    submission_id: str,
    user: UserRecord,
) -> HumanScoreHistoryResponse:
    submission = _authorized_submission(workspace_id, submission_id, user)
    revision = evaluation_sets_service.get_published_question_revision(
        workspace_id,
        submission.question_revision_id,
    )
    return HumanScoreHistoryResponse(
        submission_id=submission.id,
        question_revisions=_revision_views_for_submission(submission, revision),
        scores=[_score_view(item) for item in repository.list_scores(submission.id)],
    )


def _submission_digest(
    *,
    question_revision_id: str,
    source: str,
    original_name: str | None,
    content: bytes,
) -> tuple[str, str, int]:
    digest = sha256_bytes(content)
    size_bytes = len(content)
    command_payload_hash = repository.payload_hash(
        {
            "question_revision_id": question_revision_id,
            "source": source,
            "original_name": original_name,
            "sha256": digest,
            "size_bytes": size_bytes,
        }
    )
    return command_payload_hash, digest, size_bytes


def _cleanup_storage(storage: LocalStorage, *keys: str | None) -> None:
    failures: list[str] = []
    for key in keys:
        if not key:
            continue
        try:
            storage.delete(key)
        except (StorageError, OSError):
            failures.append("storage cleanup failed")
    if failures:
        raise StorageError("submission storage cleanup failed")


def _store_submission(
    *,
    workspace_id: str,
    question_revision_id: str,
    source: str,
    original_name: str | None,
    media_type: str,
    content: bytes,
    command_id: str,
    user: UserRecord,
) -> HumanSubmissionResponse:
    # Do this before reading or decoding caller-provided bytes. A caller must
    # not learn upload validation details for a workspace or revision it
    # cannot use, nor spend storage/CPU before authorization succeeds.
    revision = _authorized_revision(workspace_id, question_revision_id, user)
    _validated_revision_view(revision)
    if len(content) > MAX_SUBMISSION_BYTES:
        raise AppError(
            413,
            "FILE_TOO_LARGE",
            "待评答卷超过 1 MiB 限制。",
            {"max_bytes": MAX_SUBMISSION_BYTES},
        )
    try:
        text_content = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise AppError(422, "INVALID_UTF8", "待评答卷必须是 UTF-8 文本。") from exc
    if not text_content.strip():
        raise AppError(422, "EMPTY_SUBMISSION", "待评答卷内容不能为空。")

    digest, content_hash, size_bytes = _submission_digest(
        question_revision_id=question_revision_id,
        source=source,
        original_name=original_name,
        content=content,
    )
    existing = repository.get_submission_by_command(workspace_id, command_id)
    if existing is not None:
        if existing.payload_hash != digest:
            raise AppError(409, "COMMAND_ID_REUSED", "相同命令已经用于另一份待评答卷。")
        return _submission_response(existing)

    submission_id = str(uuid4())
    storage = LocalStorage()
    staged_key: str | None = None
    final_key = f"submissions/{submission_id}/content"
    published = False
    persisted = False
    try:
        staged = storage.stage_bytes(f"human-scoring/{submission_id}", "content", content)
        staged_key = staged.key
        storage.publish(staged.key, final_key)
        published = True
        record = repository.SubmissionRecord(
            id=submission_id,
            workspace_id=workspace_id,
            question_revision_id=question_revision_id,
            content_storage_key=final_key,
            source=source,
            original_name=original_name,
            media_type=media_type,
            size_bytes=size_bytes,
            sha256=content_hash,
            command_id=command_id,
            payload_hash=digest,
            submitted_by=user.id,
            submitted_at=_now(),
        )
        try:
            inserted, duplicate = repository.add_submission(record)
        except repository.RepositoryConflict as exc:
            raise AppError(409, "COMMAND_ID_REUSED", "相同命令已经用于另一份待评答卷。") from exc
        if duplicate:
            if inserted.payload_hash != digest:
                raise AppError(409, "COMMAND_ID_REUSED", "相同命令已经用于另一份待评答卷。")
            return _submission_response(inserted)
        persisted = True
        return _submission_response(inserted)
    finally:
        if not persisted:
            _cleanup_storage(storage, final_key if published else None, staged_key)


def create_pasted_submission(
    workspace_id: str,
    question_revision_id: str,
    payload: SubmissionCreateRequest,
    user: UserRecord,
) -> HumanSubmissionResponse:
    return _store_submission(
        workspace_id=workspace_id,
        question_revision_id=question_revision_id,
        source="paste",
        original_name=None,
        media_type="text/plain",
        content=payload.content_text.encode("utf-8"),
        command_id=payload.command_id,
        user=user,
    )


def reconcile_submission_storage() -> int:
    """Reclaim ready/staged files left by a crashed submission request."""

    return LocalStorage().reconcile_submission_objects(repository.list_submission_ids())


def _upload_name(filename: str | None, reported_media_type: str | None) -> tuple[str, str]:
    name = (filename or "").strip()
    if not name or "\x00" in name or "/" in name or "\\" in name:
        raise AppError(415, "UNSUPPORTED_FILE_TYPE", "只支持单个 Markdown 或 TXT 文件。")
    path = PurePosixPath(name)
    if path.is_absolute() or name in {".", ".."} or len(name) > 512:
        raise AppError(415, "UNSUPPORTED_FILE_TYPE", "只支持单个 Markdown 或 TXT 文件。")
    extension = name.rsplit(".", 1)[-1].casefold() if "." in name else ""
    media_type = _ALLOWED_EXTENSIONS.get(extension)
    if media_type is None:
        raise AppError(415, "UNSUPPORTED_FILE_TYPE", "只支持单个 Markdown 或 TXT 文件。")
    reported = (reported_media_type or "").split(";", 1)[0].strip().casefold()
    allowed_reported = {"", "application/octet-stream", media_type, "text/plain"}
    if reported not in allowed_reported:
        raise AppError(415, "UNSUPPORTED_FILE_TYPE", "文件类型与扩展名不匹配。")
    return name, media_type


async def create_uploaded_submission(
    workspace_id: str,
    question_revision_id: str,
    command_id: str,
    uploads: list[UploadFile],
    user: UserRecord,
) -> HumanSubmissionResponse:
    # Authorize before inspecting the filename or consuming upload bytes.
    revision = _authorized_revision(workspace_id, question_revision_id, user)
    _validated_revision_view(revision)
    if len(uploads) != 1:
        raise AppError(422, "SINGLE_FILE_REQUIRED", "一次只能上传一个 Markdown 或 TXT 文件。")
    command_id = command_id.strip()
    if not command_id:
        raise AppError(422, "VALIDATION_ERROR", "命令编号不能为空。")
    upload = uploads[0]
    name, media_type = _upload_name(upload.filename, upload.content_type)
    content = await upload.read(MAX_SUBMISSION_BYTES + 1)
    return _store_submission(
        workspace_id=workspace_id,
        question_revision_id=question_revision_id,
        source="file",
        original_name=name,
        media_type=media_type,
        content=content,
        command_id=command_id,
        user=user,
    )


def _score_digest(payload: ScoreCreateRequest, question_revision_id: str) -> str:
    items = [item.model_dump(mode="json") for item in payload.items]
    items.sort(key=lambda item: str(item["criterion_id"]))
    return repository.payload_hash(
        {
            "items": items,
            "overall_reason": payload.overall_reason,
            "parent_score_id": payload.parent_score_id,
            "question_revision_id": question_revision_id,
        }
    )


def _validated_score_items(
    rubric: RubricContent,
    payload: ScoreCreateRequest,
) -> tuple[list[dict[str, Any]], int, bool, bool]:
    criteria = {criterion.id: criterion for criterion in rubric.criteria}
    if len(payload.items) != len(criteria) or len({item.criterion_id for item in payload.items}) != len(payload.items):
        raise AppError(422, "SCORE_ITEMS_INCOMPLETE", "必须为每个评分项提交一次分数。")
    if set(criteria) != {item.criterion_id for item in payload.items}:
        raise AppError(422, "SCORE_ITEMS_INCOMPLETE", "评分项与已发布规则不一致。")

    received = {item.criterion_id: item for item in payload.items}
    result: list[dict[str, Any]] = []
    total = 0
    critical_passed = True
    for criterion in rubric.criteria:
        item = received[criterion.id]
        if item.score > criterion.max_score:
            raise AppError(422, "SCORE_OUT_OF_RANGE", f"评分项“{criterion.name}”的分数超过满分。")
        if criterion.critical_mode == CriticalMode.hard_fail:
            if item.hard_fail_triggered is None:
                raise AppError(422, "HARD_FAIL_DECISION_REQUIRED", f"请确认关键项“{criterion.name}”是否命中一票否决条件。")
        elif item.hard_fail_triggered is not None:
            raise AppError(422, "HARD_FAIL_DECISION_NOT_ALLOWED", f"评分项“{criterion.name}”不接受一票否决判定。")

        if criterion.critical_mode == CriticalMode.minimum:
            item_critical_passed = (
                criterion.critical_min_score is not None
                and item.score >= criterion.critical_min_score
            )
        elif criterion.critical_mode == CriticalMode.hard_fail:
            item_critical_passed = not bool(item.hard_fail_triggered)
        else:
            item_critical_passed = True
        needs_reason = item.score < criterion.reference_expected_score or not item_critical_passed
        if needs_reason and not item.reason:
            raise AppError(422, "SCORE_REASON_REQUIRED", f"评分项“{criterion.name}”低于标准或未通过关键项，请填写理由。")

        total += item.score
        critical_passed = critical_passed and item_critical_passed
        result.append(
            {
                "criterion_id": criterion.id,
                "score": item.score,
                "reason": item.reason,
                "hard_fail_triggered": item.hard_fail_triggered,
                "critical_passed": item_critical_passed,
            }
        )
    return result, total, critical_passed, total >= rubric.pass_threshold and critical_passed


def submit_score(
    workspace_id: str,
    submission_id: str,
    payload: ScoreCreateRequest,
    user: UserRecord,
) -> HumanScoreResponse:
    submission = _authorized_submission(workspace_id, submission_id, user)
    original_revision = evaluation_sets_service.get_published_question_revision(
        workspace_id,
        submission.question_revision_id,
    )
    if original_revision.workspace_id != workspace_id:
        raise AppError(500, "SUBMISSION_REVISION_INVALID", "待评答卷绑定的题目修订无法读取。")
    evaluation_sets_service.assert_accepts_evaluation_write(workspace_id, original_revision.question_draft_id, "追加评分")
    # A score is a claim about the exact bytes that were reviewed. Recheck the
    # ready marker, length and digest before accepting a new immutable result.
    _read_submission_text(submission)
    history = repository.list_scores(submission.id)
    latest = history[-1] if history else None
    existing = repository.get_score_by_command(submission.id, payload.command_id)
    target_revision_id = (
        payload.question_revision_id
        if payload.question_revision_id is not None
        else existing.question_revision_id
        if existing is not None
        else latest.question_revision_id
        if latest is not None
        else submission.question_revision_id
    )
    revision = _score_revision(workspace_id, submission, original_revision, target_revision_id)
    if latest is None and target_revision_id != submission.question_revision_id:
        raise AppError(409, "SCORE_REVISION_MISMATCH", "首次评分必须使用待评结果绑定的原题目修订。")

    try:
        rubric = RubricContent.model_validate(revision.rubric)
        validate_public_rubric_text(rubric)
    except (TypeError, ValueError) as exc:
        raise AppError(500, "QUESTION_REVISION_INVALID", "已发布的题目修订无法读取。") from exc

    digest = _score_digest(payload, target_revision_id)
    if existing is not None:
        if existing.payload_hash != digest:
            raise AppError(409, "COMMAND_ID_REUSED", "相同命令已经用于另一份评分。")
        return HumanScoreResponse(score=_score_view(existing))

    if latest is not None and payload.parent_score_id is None:
        raise AppError(409, "PARENT_SCORE_REQUIRED", "这份答卷已有评分，请从最新记录开始重新评分。")

    if payload.parent_score_id:
        parent = repository.get_score(payload.parent_score_id)
        if parent is None or parent.submission_id != submission.id:
            raise AppError(422, "INVALID_PARENT_SCORE", "重评必须基于当前答卷的历史评分。")
        if latest is None or parent.id != latest.id:
            raise AppError(409, "PARENT_SCORE_STALE", "请从最新一条评分记录开始重新评分。")

    items, total, critical_passed, passed = _validated_score_items(rubric, payload)
    try:
        score, duplicate = repository.add_score(
            submission_id=submission.id,
            question_revision_id=target_revision_id,
            parent_score_id=payload.parent_score_id,
            total_score=total,
            critical_passed=critical_passed,
            passed=passed,
            overall_reason=payload.overall_reason,
            command_id=payload.command_id,
            digest=digest,
            scored_by=user.id,
            submitted_at=_now(),
            items=items,
        )
    except repository.ScoreParentConflict as exc:
        raise AppError(409, "PARENT_SCORE_STALE", "请从最新一条评分记录开始重新评分。") from exc
    except repository.RepositoryConflict as exc:
        raise AppError(409, "COMMAND_ID_REUSED", "相同命令已经用于另一份评分。") from exc
    if duplicate:
        if score.payload_hash != digest:
            raise AppError(409, "COMMAND_ID_REUSED", "相同命令已经用于另一份评分。")
    return HumanScoreResponse(score=_score_view(score))
