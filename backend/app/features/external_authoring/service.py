from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
from typing import Any

from app.features.auth.repository import UserRecord
from app.features.case_builder import authoring_service, ingestion_service
from app.features.external_authoring import repository
from app.features.external_authoring.schemas import (
    ExternalBadSample,
    ExternalConnectionCreateRequest,
    ExternalConnectionCreateResponse,
    ExternalConnectionExchangeResponse,
    ExternalConnectionStatusResponse,
    ExternalConnectionView,
    ExternalEvaluationCaseDraftRequest,
    ExternalEvaluationCaseDraftResponse,
)
from app.features.workspaces import service as workspace_service
from app.lib.errors import AppError
from app.lib.settings import settings


@dataclass(frozen=True, slots=True)
class ExternalAuthoringPrincipal:
    connection_id: str
    user_id: str
    workspace_id: str
    scopes: tuple[str, ...]


_FORBIDDEN_BAD_SAMPLE_TERMS = (
    "system_prompt",
    "system prompt",
    "private_reasoning",
    "private reasoning",
    "tool_args",
    "tool args",
    "tool_result",
    "tool result",
    "checkpoint",
    "thread_id",
    "storage_key",
    "api_key",
    "api key",
    "access token",
    "password",
    "系统提示",
    "私有推理",
    "工具调用",
    "存储键",
    "凭证",
    "绝对路径",
)
_VAGUE_FEEDBACK = {"不行", "这个不行", "不对", "不好", "不喜欢", "不符合", "不对劲"}


def _payload_hash(payload: ExternalEvaluationCaseDraftRequest) -> str:
    encoded = json.dumps(
        payload.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _workspace_name(workspace_id: str) -> str:
    return workspace_service.get_for_internal(workspace_id).name


def _connection_view(record: repository.ConnectionRecord) -> ExternalConnectionView:
    now = datetime.now(timezone.utc)
    if record.revoked_at is not None:
        status = "revoked"
    elif record.token_created_at is not None:
        status = "active"
    elif record.code_expires_at is not None and record.code_expires_at <= now:
        status = "expired"
    else:
        status = "pending_exchange"
    return ExternalConnectionView(
        id=record.id,
        client_name=record.client_name,
        status=status,
        scopes=record.scopes,
        workspace_name=_workspace_name(record.workspace_id),
        created_at=record.created_at,
        last_used_at=record.last_used_at,
        revoked_at=record.revoked_at,
    )


def create_connection(
    workspace_id: str,
    payload: ExternalConnectionCreateRequest,
    user: UserRecord,
) -> ExternalConnectionCreateResponse:
    workspace_service.assert_owner(workspace_id, user)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=settings.authoring_connection_code_ttl_seconds)
    try:
        record, code = repository.create_connection(
            workspace_id=workspace_id,
            user_id=user.id,
            client_name=payload.client_name,
            expires_at=expires_at,
        )
    except Exception as exc:
        raise AppError(409, "CONNECTION_REBIND_CONFLICT", "当前场景正在重新绑定，请稍后重试。") from exc
    return ExternalConnectionCreateResponse(
        connection=_connection_view(record),
        connection_code=code,
        expires_at=expires_at,
        exchange_url="/api/external/authoring-connections/exchange",
    )


def get_connection(workspace_id: str, user: UserRecord) -> ExternalConnectionStatusResponse:
    workspace_service.assert_owner(workspace_id, user)
    record = repository.get_for_workspace(workspace_id)
    return ExternalConnectionStatusResponse(connection=_connection_view(record) if record else None)


def revoke_connection(workspace_id: str, connection_id: str, user: UserRecord) -> ExternalConnectionStatusResponse:
    workspace_service.assert_owner(workspace_id, user)
    try:
        record = repository.revoke(workspace_id=workspace_id, connection_id=connection_id, reason="teacher_revoked")
    except KeyError as exc:
        raise AppError(404, "RESOURCE_NOT_FOUND", "连接不存在。") from exc
    return ExternalConnectionStatusResponse(connection=_connection_view(record))


def exchange_connection(code: str) -> ExternalConnectionExchangeResponse:
    try:
        record, token = repository.exchange(code)
    except repository.ConnectionInvalid as exc:
        message = str(exc)
        if "already" in message:
            raise AppError(409, "CONNECTION_CODE_REUSED", "连接码已经兑换过，不能再次使用。") from exc
        if "expired" in message:
            raise AppError(409, "CONNECTION_CODE_EXPIRED", "连接码已过期，请回到网站重新创建。") from exc
        raise AppError(401, "CONNECTION_CODE_INVALID", "连接码无效或已失效。") from exc
    return ExternalConnectionExchangeResponse(access_token=token, connection=_connection_view(record))


def require_principal(token: str) -> ExternalAuthoringPrincipal:
    try:
        record = repository.authenticate_token(token)
    except repository.ConnectionInvalid as exc:
        raise AppError(401, "EXTERNAL_TOKEN_INVALID", "外部连接凭证无效或已撤销。") from exc
    return ExternalAuthoringPrincipal(
        connection_id=record.id,
        user_id=record.user_id,
        workspace_id=record.workspace_id,
        scopes=tuple(record.scopes),
    )


def get_external_connection_status(principal: ExternalAuthoringPrincipal) -> ExternalConnectionStatusResponse:
    record = repository.get_for_workspace(principal.workspace_id, principal.connection_id)
    if record is None or record.revoked_at is not None:
        raise AppError(401, "EXTERNAL_TOKEN_INVALID", "外部连接凭证无效或已撤销。")
    return ExternalConnectionStatusResponse(connection=_connection_view(record))


def _validate_public_payload(payload: ExternalEvaluationCaseDraftRequest) -> str:
    encoded = json.dumps(
        payload.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(encoded) > settings.external_authoring_max_payload_bytes:
        raise AppError(413, "EXTERNAL_PAYLOAD_TOO_LARGE", "外部收题内容超过限制。", {"max_bytes": settings.external_authoring_max_payload_bytes})
    if len(payload.input_files) > settings.external_authoring_max_files:
        raise AppError(413, "TOO_MANY_INPUT_FILES", "外部收题的输入文件数量超过限制。")
    if len(payload.bad_samples) > settings.external_authoring_max_bad_samples:
        raise AppError(413, "TOO_MANY_BAD_SAMPLES", "坏样本数量超过限制。")
    for sample in payload.bad_samples:
        _validate_bad_sample(sample)
    return hashlib.sha256(encoded).hexdigest()


def _validate_bad_sample(sample: ExternalBadSample) -> None:
    values = [sample.source_ref, sample.content_text, sample.reason_summary, *sample.teacher_feedback_texts]
    for value in values:
        folded = value.casefold()
        if value.startswith(("/", "\\")) or "file://" in folded or any(term in folded for term in ("/users/", "/home/", "/private/", "c:\\")):
            raise AppError(422, "BAD_SAMPLE_PRIVATE_CONTENT", "坏样本只能包含老师可见的结果正文和反馈原话。")
        if any(term in folded for term in _FORBIDDEN_BAD_SAMPLE_TERMS):
            raise AppError(422, "BAD_SAMPLE_PRIVATE_CONTENT", "坏样本不能包含系统、工具或私有运行信息。")
    if all(item.strip().casefold() in _VAGUE_FEEDBACK for item in sample.teacher_feedback_texts):
        raise AppError(422, "BAD_SAMPLE_FEEDBACK_TOO_VAGUE", "坏样本的老师反馈过于笼统，请先补充具体否定原因。")
    if not sample.reason_summary.strip():
        raise AppError(422, "BAD_SAMPLE_REASON_REQUIRED", "坏样本必须有老师确认的原因摘要。")


def _response(principal: ExternalAuthoringPrincipal, conversation_id: str, draft_id: str) -> ExternalEvaluationCaseDraftResponse:
    return ExternalEvaluationCaseDraftResponse(
        draft_id=draft_id,
        conversation_id=conversation_id,
        status="draft_ready",
        workspace_name=_workspace_name(principal.workspace_id),
        draft_url=(
            f"{settings.frontend_url.rstrip('/')}/workspaces/"
            f"{principal.workspace_id}/authoring/{conversation_id}?draft={draft_id}"
        ),
    )


def create_external_draft(
    principal: ExternalAuthoringPrincipal,
    payload: ExternalEvaluationCaseDraftRequest,
) -> ExternalEvaluationCaseDraftResponse:
    if "draft:create" not in principal.scopes:
        raise AppError(403, "EXTERNAL_SCOPE_DENIED", "当前连接没有创建草稿权限。")
    digest = _validate_public_payload(payload)
    existing = repository.get_command(principal.connection_id, payload.command_id)
    if existing is not None:
        if existing.payload_hash != digest:
            raise AppError(409, "COMMAND_ID_REUSED", "相同命令已经用于另一份评测草稿。")
        if existing.status == "ready" and existing.conversation_id and existing.draft_id:
            return _response(principal, existing.conversation_id, existing.draft_id)
        if existing.status == "creating" and (
            datetime.now(timezone.utc) - existing.created_at
        ).total_seconds() >= settings.external_authoring_request_lease_seconds:
            # A process may die after reserving the command but before the
            # transaction that creates the ordinary draft. Reclaim only this
            # exact connection/command reservation; never guess by payload.
            repository.release_command(principal.connection_id, payload.command_id)
            existing = None
        else:
            raise AppError(409, "COMMAND_IN_PROGRESS", "相同命令正在创建草稿，请稍后重试。")

    try:
        repository.begin_request(
            principal.connection_id,
            max_concurrent=settings.external_authoring_max_concurrent_requests,
            min_interval_seconds=settings.external_authoring_min_request_interval_seconds,
            lease_seconds=settings.external_authoring_request_lease_seconds,
        )
    except repository.ConnectionBusy as exc:
        raise AppError(429, "EXTERNAL_CONCURRENCY_LIMIT", "当前连接正在处理其他上传，请稍后重试。") from exc
    except repository.ConnectionRateLimited as exc:
        raise AppError(429, "EXTERNAL_RATE_LIMITED", "上传请求过于频繁，请稍后重试。") from exc
    except repository.ConnectionInvalid as exc:
        raise AppError(401, "EXTERNAL_TOKEN_INVALID", "外部连接凭证无效或已撤销。") from exc

    reserved = False
    batch = None
    files = []
    try:
        command, reserved = repository.reserve_command(principal.connection_id, payload.command_id, digest)
        if not reserved:
            if command.payload_hash != digest:
                raise AppError(409, "COMMAND_ID_REUSED", "相同命令已经用于另一份评测草稿。")
            if command.status == "ready" and command.conversation_id and command.draft_id:
                return _response(principal, command.conversation_id, command.draft_id)
            raise AppError(409, "COMMAND_IN_PROGRESS", "相同命令正在创建草稿，请稍后重试。")

        batch, files = ingestion_service.create_external_text_batch(
            workspace_id=principal.workspace_id,
            title=payload.title,
            task_requirement=payload.task_requirement,
            inputs=[
                ingestion_service.ExternalTextInput(
                    name=item.display_name,
                    content=item.content_text,
                    media_type=item.media_type,
                    metadata={
                        key: value
                        for key, value in item.model_dump(mode="json").items()
                        if key != "content_text"
                    },
                )
                for item in payload.input_files
            ],
            confirmed_by=principal.user_id,
        )
        source_file_ids = [item.id for item in files]
        conversation, draft = authoring_service.create_external_draft(
            connection_id=principal.connection_id,
            external_command_id=payload.command_id,
            external_payload_hash=digest,
            workspace_id=principal.workspace_id,
            upload_batch_id=batch.id if batch else None,
            title=payload.title,
            task_requirement=payload.task_requirement,
            source_file_ids=source_file_ids,
            bad_samples=[item.model_dump(mode="json") for item in payload.bad_samples],
            reference_answer_text=payload.reference_answer_text,
            created_by=principal.user_id,
        )
        return _response(principal, conversation.id, draft.id)
    except Exception:
        if batch is not None:
            ingestion_service.discard_external_text_batch(batch, files)
        if reserved:
            repository.release_command(principal.connection_id, payload.command_id)
        raise
    finally:
        repository.finish_request(principal.connection_id)
