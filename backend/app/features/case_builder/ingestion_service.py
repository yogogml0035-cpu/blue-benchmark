from __future__ import annotations

import json
import io
import mimetypes
import stat
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any
from uuid import uuid4

from fastapi import UploadFile
from sqlalchemy.exc import IntegrityError

from app.features.auth.repository import UserRecord
from app.features.case_builder import ingestion_repository
from app.features.case_builder.ingestion_schemas import (
    ActiveOperation,
    EvidenceFileSummary,
    EvidenceParseState,
    NextActionConfirmFiles,
    NextActionNone,
    NextActionRetry,
    NextActionWait,
    OperationReceipt,
    RetryOperationRequest,
    StudioProjection,
    UploadBatch,
    UploadBatchResponse,
    UploadBatchState,
)
from app.features.workspaces import service as workspace_service
from app.lib.errors import AppError
from app.lib.operations import repository as operation_repository
from app.lib.operations.repository import OperationJob, OperationJobStatus
from app.lib.settings import settings
from app.lib.storage import LocalStorage


ALLOWED_EXTENSIONS = frozenset({"md", "txt", "json", "jsonl", "zip"})


@dataclass(frozen=True, slots=True)
class IncomingFile:
    name: str
    content: bytes
    source_member: str | None = None


@dataclass(slots=True)
class ParseBudget:
    file_count: int = 0
    source_bytes: int = 0
    expanded_bytes: int = 0


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _extension(name: str) -> str:
    return name.rsplit(".", 1)[-1].casefold() if "." in name else ""


def _validate_name(name: str) -> str:
    if not name or name in {".", ".."}:
        raise AppError(422, "INVALID_FILE_NAME", "文件名不能为空。")
    if "\x00" in name or name.startswith(("/", "\\")):
        raise AppError(422, "UNSAFE_ARCHIVE_ENTRY", "文件路径不安全。")
    if PurePosixPath(name.replace("\\", "/")).is_absolute() or PureWindowsPath(name).is_absolute():
        raise AppError(422, "UNSAFE_ARCHIVE_ENTRY", "文件路径不安全。")
    parts = name.replace("\\", "/").split("/")
    if any(not part or part in {".", ".."} for part in parts):
        raise AppError(422, "UNSAFE_ARCHIVE_ENTRY", "文件路径不安全。")
    return "/".join(parts)


def _media_type(name: str) -> str:
    extension = _extension(name)
    return {
        "md": "text/markdown",
        "txt": "text/plain",
        "json": "application/json",
        "jsonl": "application/x-ndjson",
        "zip": "application/zip",
    }.get(extension, mimetypes.guess_type(name)[0] or "application/octet-stream")


def _unsupported(name: str) -> AppError:
    return AppError(
        415,
        "UNSUPPORTED_FILE_TYPE",
        "只支持 Markdown、TXT、JSON、JSONL 或 ZIP 文件。",
        {"allowed_extensions": sorted(ALLOWED_EXTENSIONS), "file_name": name},
    )


def _read_with_limit(zipped, limit: int) -> bytes:
    content = zipped.read(limit + 1)
    if len(content) > limit:
        raise AppError(413, "FILE_TOO_LARGE", "压缩包内文件超过当前大小限制。", {"max_bytes": limit})
    return content


def _expand_archive(
    name: str,
    content: bytes,
    *,
    depth: int,
    budget: ParseBudget,
) -> list[IncomingFile]:
    if depth > settings.archive_max_depth:
        raise AppError(422, "ARCHIVE_NESTING_TOO_DEEP", "压缩包嵌套层级超过限制。")
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except (zipfile.BadZipFile, OSError) as exc:
        raise AppError(422, "INVALID_ARCHIVE", "ZIP 文件无法安全读取。") from exc

    results: list[IncomingFile] = []
    with archive:
        members = archive.infolist()
        if len(members) > settings.archive_max_members:
            raise AppError(
                413,
                "ARCHIVE_TOO_MANY_FILES",
                "压缩包内文件数量超过限制。",
                {"max_files": settings.archive_max_members},
            )
        archive_total = 0
        seen_names: set[str] = set()
        for info in members:
            mode = (info.external_attr >> 16) & 0o170000
            if mode not in {0, stat.S_IFREG}:
                raise AppError(422, "UNSAFE_ARCHIVE_ENTRY", "压缩包不能包含符号链接或特殊文件。")
            member_name = _validate_name(info.filename)
            if member_name in seen_names:
                raise AppError(422, "DUPLICATE_ARCHIVE_ENTRY", "压缩包包含重复文件名。")
            seen_names.add(member_name)
            if info.is_dir():
                continue
            if info.file_size < 0 or info.file_size > settings.upload_max_bytes:
                raise AppError(413, "FILE_TOO_LARGE", "压缩包内文件超过当前大小限制。")
            archive_total += info.file_size
            if archive_total > settings.archive_max_uncompressed_bytes:
                raise AppError(413, "ARCHIVE_TOO_LARGE", "压缩包展开后的总大小超过限制。")
            if (
                (info.file_size > 0 and info.compress_size == 0)
                or (info.compress_size and info.file_size / info.compress_size > settings.archive_max_ratio)
            ):
                raise AppError(413, "ARCHIVE_COMPRESSION_RATIO", "压缩包疑似包含异常高压缩比内容。")
            try:
                with archive.open(info, "r") as zipped:
                    member_content = _read_with_limit(zipped, settings.upload_max_bytes)
            except (RuntimeError, OSError, zipfile.BadZipFile) as exc:
                raise AppError(422, "INVALID_ARCHIVE", "ZIP 文件无法安全读取。") from exc
            if _extension(member_name) == "zip":
                results.extend(
                    _expand_archive(
                        member_name,
                        member_content,
                        depth=depth + 1,
                        budget=budget,
                    )
                )
            else:
                budget.file_count += 1
                budget.expanded_bytes += len(member_content)
                if budget.file_count > settings.upload_max_files:
                    raise AppError(413, "TOO_MANY_FILES", "一次上传的文件数量超过限制。", {"max_files": settings.upload_max_files})
                if budget.expanded_bytes > settings.archive_max_uncompressed_bytes:
                    raise AppError(413, "ARCHIVE_TOO_LARGE", "压缩包展开后的总大小超过限制。")
                results.append(IncomingFile(member_name, member_content, member_name))
    return results


def _parse_view(name: str, content: bytes) -> tuple[str, dict[str, Any] | None, dict[str, str] | None]:
    extension = _extension(name)
    if extension in {"md", "txt"}:
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            return EvidenceParseState.parse_failed.value, None, {"code": "TEXT_DECODE_FAILED", "message": "文件不是可读取的 UTF-8 文本。"}
        if not text.strip():
            return EvidenceParseState.parse_failed.value, None, {"code": "PARSED_CONTENT_EMPTY", "message": "文件内容为空。"}
        return EvidenceParseState.parsed.value, {"kind": "text", "encoding": "utf-8", "line_count": len(text.splitlines())}, None
    if extension == "json":
        try:
            value = json.loads(content.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return EvidenceParseState.parse_failed.value, None, {"code": "JSON_PARSE_FAILED", "message": "JSON 文件无法读取。"}
        return EvidenceParseState.parsed.value, {"kind": "json", "root_type": type(value).__name__, "line_count": len(content.decode("utf-8-sig").splitlines())}, None
    if extension == "jsonl":
        try:
            lines = content.decode("utf-8-sig").splitlines()
            events = [json.loads(line) for line in lines if line.strip()]
        except (UnicodeDecodeError, json.JSONDecodeError):
            return EvidenceParseState.parse_failed.value, None, {"code": "JSONL_PARSE_FAILED", "message": "JSONL 文件无法读取。"}
        return EvidenceParseState.parsed.value, {"kind": "jsonl", "line_count": len(lines), "event_count": len(events), "eof_verified": True}, None
    return EvidenceParseState.unsupported.value, None, {"code": "UNSUPPORTED_FILE_TYPE", "message": "文件类型暂不支持。"}


async def _read_uploads(uploads: list[UploadFile]) -> list[IncomingFile]:
    if not uploads:
        raise AppError(422, "FILE_REQUIRED", "至少上传一份资料。")
    if len(uploads) > settings.upload_max_files:
        raise AppError(413, "TOO_MANY_FILES", "一次上传的文件数量超过限制。", {"max_files": settings.upload_max_files})
    budget = ParseBudget()
    results: list[IncomingFile] = []
    for upload in uploads:
        name = _validate_name(upload.filename or "unnamed")
        if _extension(name) not in ALLOWED_EXTENSIONS:
            raise _unsupported(name)
        content = await upload.read(settings.upload_max_bytes + 1)
        if len(content) > settings.upload_max_bytes:
            raise AppError(413, "FILE_TOO_LARGE", "文件超过当前大小限制。", {"max_bytes": settings.upload_max_bytes})
        budget.source_bytes += len(content)
        if budget.source_bytes > settings.upload_max_total_bytes:
            raise AppError(413, "UPLOAD_TOO_LARGE", "一次上传的总大小超过限制。", {"max_bytes": settings.upload_max_total_bytes})
        if _extension(name) == "zip":
            results.extend(_expand_archive(name, content, depth=0, budget=budget))
        else:
            budget.file_count += 1
            if budget.file_count > settings.upload_max_files:
                raise AppError(413, "TOO_MANY_FILES", "一次上传的文件数量超过限制。", {"max_files": settings.upload_max_files})
            budget.expanded_bytes += len(content)
            results.append(IncomingFile(name, content))
    return results


def _file_summary(item: ingestion_repository.EvidenceFileRecord) -> EvidenceFileSummary:
    return EvidenceFileSummary(
        id=item.id,
        original_name=item.original_name,
        media_type=item.media_type,
        size_bytes=item.size_bytes,
        sha256=item.sha256,
        parse_state=EvidenceParseState(item.parse_state),
        parse_error=(item.parse_error or {}).get("message") if item.parse_error else None,
        source_member=item.source_member,
        role=item.role,
        required=item.required,
        ignored=item.ignored,
        visibility=item.visibility,
    )


def _active_operation(job: OperationJob | None) -> ActiveOperation | None:
    if job is None or job.status not in {
        OperationJobStatus.queued,
        OperationJobStatus.running,
        OperationJobStatus.failed,
        OperationJobStatus.projection_pending,
    }:
        return None
    return ActiveOperation(id=job.id, kind=job.kind, status=job.status.value)


def _latest_receipt(job: OperationJob | None) -> OperationReceipt | None:
    if job is None or job.status not in {OperationJobStatus.succeeded, OperationJobStatus.superseded}:
        return None
    message = "资料已完成整理。" if job.status == OperationJobStatus.succeeded else "这次整理结果已过期。"
    return OperationReceipt(id=job.id, status=job.status.value, message=message, completed_at=job.finished_at)


def _projection(
    batch: ingestion_repository.UploadBatchRecord,
    files: list[ingestion_repository.EvidenceFileRecord],
    jobs: list[OperationJob],
) -> StudioProjection:
    current_job = jobs[0] if jobs else None
    blocking = []
    if not files:
        blocking.append("还没有可供整理的资料。")
    if any(item.parse_state in {EvidenceParseState.parse_failed.value, EvidenceParseState.unsupported.value} for item in files):
        blocking.append("有资料无法读取，需要老师处理或忽略。")
    if current_job and current_job.status in {OperationJobStatus.queued, OperationJobStatus.running}:
        next_action = NextActionWait()
    elif current_job and current_job.status == OperationJobStatus.failed:
        next_action = NextActionRetry()
    elif batch.status == UploadBatchState.ready_for_confirmation.value:
        next_action = (
            NextActionConfirmFiles()
            if any(item.visibility == "unconfirmed" for item in files)
            else NextActionNone(label="资料用途已确认，等待任务分组")
        )
    else:
        next_action = NextActionWait()
    return StudioProjection(
        workspace_id=batch.workspace_id,
        batch_id=batch.id,
        batch_status=UploadBatchState(batch.status),
        files=[_file_summary(item) for item in files],
        next_action=next_action,
        active_operation=_active_operation(current_job),
        latest_receipt=_latest_receipt(current_job),
        blocking_issues=blocking,
    )


def _batch_response(batch, files, jobs) -> UploadBatchResponse:
    summaries = [_file_summary(item) for item in files]
    return UploadBatchResponse(
        batch=UploadBatch(
            id=batch.id,
            workspace_id=batch.workspace_id,
            title=batch.title,
            task_description=batch.task_description,
            status=UploadBatchState(batch.status),
            revision=batch.revision,
            created_at=batch.created_at,
            updated_at=batch.updated_at,
            files=summaries,
        ),
        studio=_projection(batch, files, jobs),
    )


async def create_upload_batch(
    workspace_id: str,
    title: str,
    task_description: str | None,
    uploads: list[UploadFile],
    user: UserRecord,
    command_id: str | None = None,
) -> UploadBatchResponse:
    workspace_service.assert_owner(workspace_id, user)
    if not title.strip():
        raise AppError(422, "VALIDATION_ERROR", "任务标题不能为空。")
    normalized_command_id = command_id.strip() if command_id and command_id.strip() else None
    if normalized_command_id:
        existing = ingestion_repository.get_batch_by_command(workspace_id, normalized_command_id)
        if existing:
            files = ingestion_repository.list_files(existing.id)
            jobs = operation_repository.list_for_target("upload_batch", existing.id)
            return _batch_response(existing, files, jobs)
    incoming = await _read_uploads(uploads)
    batch_id = str(uuid4())
    storage = LocalStorage()
    files: list[ingestion_repository.EvidenceFileRecord] = []
    published_keys: list[str] = []
    staged_keys: list[str] = []
    try:
        for item in incoming:
            file_id = str(uuid4())
            state, canonical_view, parse_error = _parse_view(item.name, item.content)
            staged = storage.stage_bytes(batch_id, file_id, item.content)
            staged_keys.append(staged.key)
            final_key = f"evidence/{batch_id}/{file_id}"
            storage.publish(staged.key, final_key)
            published_keys.append(final_key)
            files.append(
                ingestion_repository.EvidenceFileRecord(
                    id=file_id,
                    upload_batch_id=batch_id,
                    workspace_id=workspace_id,
                    storage_key=final_key,
                    original_name=item.name,
                    media_type=_media_type(item.name),
                    size_bytes=len(item.content),
                    sha256=staged.sha256,
                    parse_state=state,
                    parse_error=parse_error,
                    canonical_view=canonical_view,
                    source_member=item.source_member,
                    created_at=_now(),
                )
            )
        timestamp = _now()
        batch = ingestion_repository.UploadBatchRecord(
            id=batch_id,
            workspace_id=workspace_id,
            title=title.strip(),
            task_description=task_description.strip() if task_description else None,
            command_id=normalized_command_id,
            status=UploadBatchState.analyzing.value,
            revision=0,
            created_at=timestamp,
            updated_at=timestamp,
        )
        try:
            ingestion_repository.add_batch(batch, files)
        except IntegrityError:
            existing = (
                ingestion_repository.get_batch_by_command(workspace_id, normalized_command_id)
                if normalized_command_id
                else None
            )
            if existing:
                for key in published_keys:
                    storage.delete(key)
                for key in staged_keys:
                    storage.delete(key)
                existing_files = ingestion_repository.list_files(existing.id)
                existing_jobs = operation_repository.list_for_target("upload_batch", existing.id)
                return _batch_response(existing, existing_files, existing_jobs)
            raise
        operation_repository.create_or_get(
            kind="batch_analysis",
            target_type="upload_batch",
            target_id=batch_id,
            command_id=normalized_command_id or str(uuid4()),
            business_revision=batch.revision,
        )
    except Exception:
        for key in published_keys:
            storage.delete(key)
        for key in staged_keys:
            storage.delete(key)
        ingestion_repository.delete_batch(batch_id)
        raise
    jobs = operation_repository.list_for_target("upload_batch", batch_id)
    return _batch_response(batch, files, jobs)


def get_upload_batch(workspace_id: str, batch_id: str, user: UserRecord) -> UploadBatchResponse:
    workspace_service.assert_owner(workspace_id, user)
    batch = ingestion_repository.get_batch(batch_id)
    if batch is None:
        raise AppError(404, "RESOURCE_NOT_FOUND", "上传批次不存在。")
    if batch.workspace_id != workspace_id:
        raise AppError(403, "FORBIDDEN", "你无权访问这个上传批次。")
    files = ingestion_repository.list_files(batch_id)
    jobs = operation_repository.list_for_target("upload_batch", batch_id)
    return _batch_response(batch, files, jobs)


def get_studio(
    workspace_id: str,
    user: UserRecord,
    batch_id: str | None = None,
) -> StudioProjection:
    workspace_service.assert_owner(workspace_id, user)
    batch = ingestion_repository.get_batch(batch_id) if batch_id else ingestion_repository.latest_batch(workspace_id)
    if batch is None:
        raise AppError(404, "RESOURCE_NOT_FOUND", "当前场景还没有资料批次。")
    if batch.workspace_id != workspace_id:
        raise AppError(403, "FORBIDDEN", "你无权访问这个资料批次。")
    files = ingestion_repository.list_files(batch.id)
    jobs = operation_repository.list_for_target("upload_batch", batch.id)
    return _projection(batch, files, jobs)


def retry_batch_analysis(
    workspace_id: str,
    batch_id: str,
    payload: RetryOperationRequest,
    user: UserRecord,
) -> UploadBatchResponse:
    workspace_service.assert_owner(workspace_id, user)
    batch = ingestion_repository.get_batch(batch_id)
    if batch is None:
        raise AppError(404, "RESOURCE_NOT_FOUND", "上传批次不存在。")
    if batch.workspace_id != workspace_id:
        raise AppError(403, "FORBIDDEN", "你无权访问这个上传批次。")
    existing = operation_repository.list_for_target("upload_batch", batch_id)
    if any(job.command_id == payload.command_id for job in existing):
        return _batch_response(batch, ingestion_repository.list_files(batch_id), existing)
    if payload.batch_revision != batch.revision:
        raise AppError(409, "STALE_BATCH", "批次已经更新，请重新读取后再重试。")
    if not existing or existing[0].status != OperationJobStatus.failed:
        raise AppError(409, "RETRY_NOT_AVAILABLE", "当前没有可重试的资料整理操作。")
    if not ingestion_repository.update_status(
        batch_id,
        UploadBatchState.analyzing.value,
        expected_revision=batch.revision,
    ):
        raise AppError(409, "STALE_BATCH", "批次已经更新，请重新读取后再重试。")
    try:
        operation_repository.create_or_get(
            kind="batch_analysis",
            target_type="upload_batch",
            target_id=batch_id,
            command_id=payload.command_id,
            business_revision=batch.revision,
        )
    except operation_repository.OperationCommandConflict as exc:
        raise AppError(409, "COMMAND_ID_REUSED", "相同命令已经用于另一种后台操作。") from exc
    refreshed = ingestion_repository.get_batch(batch_id)
    files = ingestion_repository.list_files(batch_id)
    jobs = operation_repository.list_for_target("upload_batch", batch_id)
    return _batch_response(refreshed, files, jobs)


def update_file_disposition(
    workspace_id: str,
    batch_id: str,
    file_id: str,
    payload,
    user: UserRecord,
) -> UploadBatchResponse:
    workspace_service.assert_owner(workspace_id, user)
    batch = ingestion_repository.get_batch(batch_id)
    if batch is None:
        raise AppError(404, "RESOURCE_NOT_FOUND", "上传批次不存在。")
    if batch.workspace_id != workspace_id:
        raise AppError(403, "FORBIDDEN", "你无权访问这个上传批次。")
    if batch.status != UploadBatchState.ready_for_confirmation.value:
        raise AppError(409, "BATCH_NOT_READY", "资料仍在整理，暂时不能确认用途。")
    file_record = ingestion_repository.get_file(file_id)
    if file_record is None:
        raise AppError(404, "RESOURCE_NOT_FOUND", "资料不存在。")
    if file_record.upload_batch_id != batch_id:
        raise AppError(403, "FORBIDDEN", "你无权访问这份资料。")
    from app.features.case_builder import cocreation_repository

    if any(
        item.status == "confirmed" and file_id in item.evidence_file_ids
        for item in cocreation_repository.list_task_packages(batch_id)
    ):
        raise AppError(409, "FILE_DISPOSITION_LOCKED", "资料已经进入已确认任务，不能再修改用途；请重新上传新批次。")
    updated = ingestion_repository.update_disposition(
        batch_id=batch_id,
        file_id=file_id,
        role=payload.role,
        required=payload.required,
        ignored=payload.ignored,
        visibility=payload.visibility,
        rationale=payload.rationale,
        confirmed_by=user.id,
        expected_revision=payload.batch_revision,
    )
    if not updated:
        raise AppError(409, "STALE_BATCH", "批次已经更新，请重新读取后再确认。")
    current = ingestion_repository.get_batch(batch_id)
    files = ingestion_repository.list_files(batch_id)
    jobs = operation_repository.list_for_target("upload_batch", batch_id)
    return _batch_response(current, files, jobs)


def complete_batch_analysis(job: OperationJob) -> dict[str, Any]:
    """Compatibility entry point; the co-creation feature owns analysis now."""

    from app.features.case_builder.cocreation_service import complete_batch_analysis as analyze

    return analyze(job)
