"""Automatic current evaluation-set lifecycle for authored questions."""

from __future__ import annotations

from datetime import datetime, timezone
import uuid
from typing import Any

from app.features.auth.repository import UserRecord
from app.features.case_builder import authoring_repository
from app.features.evaluation_sets import repository as evaluation_repository
from app.features.evaluation_sets import rubric_repository
from app.features.evaluation_sets import rubric_service
from app.features.evaluation_sets.schemas import VersionSummary
from app.lib.errors import AppError
from app.lib.storage import LocalStorage, StorageError
from app.lib.version_packages import QUESTION_REVISION_PACKAGE_SCHEMA_VERSION, VersionPackageError, build_question_revision_package


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _publish_objects(storage: LocalStorage, version_id: str, objects: dict[str, bytes]) -> list[str]:
    final_keys = [f"versions/{version_id}/{name}" for name in objects]
    published: list[str] = []
    staged: list[str] = []
    try:
        for name, content in objects.items():
            final_key = f"versions/{version_id}/{name}"
            if storage.exists(final_key):
                if storage.read_bytes(final_key) != content:
                    raise VersionPackageError("automatic version object conflicts with an existing object")
                published.append(final_key)
                continue
            staged_object = storage.stage_bytes(f"automatic-version-{version_id}", name, content)
            staged.append(staged_object.key)
            storage.publish(staged_object.key, final_key)
            published.append(final_key)
        if not all(storage.is_ready(key) for key in final_keys):
            raise VersionPackageError("automatic version object is not ready")
        return final_keys
    except Exception:
        for key in published:
            try:
                storage.delete(key)
            except (StorageError, OSError):
                pass
        for key in staged:
            try:
                storage.delete(key)
            except (StorageError, OSError):
                pass
        raise


def _version_summary(version: evaluation_repository.EvaluationSetVersionRecord) -> VersionSummary:
    return VersionSummary(
        id=version.id,
        workspace_id=version.workspace_id,
        version_number=version.version_number,
        status="frozen",
        overall_sha256=version.overall_sha256,
        frozen_at=version.frozen_at,
    )


def finalize_question_publish(
    workspace_id: str,
    revision_id: str,
    *,
    command_id: str,
    user: UserRecord,
) -> VersionSummary:
    """Build the next immutable current-set version, then activate the revision.

    The revision is staged until a ready package and DB version exist. A retry
    of the same command reuses the version and completes the activation, so a
    storage or process failure cannot make a half-published revision visible.
    """

    revision = rubric_repository.get_revision_any(revision_id)
    if revision is None:
        raise AppError(404, "RESOURCE_NOT_FOUND", "待发布的题目修订不存在。")
    if revision.workspace_id != workspace_id:
        raise AppError(403, "FORBIDDEN", "你无权发布这道题。")
    draft = authoring_repository.get_draft(revision.question_draft_id)
    if draft is None:
        raise AppError(404, "RESOURCE_NOT_FOUND", "题目草稿不存在。")
    if draft.lifecycle_status in {"disabled", "deleted"}:
        raise AppError(409, "QUESTION_NOT_ACTIVE", "停用或删除的题目不能发布新修订。")

    version_command = f"auto-publish:{command_id}"
    existing = evaluation_repository.get_version_by_freeze_command(workspace_id, version_command)
    if existing is not None:
        try:
            rubric_repository.mark_revision_published(revision_id)
            authoring_repository.set_active_revision(
                revision.question_draft_id,
                revision_id=revision_id,
                command_id=f"lifecycle:{command_id}",
                digest=rubric_repository.payload_hash({"revision_id": revision_id, "command_id": command_id}),
            )
        except Exception as exc:
            raise AppError(503, "PUBLISH_RECOVERY_FAILED", "发布版本已生成，但题目当前状态还未恢复，请重试。") from exc
        return _version_summary(existing)

    active_revisions = rubric_repository.list_current_active_revisions(workspace_id)
    tasks = [
        rubric_service.get_question_revision_for_version(
            workspace_id,
            item.id,
            allow_staged=False,
        )
        for item in active_revisions
        if item.id != revision_id
    ]
    tasks.append(
        rubric_service.get_question_revision_for_version(
            workspace_id,
            revision_id,
            allow_staged=True,
        )
    )
    version_number = evaluation_repository.latest_version_number(workspace_id) + 1
    version_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"skill-eval:auto:{workspace_id}:{command_id}"))
    frozen_at = _now()
    artifacts = build_question_revision_package(
        version_id=version_id,
        workspace_id=workspace_id,
        version_number=version_number,
        contract_revision=0,
        contract_revision_id=None,
        contract={},
        coverage={
            "automatic": True,
            "task_ids": [item.task_id for item in tasks],
        },
        tasks=tasks,
        frozen_by=user.id,
        frozen_at=frozen_at,
        risk_confirmation={"automatic": True},
    )
    objects = {
        "manifest.json": artifacts.manifest_bytes,
        "runtime.json": artifacts.runtime_bytes,
        "judge.json": artifacts.judge_bytes,
        "provenance.json": artifacts.provenance_bytes,
        "package.zip": artifacts.package_bytes,
    }
    storage = LocalStorage()
    keys = _publish_objects(storage, version_id, objects)
    key_map = dict(zip(objects, keys, strict=True))
    try:
        version = evaluation_repository.create_automatic_version_if_current(
            workspace_id,
            version_id=version_id,
            expected_latest_number=version_number - 1,
            version_number=version_number,
            command_id=version_command,
            schema_version=QUESTION_REVISION_PACKAGE_SCHEMA_VERSION,
            keys={
                "manifest": key_map["manifest.json"],
                "runtime": key_map["runtime.json"],
                "judge": key_map["judge.json"],
                "provenance": key_map["provenance.json"],
                "package": key_map["package.zip"],
            },
            hashes={
                "manifest": artifacts.manifest_sha256,
                "runtime": artifacts.runtime_sha256,
                "judge": artifacts.judge_sha256,
                "provenance": artifacts.provenance_sha256,
            },
            overall_sha256=artifacts.overall_sha256,
            frozen_by=user.id,
            frozen_at=frozen_at,
        )
    except Exception:
        for key in keys:
            try:
                storage.delete(key)
            except (StorageError, OSError):
                pass
        raise
    try:
        rubric_repository.mark_revision_published(revision_id)
        authoring_repository.set_active_revision(
            revision.question_draft_id,
            revision_id=revision_id,
            command_id=f"lifecycle:{command_id}",
            digest=rubric_repository.payload_hash({"revision_id": revision_id, "command_id": command_id}),
        )
    except Exception as exc:
        raise AppError(503, "PUBLISH_RECOVERY_FAILED", "版本已生成，但题目当前状态还未恢复，请重试。") from exc
    return _version_summary(version)


def finalize_current_set_change(
    workspace_id: str,
    *,
    command_id: str,
    user: UserRecord,
    transition_draft_id: str,
    transition_action: str,
) -> VersionSummary:
    """Create the next current-set version after disable/restore/delete."""

    version_command = f"auto-lifecycle:{command_id}"
    existing = evaluation_repository.get_version_by_freeze_command(workspace_id, version_command)
    if existing is not None:
        return _version_summary(existing)
    transition = authoring_repository.get_draft(transition_draft_id)
    if transition is None:
        raise AppError(404, "RESOURCE_NOT_FOUND", "题目草稿不存在。")
    active_revisions = rubric_repository.list_current_active_revisions(workspace_id)
    if transition_action in {"disable", "delete"}:
        active_revisions = [item for item in active_revisions if item.question_draft_id != transition_draft_id]
    elif transition_action == "restore":
        active_revisions = [item for item in active_revisions if item.question_draft_id != transition_draft_id]
        if transition.active_revision_id:
            restored = rubric_repository.get_revision(transition.active_revision_id)
            if restored is not None:
                active_revisions.append(restored)
    tasks = [
        rubric_service.get_question_revision_for_version(workspace_id, item.id)
        for item in active_revisions
    ]
    version_number = evaluation_repository.latest_version_number(workspace_id) + 1
    version_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"skill-eval:auto:{workspace_id}:{command_id}"))
    frozen_at = _now()
    artifacts = build_question_revision_package(
        version_id=version_id,
        workspace_id=workspace_id,
        version_number=version_number,
        contract_revision=0,
        contract_revision_id=None,
        contract={},
        coverage={"automatic": True, "task_ids": [item.task_id for item in tasks]},
        tasks=tasks,
        frozen_by=user.id,
        frozen_at=frozen_at,
        risk_confirmation={"automatic": True},
        allow_empty=True,
    )
    objects = {
        "manifest.json": artifacts.manifest_bytes,
        "runtime.json": artifacts.runtime_bytes,
        "judge.json": artifacts.judge_bytes,
        "provenance.json": artifacts.provenance_bytes,
        "package.zip": artifacts.package_bytes,
    }
    storage = LocalStorage()
    keys = _publish_objects(storage, version_id, objects)
    key_map = dict(zip(objects, keys, strict=True))
    try:
        version = evaluation_repository.create_automatic_version_if_current(
            workspace_id,
            version_id=version_id,
            expected_latest_number=version_number - 1,
            version_number=version_number,
            command_id=version_command,
            schema_version=QUESTION_REVISION_PACKAGE_SCHEMA_VERSION,
            keys={
                "manifest": key_map["manifest.json"],
                "runtime": key_map["runtime.json"],
                "judge": key_map["judge.json"],
                "provenance": key_map["provenance.json"],
                "package": key_map["package.zip"],
            },
            hashes={
                "manifest": artifacts.manifest_sha256,
                "runtime": artifacts.runtime_sha256,
                "judge": artifacts.judge_sha256,
                "provenance": artifacts.provenance_sha256,
            },
            overall_sha256=artifacts.overall_sha256,
            frozen_by=user.id,
            frozen_at=frozen_at,
        )
    except Exception:
        for key in keys:
            try:
                storage.delete(key)
            except (StorageError, OSError):
                pass
        raise
    return _version_summary(version)
