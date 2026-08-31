"""Business orchestration for the first-stage benchmark authoring flow."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import re

from app.features.auth.repository import UserRecord
from app.features.case_builder import authoring_repository as repository
from app.features.case_builder import ingestion_repository
from app.features.case_builder.authoring_schemas import (
    AuthoringConversationCreateRequest,
    AuthoringConversationResponse,
    AuthoringConversationStatus,
    AuthoringConversationView,
    AuthoringEventListResponse,
    AuthoringEventView,
    AuthoringMessageRequest,
    AuthoringMessageRole,
    AuthoringMessageType,
    AuthoringNextAction,
    AuthoringOperationView,
    AuthoringQuestion,
    AuthoringRetryRequest,
    AuthoringContinuityResetRequest,
    BenchmarkQuestionDraftView,
    InputAnswerConfirmationRequest,
    InputAnswerPatchRequest,
    QuestionBoundaryRequest,
    QuestionDraftStatus,
    QuestionInput,
    QuestionMaterialView,
)
from app.features.workspaces import service as workspace_service
from app.lib.ai_runtime import AgentRunContext, get_adapters, get_ai_profile
from app.lib.ai_runtime.evidence import documents_for_files
from app.lib.ai_runtime.profile import GRAPH_SCHEMA_VERSION
from app.lib.errors import AppError
from app.lib.operations import repository as operation_repository
from app.lib.operations.repository import OperationJob, OperationJobStatus


_ACTIVE_JOB_STATUSES = {OperationJobStatus.queued, OperationJobStatus.running}
_VISIBLE_JOB_STATUSES = {
    OperationJobStatus.queued,
    OperationJobStatus.running,
    OperationJobStatus.failed,
    OperationJobStatus.projection_pending,
}
_FORBIDDEN_PUBLIC_TERMS = (
    "private_reasoning",
    "system prompt",
    "system_prompt",
    "checkpoint",
    "thread_id",
    "storage_key",
    "api_key",
    "api key",
    "access token",
    "secret",
    "credential",
    "password",
    "密码",
    "凭证",
    "访问令牌",
    "系统提示",
    "私有推理",
    "绝对路径",
    "存储键",
    "线程标识",
)
_CJK = re.compile(r"[\u3400-\u9fff]")
_TASK_HEADING = re.compile(
    r"^\s*(?:#{1,6}\s*)?(?:任务|题目|交付物)\s*(?:[0-9]+|[A-Za-z]|[一二三四五六七八九十]+)\s*[：:、\-\.]\s*(.*)$",
    re.MULTILINE,
)


def _public_text(value: str, fallback: str) -> str:
    candidate = " ".join(str(value or "").split()).strip()
    if not candidate or not _CJK.search(candidate):
        return fallback
    if any(term in candidate.casefold() for term in _FORBIDDEN_PUBLIC_TERMS):
        return fallback
    if "/" in candidate or "\\" in candidate or "file://" in candidate.casefold():
        return fallback
    return candidate[:2_000]


def _authorized_conversation(
    workspace_id: str,
    conversation_id: str,
    user: UserRecord,
) -> repository.AuthoringConversationRecord:
    workspace_service.assert_owner(workspace_id, user)
    conversation = repository.get_conversation(conversation_id)
    if conversation is None:
        raise AppError(404, "RESOURCE_NOT_FOUND", "建题会话不存在。")
    if conversation.workspace_id != workspace_id:
        raise AppError(403, "FORBIDDEN", "你无权访问这个建题会话。")
    return conversation


def _authorized_draft(
    workspace_id: str,
    conversation_id: str,
    draft_id: str,
    user: UserRecord,
) -> tuple[repository.AuthoringConversationRecord, repository.QuestionDraftRecord]:
    conversation = _authorized_conversation(workspace_id, conversation_id, user)
    draft = next((item for item in repository.list_drafts(conversation_id) if item.id == draft_id), None)
    if draft is None:
        raise AppError(404, "RESOURCE_NOT_FOUND", "题目草稿不存在。")
    return conversation, draft


def _files_for_conversation(
    conversation: repository.AuthoringConversationRecord,
) -> list[ingestion_repository.EvidenceFileRecord]:
    if not conversation.upload_batch_id:
        return []
    batch = ingestion_repository.get_batch(conversation.upload_batch_id)
    if batch is None or batch.workspace_id != conversation.workspace_id:
        return []
    files = ingestion_repository.list_files(conversation.upload_batch_id)
    files = [item for item in files if item.workspace_id == conversation.workspace_id]
    if not conversation.source_file_ids:
        return files
    selected = set(conversation.source_file_ids)
    return [item for item in files if item.id in selected]


def _validate_file_ids(
    conversation: repository.AuthoringConversationRecord,
    file_ids: list[str],
) -> None:
    files = _files_for_conversation(conversation)
    allowed = {item.id for item in files}
    if set(file_ids) - allowed:
        raise AppError(422, "INVALID_EVIDENCE_SCOPE", "只能引用当前会话资料批次中的文件。")


def _active_job(conversation: repository.AuthoringConversationRecord) -> OperationJob | None:
    jobs = operation_repository.list_for_target("authoring_conversation", conversation.id)
    for job in jobs:
        if job.status in _VISIBLE_JOB_STATUSES and (
            job.id == conversation.active_operation_id or job.business_revision == conversation.revision
        ):
            return job
    return None


def _draft_view(
    draft: repository.QuestionDraftRecord,
    files: dict[str, ingestion_repository.EvidenceFileRecord],
) -> BenchmarkQuestionDraftView:
    question_input = QuestionInput.model_validate(draft.input)
    materials = [
        QuestionMaterialView(
            **item.model_dump(mode="json"),
            file_name=files.get(item.file_id).original_name if files.get(item.file_id) else None,
        )
        for item in question_input.materials
    ]
    return BenchmarkQuestionDraftView(
        id=draft.id,
        conversation_id=draft.conversation_id,
        title=draft.title,
        summary=draft.summary,
        status=QuestionDraftStatus(draft.status),
        revision=draft.revision,
        input=question_input,
        reference_answer_text=draft.reference_answer_text,
        reference_answer_source=draft.reference_answer_source,
        evidence_file_ids=list(draft.evidence_file_ids),
        materials=materials,
        confirmed_revision=draft.confirmed_revision,
        confirmed_at=draft.confirmed_at,
    )


def _next_action(
    conversation: repository.AuthoringConversationRecord,
    drafts: list[repository.QuestionDraftRecord],
    job: OperationJob | None,
) -> AuthoringNextAction:
    if conversation.status == AuthoringConversationStatus.continuity_reset.value:
        return AuthoringNextAction.continuity_reset
    if job and job.status in _ACTIVE_JOB_STATUSES:
        return AuthoringNextAction.wait_for_processing
    if job and job.status in {OperationJobStatus.failed, OperationJobStatus.projection_pending}:
        return AuthoringNextAction.retry_processing
    active = [item for item in drafts if item.status != QuestionDraftStatus.discarded.value]
    if not active:
        return AuthoringNextAction.none
    if any(item.status == QuestionDraftStatus.candidate.value for item in active):
        return AuthoringNextAction.confirm_question_boundaries
    if conversation.pending_question:
        return AuthoringNextAction.provide_standard_answer
    if any(item.status != QuestionDraftStatus.input_answer_confirmed.value for item in active):
        if any(not item.reference_answer_text for item in active):
            return AuthoringNextAction.provide_standard_answer
        return AuthoringNextAction.confirm_input_answer
    return AuthoringNextAction.none


def _conversation_response(conversation: repository.AuthoringConversationRecord) -> AuthoringConversationResponse:
    files = {item.id: item for item in _files_for_conversation(conversation)}
    drafts = repository.list_drafts(conversation.id)
    messages = repository.list_messages(conversation.id)
    job = _active_job(conversation)
    display_status = conversation.status
    if job and (
        conversation.active_operation_id == job.id or job.business_revision == conversation.revision
    ):
        if job and job.status == OperationJobStatus.projection_pending:
            display_status = AuthoringConversationStatus.projection_pending.value
        elif job and job.status == OperationJobStatus.failed:
            display_status = AuthoringConversationStatus.failed.value
    pending = AuthoringQuestion.model_validate(conversation.pending_question) if conversation.pending_question else None
    blocking: list[str] = []
    if pending is not None:
        blocking.append(pending.reason)
    if display_status == AuthoringConversationStatus.failed.value:
        blocking.append("本轮整理没有完成，你的已保存内容仍然保留。")
    if any(
        item.status != QuestionDraftStatus.discarded.value
        and any(material.role.value == "unconfirmed" for material in QuestionInput.model_validate(item.input).materials)
        for item in drafts
    ):
        blocking.append("还有资料用途或优先级没有确认。")
    if conversation.upload_batch_id and not any(
        item.parse_state == "parsed" and not item.ignored for item in files.values()
    ):
        blocking.append("当前没有可用于形成题目的资料，请检查资料是否可读且未被忽略。")
    return AuthoringConversationResponse(
        conversation=AuthoringConversationView(
            id=conversation.id,
            workspace_id=conversation.workspace_id,
            upload_batch_id=conversation.upload_batch_id,
            source_file_count=len(files),
            title=conversation.title,
            status=AuthoringConversationStatus(display_status),
            revision=conversation.revision,
            messages=[
                # Assistant messages are inserted only after validation; keep
                # teacher messages visible so refresh can restore the transcript.
                {
                    "id": item.id,
                    "sequence": item.sequence,
                    "role": AuthoringMessageRole(item.role),
                    "message_type": AuthoringMessageType(item.message_type),
                    "content": item.content,
                    "attachment_ids": list(item.attachment_ids),
                    "question_draft_id": item.question_draft_id,
                    "created_at": item.created_at,
                }
                for item in messages
                if item.role == AuthoringMessageRole.teacher.value or item.verified
            ],
            question_drafts=[_draft_view(item, files) for item in drafts],
            pending_question=pending,
            next_action=_next_action(conversation, drafts, job),
            active_operation=(
                AuthoringOperationView(kind=job.kind, status=job.status.value)
                if job and job.status in _VISIBLE_JOB_STATUSES
                else None
            ),
            events_cursor=repository.latest_event_sequence(conversation.id),
            blocking_issues=blocking,
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
        )
    )


def get_conversation(
    workspace_id: str,
    conversation_id: str,
    user: UserRecord,
) -> AuthoringConversationResponse:
    return _conversation_response(_authorized_conversation(workspace_id, conversation_id, user))


def _enqueue(
    conversation: repository.AuthoringConversationRecord,
    *,
    command_id: str,
    kind: str = "authoring_process",
) -> repository.AuthoringConversationRecord:
    job: OperationJob | None = None
    try:
        job = operation_repository.create_or_get(
            kind=kind,
            target_type="authoring_conversation",
            target_id=conversation.id,
            command_id=command_id,
            business_revision=conversation.revision,
        )
        return repository.set_active_operation(
            conversation.id,
            job.id,
            expected_revision=conversation.revision,
        )
    except operation_repository.OperationCommandConflict as exc:
        raise AppError(409, "COMMAND_ID_REUSED", "相同命令已经用于另一种后台操作。") from exc
    except Exception:
        # Do not let an enqueue failure from an old request overwrite a newer
        # conversation branch.  The guarded projection also closes the small
        # race where a fast Worker finishes between create_or_get and attach.
        current = repository.get_conversation(conversation.id)
        if (
            current is not None
            and current.revision == conversation.revision
            and current.status == AuthoringConversationStatus.processing.value
            and current.active_operation_id is None
        ):
            repository.mark_failed(
                conversation.id,
                "OPERATION_ENQUEUE_FAILED",
                expected_revision=conversation.revision,
                expected_operation_id=job.id if job is not None else None,
            )
        raise


def create_conversation(
    workspace_id: str,
    payload: AuthoringConversationCreateRequest,
    user: UserRecord,
) -> AuthoringConversationResponse:
    workspace_service.assert_owner(workspace_id, user)
    digest = repository.payload_hash(payload.model_dump(mode="json"))
    existing = repository.get_conversation_by_command(workspace_id, payload.command_id)
    if existing is not None:
        if existing.command_payload_hash != digest:
            raise AppError(409, "COMMAND_ID_REUSED", "相同命令已经用于不同的建题内容。")
        if existing.status == AuthoringConversationStatus.processing.value and _active_job(existing) is None:
            try:
                _enqueue(existing, command_id=payload.command_id)
                existing = repository.get_conversation(existing.id) or existing
            except Exception as exc:
                raise AppError(503, "AUTHORING_UNAVAILABLE", "建题后台暂时不可用，请稍后重试。") from exc
        return _conversation_response(existing)
    if payload.upload_batch_id:
        batch = ingestion_repository.get_batch(payload.upload_batch_id)
        if batch is None:
            raise AppError(404, "RESOURCE_NOT_FOUND", "资料批次不存在。")
        if batch.workspace_id != workspace_id:
            raise AppError(403, "FORBIDDEN", "你无权使用这个资料批次。")
        files = ingestion_repository.list_files(batch.id)
        selected = payload.source_file_ids or [item.id for item in files]
        _validate_file_ids(
            repository.AuthoringConversationRecord(
                id="new",
                workspace_id=workspace_id,
                upload_batch_id=batch.id,
                title=payload.title,
                task_instruction=payload.task_instruction,
                source_file_ids=list(payload.source_file_ids),
                command_id=payload.command_id,
                command_payload_hash=digest,
                status="new",
                revision=0,
                active_operation_id=None,
                pending_question=None,
                command_receipts={},
                created_by=user.id,
                created_at=batch.created_at,
                updated_at=batch.updated_at,
            ),
            selected,
        )
    elif payload.source_file_ids:
        raise AppError(422, "INVALID_EVIDENCE_SCOPE", "没有资料批次时不能引用文件。")
    conversation = repository.create_conversation(
        workspace_id=workspace_id,
        upload_batch_id=payload.upload_batch_id,
        title=payload.title,
        task_instruction=payload.task_instruction,
        source_file_ids=(payload.source_file_ids or ([item.id for item in files] if payload.upload_batch_id else [])),
        command_id=payload.command_id,
        command_payload_hash=digest,
        created_by=user.id,
        initial_message=payload.message or payload.task_instruction,
        initial_reference_answer=payload.reference_answer_text,
    )
    if conversation.command_payload_hash != digest:
        raise AppError(409, "COMMAND_ID_REUSED", "相同命令已经用于不同的建题内容。")
    try:
        _enqueue(conversation, command_id=payload.command_id)
    except AppError:
        raise
    except Exception as exc:
        raise AppError(503, "AUTHORING_UNAVAILABLE", "建题后台暂时不可用，请稍后重试。") from exc
    return _conversation_response(repository.get_conversation(conversation.id) or conversation)


def post_message(
    workspace_id: str,
    conversation_id: str,
    payload: AuthoringMessageRequest,
    user: UserRecord,
) -> AuthoringConversationResponse:
    conversation = _authorized_conversation(workspace_id, conversation_id, user)
    _validate_file_ids(conversation, payload.attachment_ids)
    pending = conversation.pending_question or {}
    effective_question_draft_id = payload.question_draft_id
    if payload.message_type == AuthoringMessageType.standard_answer:
        pending_draft_id = pending.get("question_draft_id")
        if not pending_draft_id or pending_draft_id != payload.question_draft_id:
            raise AppError(
                409,
                "STANDARD_ANSWER_NOT_REQUESTED",
                "当前没有要求补充这道题的标准答案。",
            )
        if not any(
            item.id == pending_draft_id and item.status != QuestionDraftStatus.discarded.value
            for item in repository.list_drafts(conversation.id)
        ):
            raise AppError(409, "QUESTION_NOT_READY", "这道题已经不存在或已被舍弃。")
    elif pending.get("question_draft_id"):
        pending_draft_id = str(pending["question_draft_id"])
        if payload.question_draft_id not in {None, pending_draft_id}:
            raise AppError(409, "QUESTION_NOT_PENDING", "请先回答当前正在等待的这道题。")
        effective_question_draft_id = pending_draft_id
        if not any(
            item.id == pending_draft_id and item.status != QuestionDraftStatus.discarded.value
            for item in repository.list_drafts(conversation.id)
        ):
            raise AppError(409, "QUESTION_NOT_READY", "这道题已经不存在或已被舍弃。")
    elif payload.question_draft_id is not None and not any(
        item.id == payload.question_draft_id and item.status != QuestionDraftStatus.discarded.value
        for item in repository.list_drafts(conversation.id)
    ):
        raise AppError(409, "QUESTION_NOT_READY", "这道题不存在或已经被舍弃。")
    digest = repository.payload_hash(
        {
            "content": payload.content,
            "message_type": payload.message_type.value,
            "question_draft_id": effective_question_draft_id,
            "attachment_ids": payload.attachment_ids,
        }
    )
    try:
        updated, _message, duplicate = repository.append_teacher_message(
            conversation.id,
            expected_revision=payload.conversation_revision,
            command_id=payload.command_id,
            content=payload.content,
            message_type=payload.message_type.value,
            question_draft_id=effective_question_draft_id,
            attachment_ids=payload.attachment_ids,
            command_payload_hash=digest,
        )
    except repository.StaleProjection as exc:
        raise AppError(409, "STALE_AUTHORING", "会话已经更新，请刷新后再提交。") from exc
    except repository.RepositoryConflict as exc:
        message = str(exc)
        if "active operation" in message:
            code, user_message = "AUTHORING_ACTIVE", "本轮 AI 还在处理，请等待完成后再发送。"
        elif "updated concurrently" in message:
            code, user_message = "STALE_AUTHORING", "会话已经更新，请刷新后再提交。"
        else:
            code, user_message = "COMMAND_ID_REUSED", "相同命令已经提交过不同的内容。"
        raise AppError(409, code, user_message) from exc
    if duplicate:
        if updated.status == AuthoringConversationStatus.processing.value and _active_job(updated) is None:
            try:
                updated = _enqueue(updated, command_id=payload.command_id)
            except Exception as exc:
                raise AppError(503, "AUTHORING_UNAVAILABLE", "建题后台暂时不可用，你的消息已保存，请稍后重试。") from exc
        return _conversation_response(updated)
    try:
        _enqueue(updated, command_id=payload.command_id)
    except Exception as exc:
        raise AppError(503, "AUTHORING_UNAVAILABLE", "建题后台暂时不可用，你的消息已保存，请稍后重试。") from exc
    return _conversation_response(repository.get_conversation(conversation_id) or updated)


def mutate_boundaries(
    workspace_id: str,
    conversation_id: str,
    payload: QuestionBoundaryRequest,
    user: UserRecord,
) -> AuthoringConversationResponse:
    conversation = _authorized_conversation(workspace_id, conversation_id, user)
    _validate_file_ids(
        conversation,
        [file_id for group in payload.groups for file_id in group.evidence_file_ids],
    )
    try:
        updated = repository.mutate_boundaries(
            conversation.id,
            expected_revision=payload.conversation_revision,
            command_id=payload.command_id,
            action=payload.action,
            draft_ids=payload.draft_ids,
            groups=[group.model_dump(mode="json") for group in payload.groups],
            digest=repository.payload_hash(payload.model_dump(mode="json")),
        )
    except repository.StaleProjection as exc:
        raise AppError(409, "STALE_AUTHORING", "会话已经更新，请刷新后再确认题目边界。") from exc
    except ValueError as exc:
        raise AppError(422, "INVALID_QUESTION_BOUNDARY", "题目边界必须使用不重复且完整的资料范围。") from exc
    except repository.RepositoryConflict as exc:
        error_text = str(exc)
        if "active operation" in error_text:
            code, message = "AUTHORING_ACTIVE", "本轮 AI 还在处理，请等待完成后再操作。"
        elif "candidate question draft" in error_text:
            code, message = "QUESTION_BOUNDARY_LOCKED", "只有尚未确认边界的候选题可以修改。"
        else:
            code, message = "COMMAND_ID_REUSED", "相同命令已经提交过不同的边界内容。"
        raise AppError(409, code, message) from exc
    if payload.action == "confirm" and updated.revision == conversation.revision + 1:
        active = repository.list_drafts(updated.id, include_discarded=False)
        if active and not any(item.status == QuestionDraftStatus.candidate.value for item in active):
            try:
                updated = _enqueue(updated, command_id=payload.command_id)
            except Exception as exc:
                raise AppError(503, "AUTHORING_UNAVAILABLE", "题目边界已保存，但下一轮整理暂时不可用，请稍后重试。") from exc
    return _conversation_response(repository.get_conversation(conversation.id) or updated)


def patch_input_answer(
    workspace_id: str,
    conversation_id: str,
    draft_id: str,
    payload: InputAnswerPatchRequest,
    user: UserRecord,
) -> AuthoringConversationResponse:
    conversation, draft = _authorized_draft(workspace_id, conversation_id, draft_id, user)
    _validate_file_ids(conversation, [item.file_id for item in payload.input.materials])
    try:
        repository.update_draft_input(
            draft.id,
            expected_revision=payload.draft_revision,
            command_id=payload.command_id,
            digest=repository.payload_hash(payload.model_dump(mode="json")),
            input_json=payload.input.model_dump(mode="json"),
            reference_answer_text=payload.reference_answer_text,
            source_refs=draft.source_refs,
        )
    except repository.StaleProjection as exc:
        raise AppError(409, "STALE_QUESTION_DRAFT", "题目草稿已经更新，请刷新后再保存。") from exc
    except repository.RepositoryConflict as exc:
        code = "AUTHORING_ACTIVE" if "active operation" in str(exc) else "QUESTION_NOT_EDITABLE"
        raise AppError(409, code, "本轮 AI 还在处理，请等待完成后再编辑。" if code == "AUTHORING_ACTIVE" else "当前题目边界尚未确认或已经舍弃。") from exc
    return _conversation_response(repository.get_conversation(conversation.id) or conversation)


def confirm_input_answer(
    workspace_id: str,
    conversation_id: str,
    draft_id: str,
    payload: InputAnswerConfirmationRequest,
    user: UserRecord,
) -> AuthoringConversationResponse:
    conversation, draft = _authorized_draft(workspace_id, conversation_id, draft_id, user)
    try:
        repository.confirm_draft(
            draft.id,
            expected_revision=payload.draft_revision,
            command_id=payload.command_id,
            confirmed_by=user.id,
            digest=repository.payload_hash(payload.model_dump(mode="json")),
        )
    except repository.StaleProjection as exc:
        raise AppError(409, "STALE_QUESTION_DRAFT", "题目草稿已经更新，请刷新后再确认。") from exc
    except repository.RepositoryConflict as exc:
        text = str(exc)
        if "active operation" in text:
            code, message = "AUTHORING_ACTIVE", "本轮 AI 还在处理，请等待完成后再确认。"
        elif "roles" in text:
            code, message = "MATERIAL_ROLES_NOT_CONFIRMED", "请先确认每份资料的角色和优先级。"
        elif "standard answer" in text:
            code, message = "STANDARD_ANSWER_REQUIRED", "请先补充老师终版或明确认可的标准答案。"
        elif "already decided" in text:
            code, message = "QUESTION_ALREADY_CONFIRMED", "这道题已经确认。"
        else:
            code, message = "QUESTION_NOT_READY", "当前题目还不能确认，请先完成题目边界和内容审阅。"
        raise AppError(409, code, message) from exc
    return _conversation_response(repository.get_conversation(conversation.id) or conversation)


def retry_conversation(
    workspace_id: str,
    conversation_id: str,
    payload: AuthoringRetryRequest,
    user: UserRecord,
) -> AuthoringConversationResponse:
    conversation = _authorized_conversation(workspace_id, conversation_id, user)
    previous_job = _active_job(conversation)
    digest = repository.payload_hash(payload.model_dump(mode="json"))
    try:
        queued_result = repository.queue_retry(
            conversation.id,
            payload.conversation_revision,
            command_id=payload.command_id,
            digest=digest,
        )
    except repository.RepositoryConflict as exc:
        if "payload conflicts" in str(exc):
            raise AppError(409, "COMMAND_ID_REUSED", "相同命令已经提交过不同的重试内容。") from exc
        raise AppError(409, "RETRY_NOT_AVAILABLE", "当前没有可重试的后台整理。") from exc
    if queued_result is None:
        raise AppError(409, "STALE_AUTHORING", "会话已经更新，请刷新后再重试。")
    queued, duplicate = queued_result
    if duplicate:
        return _conversation_response(queued)
    try:
        kind = (
            "authoring_reproject"
            if previous_job and (previous_job.result or {}).get("__authoring_projection")
            else "authoring_process"
        )
        _enqueue(queued, command_id=payload.command_id, kind=kind)
    except Exception as exc:
        raise AppError(503, "AUTHORING_UNAVAILABLE", "重试暂时不可用，请稍后再试。") from exc
    return _conversation_response(repository.get_conversation(conversation.id) or queued)


def reset_continuity(
    workspace_id: str,
    conversation_id: str,
    payload: AuthoringContinuityResetRequest,
    user: UserRecord,
) -> AuthoringConversationResponse:
    conversation = _authorized_conversation(workspace_id, conversation_id, user)
    digest = repository.payload_hash(payload.model_dump(mode="json"))
    try:
        reset_result = repository.reset_continuity(
            conversation.id,
            conversation.revision,
            command_id=payload.command_id,
            digest=digest,
        )
    except repository.RepositoryConflict as exc:
        if "payload conflicts" in str(exc):
            raise AppError(409, "COMMAND_ID_REUSED", "相同命令已经提交过不同的重置内容。") from exc
        raise AppError(409, "CONTINUITY_RESET_NOT_REQUIRED", "当前会话不需要重新建立连续性。") from exc
    if reset_result is None:
        raise AppError(409, "STALE_AUTHORING", "会话已经更新，请刷新后重试。")
    reset, duplicate = reset_result
    if duplicate:
        return _conversation_response(reset)
    try:
        _enqueue(reset, command_id=payload.command_id)
    except Exception as exc:
        raise AppError(503, "AUTHORING_UNAVAILABLE", "会话重置暂时不可用。") from exc
    return _conversation_response(repository.get_conversation(conversation.id) or reset)


def list_events(
    workspace_id: str,
    conversation_id: str,
    user: UserRecord,
    *,
    after: int = 0,
) -> AuthoringEventListResponse:
    conversation = _authorized_conversation(workspace_id, conversation_id, user)
    events = repository.list_events(conversation.id, after=after)
    return AuthoringEventListResponse(
        conversation_id=conversation.id,
        events=[
            AuthoringEventView(
                sequence=item.sequence,
                kind=item.kind,
                payload=item.payload,
                created_at=item.created_at,
            )
            for item in events
        ],
        next_cursor=repository.latest_event_sequence(conversation.id),
    )


@dataclass(frozen=True, slots=True)
class _Candidate:
    title: str
    summary: str
    evidence_file_ids: list[str]


def _manual_candidates(text: str | None, fallback_title: str) -> list[_Candidate]:
    source = (text or "").strip()
    if not source:
        return [_Candidate(fallback_title, "老师手动输入的一个独立任务。", [])]
    matches = list(_TASK_HEADING.finditer(source))
    if len(matches) >= 2:
        candidates: list[_Candidate] = []
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(source)
            body = " ".join(source[match.start() : end].split())
            title = match.group(1).strip() or f"候选题 {index + 1}"
            candidates.append(_Candidate(title[:200], body[:2_000], []))
        return candidates
    return [_Candidate(fallback_title, " ".join(source.split())[:2_000], [])]


def _materials(
    file_ids: list[str],
    files: dict[str, ingestion_repository.EvidenceFileRecord],
) -> list[dict[str, Any]]:
    # The upload feature predates authoring and uses runtime/judge/provenance
    # roles.  Only the two unambiguous meanings can be carried forward; the
    # other legacy roles must be re-confirmed instead of being cast into a
    # different authoring meaning.
    legacy_role_map = {"brief": "brief", "runtime": "fact"}
    return [
        {
            "file_id": file_id,
            "role": legacy_role_map.get(files[file_id].role, "unconfirmed"),
            "priority": index,
            "rationale": None,
        }
        for index, file_id in enumerate(file_ids)
        if file_id in files and not files[file_id].ignored
    ]


def _authoring_context(
    conversation: repository.AuthoringConversationRecord,
    file_ids: list[str],
) -> AgentRunContext:
    profile = get_ai_profile()
    teacher_messages = [
        item.content[:4_000]
        for item in repository.list_messages(conversation.id)
        if item.role == AuthoringMessageRole.teacher.value
    ][-12:]
    return AgentRunContext(
        user_id=conversation.created_by,
        workspace_id=conversation.workspace_id,
        target_type="authoring_conversation",
        target_id=conversation.id,
        thread_key=f"authoring-{conversation.id}",
        business_revision=conversation.revision,
        teacher_answers=tuple(teacher_messages),
        evidence_file_ids=tuple(file_ids),
        evidence_scope=f"/evidence/authoring/{conversation.id}",
        ai_profile_version=profile.version,
        graph_schema_version=GRAPH_SCHEMA_VERSION,
        deadline=None,
    )


def _authoring_question_context(
    conversation: repository.AuthoringConversationRecord,
    draft: repository.QuestionDraftRecord,
) -> AgentRunContext:
    """Build an isolated context for exactly one confirmed question draft."""

    profile = get_ai_profile()
    all_drafts = [
        item
        for item in repository.list_drafts(conversation.id)
        if item.status != QuestionDraftStatus.discarded.value
    ]
    teacher_messages = [
        item.content[:4_000]
        for item in repository.list_messages(conversation.id)
        if item.role == AuthoringMessageRole.teacher.value
        and (
            item.question_draft_id == draft.id
            or (len(all_drafts) == 1 and item.question_draft_id is None)
        )
    ][-12:]
    file_ids = tuple(draft.evidence_file_ids)
    return AgentRunContext(
        user_id=conversation.created_by,
        workspace_id=conversation.workspace_id,
        target_type="authoring_question",
        target_id=draft.id,
        thread_key=f"authoring-question-{conversation.id}-{draft.id}",
        business_revision=conversation.revision,
        co_creation_question_count=draft.question_question_count,
        teacher_answers=tuple(teacher_messages),
        evidence_file_ids=file_ids,
        evidence_scope=f"/evidence/authoring/{conversation.id}/question/{draft.id}",
        ai_profile_version=profile.version,
        graph_schema_version=GRAPH_SCHEMA_VERSION,
        deadline=None,
    )


def process_authoring(job: OperationJob) -> dict[str, Any]:
    """Worker handler for candidate discovery and answer-gap projection.

    The Fake adapter is deterministic for CI.  A configured production adapter
    may propose boundaries, but only this service writes drafts and it never
    treats an AI candidate as a confirmed answer.
    """

    from app.lib.operations.worker import SupersededOperation

    conversation = repository.get_conversation(job.target_id)
    if conversation is None:
        raise AppError(404, "RESOURCE_NOT_FOUND", "建题会话不存在。")
    if conversation.revision != job.business_revision:
        raise SupersededOperation("建题会话已经产生新修订。")
    files_list = _files_for_conversation(conversation)
    if conversation.upload_batch_id and (
        not files_list or set(conversation.source_file_ids) - {item.id for item in files_list}
    ):
        raise RuntimeError("authoring evidence scope is unavailable")
    files = {item.id: item for item in files_list}
    file_ids = [
        item.id
        for item in files_list
        if item.parse_state == "parsed" and not item.ignored
    ]
    teacher_messages = [item for item in repository.list_messages(conversation.id) if item.role == "teacher"]
    latest_teacher_message = teacher_messages[-1] if teacher_messages else None
    latest_targeted_response = next(
        (item for item in reversed(teacher_messages) if item.question_draft_id is not None),
        None,
    )
    repository.append_event(
        conversation.id,
        "phase_started",
        {"phase": "识别任务", "label": "识别任务"},
    )
    existing = repository.list_drafts(conversation.id)
    active_existing = [item for item in existing if item.status != QuestionDraftStatus.discarded.value]
    question_stage = bool(
        active_existing
        and not any(item.status == QuestionDraftStatus.candidate.value for item in active_existing)
    )
    candidates: list[_Candidate] = []
    if active_existing:
        # A normal teacher correction is still an AI turn. Re-read the
        # bounded, scoped context so the real model can react to the new
        # business input, but keep the existing candidate identities stable;
        # only explicit boundary commands may create/discard/merge drafts.
        if (
            file_ids
            and latest_teacher_message is not None
            and latest_teacher_message.message_type == AuthoringMessageType.chat.value
            and not question_stage
        ):
            repository.append_event(
                conversation.id,
                "phase_started",
                {"phase": "理解补充信息", "label": "理解补充信息"},
            )
            refreshed = get_adapters().evidence_analyzer.analyze(
                _authoring_context(conversation, file_ids),
                documents_for_files(file_ids),
            )
            if getattr(refreshed, "result", None) is None:
                raise RuntimeError("authoring context review did not return a result")
            repository.append_event(
                conversation.id,
                "phase_completed",
                {"phase": "理解补充信息", "label": "理解补充信息"},
            )
        candidates = [_Candidate(item.title, item.summary, list(item.evidence_file_ids)) for item in active_existing]
    elif file_ids:
        repository.append_event(
            conversation.id,
            "phase_started",
            {"phase": "读取资料", "label": "读取资料"},
        )
        analysis = get_adapters().evidence_analyzer.analyze(
            _authoring_context(conversation, file_ids),
            documents_for_files(file_ids),
        )
        result = getattr(analysis, "result", None)
        groups = getattr(result, "groups", None)
        known = set(file_ids)
        if groups is None:
            raise RuntimeError("task analyzer did not return candidate groups")
        used: set[str] = set()
        for index, group in enumerate(groups):
            group_ids = [str(item) for item in group.evidence_file_ids]
            if not group_ids or set(group_ids) - known or used.intersection(group_ids):
                raise RuntimeError("task analyzer returned an invalid candidate boundary")
            used.update(group_ids)
            candidates.append(
                _Candidate(
                    _public_text(str(group.title), f"候选题 {index + 1}"),
                    _public_text(str(group.summary), "AI 已根据当前资料提出一个候选任务边界，请确认或调整。"),
                    group_ids,
                )
            )
        for file_id in sorted(known - used):
            candidates.append(_Candidate(f"候选题 {len(candidates) + 1}", "这份资料尚未归入候选题，请确认它的用途。", [file_id]))
    elif not conversation.upload_batch_id:
        # A manual conversation may be created with only its first chat
        # message.  That message is the user's task input just as much as the
        # dedicated task_instruction field; ignoring it collapses a multi-task
        # chat into one generic candidate.
        manual_source = conversation.task_instruction or (
            latest_teacher_message.content if latest_teacher_message is not None else None
        )
        candidates = _manual_candidates(manual_source, conversation.title)
    if not candidates and not conversation.upload_batch_id:
        candidates = [_Candidate(conversation.title, "暂时没有识别到明确的交付任务，请老师补充任务说明。", [])]
    repository.append_event(
        conversation.id,
        "phase_completed",
        {"phase": "识别任务", "label": "识别任务"},
    )
    repository.append_event(
        conversation.id,
        "action_summary",
        {"label": "资料数量", "count": len(file_ids)},
    )
    repository.append_event(
        conversation.id,
        "action_summary",
        {"label": "候选题数量", "count": len(candidates)},
    )

    latest_answer = next(
        (item for item in reversed(teacher_messages) if item.message_type == AuthoringMessageType.standard_answer.value),
        None,
    )
    drafts_payload: list[dict[str, Any]] = []
    answer_assigned = False
    question_pending: dict[str, Any] | None = None
    question_blocked = False
    for index, candidate in enumerate(candidates):
        previous = active_existing[index] if index < len(active_existing) else None
        source_ids = [item for item in candidate.evidence_file_ids if item in files]
        title = _public_text(candidate.title, f"候选题 {index + 1}")
        summary = _public_text(candidate.summary, "AI 已根据当前资料提出一个候选任务边界，请确认或调整。")
        task_instruction = conversation.task_instruction or candidate.summary or title
        answer = previous.reference_answer_text if previous else None
        answer_source = previous.reference_answer_source if previous else None
        if latest_answer is not None and not answer and not answer_assigned:
            target_id = latest_answer.question_draft_id
            if (target_id is None and len(candidates) == 1) or (
                target_id is not None and previous is not None and target_id == previous.id
            ):
                answer = latest_answer.content
                answer_source = "teacher_message"
                answer_assigned = True
        input_json = previous.input if previous else QuestionInput(
            task_instruction=task_instruction[:10_000],
            materials=_materials(source_ids, files),
            must_include=[],
            prohibited=[],
            background=None,
        ).model_dump(mode="json")
        status = previous.status if previous else QuestionDraftStatus.candidate.value
        question_checkpoint_id = previous.question_checkpoint_id if previous else None
        question_question_count = previous.question_question_count if previous else 0
        question_input_revision = previous.question_input_revision if previous else None
        question_prompt_sequence = previous.question_prompt_sequence if previous else None
        source_refs = previous.source_refs if previous else []
        if (
            question_stage
            and previous is not None
            and status != QuestionDraftStatus.candidate.value
            and not question_blocked
            and (
                question_checkpoint_id is not None
                or question_input_revision != conversation.revision
            )
            and (question_agent := get_adapters().question_cocreator) is not None
        ):
            draft_payload = {
                "id": previous.id,
                "title": title,
                "summary": summary,
                "input": input_json,
                "reference_answer_text": answer,
                "reference_answer_source": answer_source,
                "evidence_file_ids": source_ids,
            }
            question_context = _authoring_question_context(conversation, previous)
            agent_result = None
            if (
                question_checkpoint_id
                and latest_targeted_response is not None
                and latest_targeted_response.question_draft_id == previous.id
                and (
                    question_prompt_sequence is None
                    or latest_targeted_response.sequence > question_prompt_sequence
                )
            ):
                agent_result = question_agent.resume(
                    question_context,
                    question_checkpoint_id,
                    latest_targeted_response.content,
                    draft_payload,
                )
            elif question_checkpoint_id is None:
                agent_result = question_agent.start(question_context, draft_payload)
            if agent_result is not None:
                result = agent_result.result
                if result.input is not None:
                    original_materials = list(input_json.get("materials") or [])
                    input_json = result.input.model_dump(mode="json")
                    if not result.input.materials and original_materials:
                        # A model omission must not silently erase the
                        # teacher's evidence boundary from the draft.
                        input_json["materials"] = original_materials
                    source_ids = [
                        str(item.get("file_id"))
                        for item in input_json.get("materials") or []
                        if item.get("role") != "ignored"
                    ]
                if result.phase == "question":
                    if not agent_result.produced_checkpoint_id:
                        raise RuntimeError("authoring question interrupt did not produce a checkpoint")
                    question_checkpoint_id = agent_result.produced_checkpoint_id
                    question_question_count += 1
                    question_input_revision = None
                    question_prompt_sequence = latest_teacher_message.sequence if latest_teacher_message else 0
                    question = result.question
                    if question is None:
                        raise RuntimeError("authoring question result is missing its question")
                    question_pending = {
                        "id": question.id,
                        "text": _public_text(question.text, "请补充当前题目仍缺少的老师确认信息。"),
                        "reason": _public_text(question.reason, "需要老师确认后才能继续整理这道题。"),
                        "gap_type": question.gap_type,
                        "question_draft_id": previous.id,
                    }
                    source_refs = [item.model_dump(mode="json") for item in result.evidence_refs]
                    source_refs.extend(item.model_dump(mode="json") for item in question.evidence_refs)
                    question_blocked = True
                else:
                    if not answer:
                        # A completion without a teacher answer is not a safe
                        # standard-answer projection. Fall back to the durable
                        # business question instead of trusting model intent.
                        question_checkpoint_id = None
                        question_question_count = 0
                        question_input_revision = None
                        question_prompt_sequence = None
                        question_pending = {
                            "id": f"standard-answer-{previous.id}",
                            "text": f"请提供“{title}”的老师终版或明确认可的标准答案。",
                            "reason": "没有老师明确认可的终版，不能把 AI 候选当作标准答案。",
                            "gap_type": "standard_answer",
                            "question_draft_id": previous.id,
                        }
                        question_blocked = True
                    else:
                        question_checkpoint_id = None
                        question_question_count = 0
                        question_input_revision = conversation.revision + 1
                        question_prompt_sequence = None
                    source_refs = [item.model_dump(mode="json") for item in result.evidence_refs]
        drafts_payload.append(
            {
                "id": previous.id if previous else None,
                "title": title,
                "summary": summary,
                "status": status,
                "input": input_json,
                "reference_answer_text": answer,
                "reference_answer_source": answer_source,
                "evidence_file_ids": source_ids,
                "source_refs": source_refs,
                "question_checkpoint_id": question_checkpoint_id,
                "question_question_count": question_question_count,
                "question_input_revision": question_input_revision,
                "question_prompt_sequence": question_prompt_sequence,
            }
        )
    active_payload = [item for item in drafts_payload if item["status"] != QuestionDraftStatus.discarded.value]
    has_candidates = any(item["status"] == QuestionDraftStatus.candidate.value for item in active_payload)
    missing_answers = [item for item in active_payload if not item.get("reference_answer_text")]
    if has_candidates:
        status = AuthoringConversationStatus.review_ready.value
        pending = None
        message = f"我已整理出 {len(active_payload)} 道候选题。请先确认题目边界，再逐题审阅题目输入和标准答案。"
    elif question_pending:
        pending = question_pending
        status = AuthoringConversationStatus.waiting_for_teacher.value
        message = "我需要你补充一项信息，补充后会继续整理当前题目。"
    elif missing_answers:
        selected = missing_answers[0]
        pending = {
            "id": f"standard-answer-{selected['id'] or 'next'}",
            "text": f"请提供“{selected['title']}”的老师终版或明确认可的标准答案。",
            "reason": "没有老师明确认可的终版，不能把 AI 候选当作标准答案。",
            "gap_type": "standard_answer",
            "question_draft_id": selected["id"],
        }
        status = AuthoringConversationStatus.waiting_for_teacher.value
        message = "题目边界已保存。请补充老师终版或明确认可的标准答案；补充前不会进入下一阶段。"
    elif active_payload:
        pending = None
        status = AuthoringConversationStatus.review_ready.value
        message = "题目输入和老师标准答案候选已准备好，请逐题审阅并确认。"
    else:
        pending = None
        status = AuthoringConversationStatus.review_ready.value
        message = "当前没有可用资料形成候选题。请检查资料是否可读且未被忽略，或回到开始页重新上传资料。"
    events = [
        ("phase_completed", {"phase": "整理题目与标准答案", "label": "整理题目与标准答案"}),
        ("public_message_ready", {"text": message}),
        (
            "snapshot_changed",
            {
                "revision": conversation.revision + 1,
                "status": status,
                "draft_count": len(active_payload),
            },
        ),
    ]
    if pending:
        events.append(
            (
                "waiting_for_teacher",
                {"text": pending["text"], "reason": pending["reason"], "gap_type": pending["gap_type"]},
            )
        )
    else:
        events.append(("completed", {"draft_count": len(active_payload), "confirmed_count": 0}))
    projection_payload = {
        "drafts": drafts_payload,
        "status": status,
        "pending_question": pending,
        "assistant_message": message,
        "events": [[kind, payload] for kind, payload in events],
    }
    try:
        updated = repository.commit_worker_projection(
            conversation.id,
            expected_revision=job.business_revision,
            operation_job_id=job.id,
            operation_attempt=job.attempts,
            worker_id=job.worker_id or "",
            drafts=drafts_payload,
            status=status,
            pending_question=pending,
            assistant_message=message,
            events=events,
        )
    except repository.StaleProjection as exc:
        raise SupersededOperation(str(exc)) from exc
    except Exception as exc:
        try:
            operation_repository.save_result(
                job.id,
                job.worker_id or "",
                {"__authoring_projection": projection_payload},
            )
        except Exception:
            # If the handoff record cannot be saved, the Worker will still
            # mark the operation failed; never pretend the result is safely
            # reprojectable.
            raise
        from app.lib.operations.worker import ProjectionPendingOperation

        raise ProjectionPendingOperation(
            result_hash=repository.payload_hash(projection_payload),
        ) from exc
    return {"conversation_id": updated.id, "status": updated.status, "revision": updated.revision}


def reproject_authoring(job: OperationJob) -> dict[str, Any]:
    """Commit a saved authoring result without invoking a model."""

    from app.lib.operations.worker import SupersededOperation

    conversation = repository.get_conversation(job.target_id)
    if conversation is None:
        raise AppError(404, "RESOURCE_NOT_FOUND", "建题会话不存在。")
    if conversation.revision != job.business_revision:
        raise SupersededOperation("建题会话已经产生新修订。")
    saved: dict[str, Any] | None = None
    for previous in operation_repository.list_for_target("authoring_conversation", job.target_id):
        candidate = (previous.result or {}).get("__authoring_projection")
        if isinstance(candidate, dict):
            saved = candidate
            break
    if saved is None:
        raise RuntimeError("没有可重投影的已保存建题结果")
    events = []
    for item in saved.get("events") or []:
        if not isinstance(item, list) or len(item) != 2 or not isinstance(item[0], str) or not isinstance(item[1], dict):
            raise RuntimeError("已保存的建题结果事件格式无效")
        payload = dict(item[1])
        if item[0] == "snapshot_changed":
            payload["revision"] = job.business_revision + 1
        events.append((item[0], payload))
    try:
        updated = repository.commit_worker_projection(
            conversation.id,
            expected_revision=job.business_revision,
            operation_job_id=job.id,
            operation_attempt=job.attempts,
            worker_id=job.worker_id or "",
            drafts=list(saved.get("drafts") or []),
            status=str(saved.get("status") or "review_ready"),
            pending_question=saved.get("pending_question") if isinstance(saved.get("pending_question"), dict) else None,
            assistant_message=str(saved.get("assistant_message") or ""),
            events=events,
        )
    except repository.StaleProjection as exc:
        raise SupersededOperation(str(exc)) from exc
    except Exception as exc:
        try:
            operation_repository.save_result(
                job.id,
                job.worker_id or "",
                {"__authoring_projection": saved},
            )
        except Exception:
            raise
        from app.lib.operations.worker import ProjectionPendingOperation

        raise ProjectionPendingOperation(
            result_hash=repository.payload_hash(saved),
        ) from exc
    return {"conversation_id": updated.id, "status": updated.status, "revision": updated.revision}
