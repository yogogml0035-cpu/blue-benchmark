from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from io import BytesIO
import uuid
from typing import Any
from zipfile import BadZipFile, ZipFile

from app.features.auth.repository import UserRecord
from app.features.case_builder import cocreation_service as case_service
from app.features.case_builder.cocreation_schemas import CoverageReview, EvaluationTaskSnapshot
from app.features.evaluation_sets import repository
from app.features.evaluation_sets.schemas import (
    BatchImpactReviewRequest,
    CoverageConfirmationRequest,
    CoverageReviewRequest,
    CoverageSnapshotView,
    DraftCreateRequest,
    DraftDiscardRequest,
    DraftMemberView,
    FreezeAcceptedResponse,
    FreezeRequest,
    ImpactReviewDecisionRequest,
    ImpactReviewStatus,
    MemberMutationRequest,
    MemberStatus,
    ManifestResponse,
    VersionListResponse,
    VersionSummary,
    WorkingSetDraftResponse,
    WorkingSetDraftView,
)
from app.features.workspaces import service as workspace_service
from app.lib.ai_runtime import AgentRunContext, get_adapters, get_ai_profile
from app.lib.ai_runtime.adapters import AgentRunResult
from app.lib.errors import AppError
from app.lib.operations import repository as operation_repository
from app.lib.operations.repository import OperationJob, OperationJobStatus
from app.lib.storage import LocalStorage, StorageError
from app.lib.version_packages import PACKAGE_SCHEMA_VERSION, VersionPackageError, build_package, read_manifest


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _authorized_draft(workspace_id: str, draft_id: str, user: UserRecord) -> repository.WorkingSetDraftRecord:
    workspace_service.assert_owner(workspace_id, user)
    draft = repository.get_draft(draft_id)
    if draft is None:
        raise AppError(404, "RESOURCE_NOT_FOUND", "下一版本草稿不存在。")
    if draft.workspace_id != workspace_id:
        raise AppError(403, "FORBIDDEN", "你无权访问这个下一版本草稿。")
    return draft


def _active_operation(draft_id: str) -> OperationJob | None:
    jobs = operation_repository.list_for_target("working_set_draft", draft_id)
    for job in jobs:
        if job.kind not in {"coverage_review", "freeze_package"}:
            continue
        if job.status in {
            OperationJobStatus.queued,
            OperationJobStatus.running,
            OperationJobStatus.failed,
            OperationJobStatus.projection_pending,
        }:
            return job
    return None


def _version_summary(version: repository.EvaluationSetVersionRecord) -> VersionSummary:
    return VersionSummary(
        id=version.id,
        workspace_id=version.workspace_id,
        version_number=version.version_number,
        status="frozen",
        overall_sha256=version.overall_sha256,
        frozen_at=version.frozen_at,
    )


def _coverage_view(snapshot: repository.CoverageSnapshotRecord | None) -> CoverageSnapshotView | None:
    if snapshot is None:
        return None
    value = snapshot.snapshot
    return CoverageSnapshotView(
        id=snapshot.id,
        draft_revision=snapshot.draft_revision,
        capabilities=list(value.get("capabilities", [])),
        dimensions=list(value.get("dimensions", [])),
        failure_modes=list(value.get("failure_modes", [])),
        duplicate_groups=list(value.get("duplicate_groups", [])),
        blank_areas=list(value.get("blank_areas", [])),
        warnings=list(value.get("warnings", [])),
        risk_confirmed=snapshot.risk_confirmed,
        risk_confirmation_note=snapshot.risk_confirmation_note,
        confirmed_at=snapshot.confirmed_at,
    )


def _draft_view(draft: repository.WorkingSetDraftRecord) -> WorkingSetDraftView:
    members = repository.list_members(draft.id)
    member_views = [
        DraftMemberView(
            id=item.id,
            task_package_id=item.task_package_id,
            task_package_revision=item.task_package_revision,
            status=MemberStatus(item.status),
            review_status=ImpactReviewStatus(item.review_status),
            deterministic_conflicts=list(item.deterministic_conflicts),
            ai_suggestions=list(item.ai_suggestions),
            teacher_note=item.teacher_note,
            sort_order=item.sort_order,
        )
        for item in members
    ]
    included = [item for item in members if item.status == MemberStatus.included.value]
    blocking: list[str] = []
    if not included:
        blocking.append("至少选择一道已定稿题。")
    if any(item.review_status == ImpactReviewStatus.review_required.value for item in included):
        blocking.append("有入选题等待老师复核场景标准变化。")
    for item in included:
        try:
            snapshot = case_service.get_evaluation_task_snapshot(draft.workspace_id, item.task_package_id)
            if snapshot.revision != item.task_package_revision:
                blocking.append(f"{item.task_package_id}: 题已有新修订，请明确更新下一版引用。")
        except AppError as exc:
            blocking.append(exc.message)
    coverage = repository.get_latest_coverage(draft.id)
    latest_contract = case_service.get_latest_confirmed_contract(draft.workspace_id)
    if latest_contract is not None and latest_contract.id != draft.contract_revision_id:
        blocking.append("场景标准已有更新，请丢弃并从最新版本重新建立草稿。")
    if coverage is None or coverage.draft_revision != draft.revision:
        blocking.append("当前草稿还没有最新覆盖检查。")
    elif coverage.snapshot.get("warnings") and not coverage.risk_confirmed:
        blocking.append("覆盖检查存在风险，等待老师明确确认。")
    active = _active_operation(draft.id)
    if active and active.status in {OperationJobStatus.queued, OperationJobStatus.running}:
        next_action = "wait_for_processing"
    elif active and active.status in {OperationJobStatus.failed, OperationJobStatus.projection_pending}:
        next_action = "retry_processing"
    elif draft.status != "active":
        next_action = "none"
    elif not included:
        next_action = "add_or_remove_tasks"
    elif latest_contract is not None and latest_contract.id != draft.contract_revision_id:
        next_action = "review_contract_impact"
    elif any(item.review_status == ImpactReviewStatus.review_required.value for item in included):
        next_action = "review_contract_impact"
    elif coverage is None or coverage.draft_revision != draft.revision:
        next_action = "run_coverage_review"
    elif coverage.snapshot.get("warnings") and not coverage.risk_confirmed:
        next_action = "confirm_coverage_risk"
    else:
        next_action = "freeze"
    contract = case_service.get_contract_revision_for_evaluation(draft.workspace_id, draft.contract_revision_id)
    return WorkingSetDraftView(
        id=draft.id,
        workspace_id=draft.workspace_id,
        revision=draft.revision,
        status=draft.status,
        base_version_id=draft.base_version_id,
        contract_revision=contract.revision,
        members=member_views,
        coverage=_coverage_view(coverage),
        blocking_issues=blocking,
        next_action=next_action,
        active_operation=(
            {
                "id": active.id,
                "kind": active.kind,
                "status": active.status.value,
            }
            if active
            else None
        ),
        created_at=draft.created_at,
        updated_at=draft.updated_at,
    )


def _response(draft: repository.WorkingSetDraftRecord) -> WorkingSetDraftResponse:
    return WorkingSetDraftResponse(draft=_draft_view(draft))


def _base_members_from_manifest(version: repository.EvaluationSetVersionRecord) -> list[tuple[str, int, str]]:
    try:
        manifest, _ = _verified_manifest(version)
    except VersionPackageError:
        raise AppError(500, "VERSION_PACKAGE_UNREADABLE", "最新历史版本包无法读取。")
    members: list[tuple[str, int, str]] = []
    for item in manifest.get("tasks", []):
        if not isinstance(item, dict) or not item.get("task_id") or not item.get("contract_revision_id"):
            raise AppError(500, "VERSION_MANIFEST_INVALID", "最新历史版本包的任务清单无效。")
        members.append((str(item["task_id"]), int(item.get("revision", 0)), str(item["contract_revision_id"])))
    return members


def create_draft(workspace_id: str, payload: DraftCreateRequest, user: UserRecord) -> WorkingSetDraftResponse:
    workspace_service.assert_owner(workspace_id, user)
    existing = repository.get_active_draft(workspace_id)
    if existing is not None:
        return _response(existing)
    contract = case_service.get_latest_confirmed_contract(workspace_id)
    if contract is None:
        raise AppError(409, "CONTRACT_NOT_CONFIRMED", "请先确认场景标准。")
    versions = repository.list_versions(workspace_id)
    latest = versions[0] if versions else None
    base_members = _base_members_from_manifest(latest) if latest else []
    try:
        draft = repository.create_draft(
            workspace_id=workspace_id,
            contract_revision_id=contract.id,
            base_version_id=latest.id if latest else None,
            base_members=base_members,
            command_id=payload.command_id,
        )
    except Exception as exc:
        raise AppError(500, "DRAFT_CREATE_FAILED", "下一版本草稿未能创建。") from exc
    return _response(draft)


def get_draft(workspace_id: str, draft_id: str, user: UserRecord) -> WorkingSetDraftResponse:
    return _response(_authorized_draft(workspace_id, draft_id, user))


def discard_draft(
    workspace_id: str,
    draft_id: str,
    payload: DraftDiscardRequest,
    user: UserRecord,
) -> WorkingSetDraftResponse:
    draft = _authorized_draft(workspace_id, draft_id, user)
    active = _active_operation(draft.id)
    if active and active.kind == "freeze_package" and active.status in {OperationJobStatus.queued, OperationJobStatus.running}:
        raise AppError(409, "FREEZE_IN_PROGRESS", "冻结操作进行中，不能丢弃当前草稿。")
    try:
        discarded = repository.discard_draft(
            draft.id,
            expected_revision=payload.draft_revision,
            command_id=payload.command_id,
        )
    except repository.StaleDraft as exc:
        raise AppError(409, "STALE_DRAFT", "下一版本草稿已经更新，请重新读取。") from exc
    except repository.RepositoryConflict as exc:
        raise AppError(409, "DRAFT_NOT_EDITABLE", "当前下一版本草稿不能丢弃。") from exc
    return _response(discarded)


def mutate_member(
    workspace_id: str,
    draft_id: str,
    payload: MemberMutationRequest,
    user: UserRecord,
) -> WorkingSetDraftResponse:
    draft = _authorized_draft(workspace_id, draft_id, user)
    active = _active_operation(draft.id)
    if active and active.kind == "freeze_package" and active.status in {OperationJobStatus.queued, OperationJobStatus.running}:
        raise AppError(409, "FREEZE_IN_PROGRESS", "冻结操作进行中，不能修改当前草稿。")
    task = case_service.get_evaluation_task_snapshot(workspace_id, payload.task_package_id)
    if task.revision != payload.task_package_revision:
        raise AppError(409, "STALE_TASK_PACKAGE", "题已经更新，请重新读取后再操作。")
    conflicts = [] if task.contract_revision_id == draft.contract_revision_id else ["题引用了不同的场景标准修订。"]
    suggestions = ["请逐题核对新场景标准与本题判定依据。"] if conflicts else []
    try:
        changed = repository.mutate_member(
            draft.id,
            payload=payload,
            contract_revision_id=draft.contract_revision_id,
            task_contract_revision_id=task.contract_revision_id,
            deterministic_conflicts=conflicts,
            ai_suggestions=suggestions,
        )
    except repository.StaleDraft as exc:
        raise AppError(409, "STALE_DRAFT", "下一版本草稿已经更新，请重新读取。") from exc
    except repository.RepositoryConflict as exc:
        raise AppError(409, "DRAFT_NOT_EDITABLE", "当前下一版本草稿不能执行这项操作。") from exc
    return _response(changed)


def decide_impact(
    workspace_id: str,
    draft_id: str,
    task_package_id: str,
    payload: ImpactReviewDecisionRequest,
    user: UserRecord,
) -> WorkingSetDraftResponse:
    draft = _authorized_draft(workspace_id, draft_id, user)
    member = repository.get_member(draft.id, task_package_id)
    if member is None:
        raise AppError(404, "RESOURCE_NOT_FOUND", "题不在当前下一版本草稿中。")
    task = case_service.get_evaluation_task_snapshot(workspace_id, task_package_id)
    try:
        changed = repository.decide_impact(
            draft.id,
            task_package_id,
            payload=payload,
            confirmed_by=user.id,
            current_task_revision=task.revision,
        )
    except repository.StaleDraft as exc:
        raise AppError(409, "STALE_DRAFT", "下一版本草稿已经更新，请重新读取。") from exc
    except repository.RepositoryConflict as exc:
        raise AppError(409, "CONTRACT_REVIEW_REQUIRED", "当前合同影响还不能按该方式确认。") from exc
    return _response(changed)


def confirm_impact_batch(
    workspace_id: str,
    draft_id: str,
    payload: BatchImpactReviewRequest,
    user: UserRecord,
) -> WorkingSetDraftResponse:
    draft = _authorized_draft(workspace_id, draft_id, user)
    try:
        changed = repository.confirm_no_conflict_batch(draft.id, payload=payload, confirmed_by=user.id)
    except repository.StaleDraft as exc:
        raise AppError(409, "STALE_DRAFT", "下一版本草稿已经更新，请重新读取。") from exc
    except repository.RepositoryConflict as exc:
        raise AppError(409, "CONTRACT_REVIEW_REQUIRED", "存在需要逐题复核的合同冲突。") from exc
    return _response(changed)


def request_coverage_review(
    workspace_id: str,
    draft_id: str,
    payload: CoverageReviewRequest,
    user: UserRecord,
) -> WorkingSetDraftResponse:
    draft = _authorized_draft(workspace_id, draft_id, user)
    if draft.revision != payload.draft_revision:
        raise AppError(409, "STALE_DRAFT", "下一版本草稿已经更新，请重新读取。")
    if draft.status != "active":
        raise AppError(409, "DRAFT_NOT_EDITABLE", "已冻结或丢弃的草稿不能重新检查覆盖。")
    if any(
        item.review_status == ImpactReviewStatus.review_required.value
        for item in repository.list_members(draft.id, included_only=True)
    ):
        raise AppError(409, "CONTRACT_REVIEW_REQUIRED", "存在需要逐题复核的合同冲突。")
    _freeze_inputs(draft, allow_risk_confirmation=True, require_coverage=False)
    operation_repository.create_or_get(
        kind="coverage_review",
        target_type="working_set_draft",
        target_id=draft.id,
        command_id=payload.command_id,
        business_revision=draft.revision,
    )
    return _response(repository.get_draft(draft.id) or draft)


def confirm_coverage(
    workspace_id: str,
    draft_id: str,
    payload: CoverageConfirmationRequest,
    user: UserRecord,
) -> WorkingSetDraftResponse:
    draft = _authorized_draft(workspace_id, draft_id, user)
    try:
        changed = repository.confirm_coverage(draft.id, payload=payload, confirmed_by=user.id)
    except repository.StaleDraft as exc:
        raise AppError(409, "STALE_DRAFT", "下一版本草稿已经更新，请重新读取。") from exc
    except repository.RepositoryConflict as exc:
        raise AppError(409, "COVERAGE_NOT_READY", "当前没有可确认的覆盖检查结果。") from exc
    return _response(changed)


def _freeze_inputs(
    draft: repository.WorkingSetDraftRecord,
    *,
    allow_risk_confirmation: bool = False,
    require_coverage: bool = True,
) -> tuple[list[EvaluationTaskSnapshot], repository.ContractRevisionRecord, repository.CoverageSnapshotRecord | None]:
    if draft.status != "active":
        raise AppError(409, "DRAFT_NOT_EDITABLE", "已冻结或丢弃的草稿不能冻结。")
    contract = case_service.get_contract_revision_for_evaluation(draft.workspace_id, draft.contract_revision_id)
    if contract.status != "confirmed":
        raise AppError(409, "CONTRACT_NOT_CONFIRMED", "场景标准尚未确认。")
    latest_contract = case_service.get_latest_confirmed_contract(draft.workspace_id)
    if latest_contract is not None and latest_contract.id != draft.contract_revision_id:
        raise AppError(409, "CONTRACT_REVIEW_REQUIRED", "场景标准已有更新，请重新建立下一版本草稿。")
    members = repository.list_members(draft.id, included_only=True)
    if not members:
        raise AppError(409, "FREEZE_BLOCKED", "至少选择一道已定稿题后才能冻结。", {"issues": ["没有入选题。"]})
    review_issues = [
        item.task_package_id
        for item in members
        if item.review_status not in {
            ImpactReviewStatus.not_required.value,
            ImpactReviewStatus.reviewed.value,
            ImpactReviewStatus.no_conflict_confirmed.value,
        }
    ]
    if review_issues:
        raise AppError(409, "FREEZE_BLOCKED", "还有题没有完成合同影响复核。", {"task_package_ids": review_issues})
    tasks: list[EvaluationTaskSnapshot] = []
    issues: list[str] = []
    for member in members:
        try:
            task = case_service.get_evaluation_task_snapshot(draft.workspace_id, member.task_package_id)
            if task.revision != member.task_package_revision:
                issues.append(f"{member.task_package_id}: 题引用的修订已过期。")
            else:
                tasks.append(task)
        except AppError as exc:
            issues.append(f"{member.task_package_id}: {exc.message}")
    if issues:
        raise AppError(409, "FREEZE_BLOCKED", "入选题还不具备完整的冻结材料。", {"issues": issues})
    coverage = repository.get_latest_coverage(draft.id)
    if require_coverage and (coverage is None or coverage.draft_revision != draft.revision):
        raise AppError(409, "FREEZE_BLOCKED", "请先生成当前草稿的覆盖检查。", {"issues": ["coverage is stale or missing"]})
    warnings = list(coverage.snapshot.get("warnings", [])) if coverage else []
    if require_coverage and warnings and coverage.risk_confirmed and not (coverage.risk_confirmation_note or "").strip():
        raise AppError(409, "COVERAGE_RISK_CONFIRMATION_REQUIRED", "覆盖风险确认缺少老师说明。", {"warnings": warnings})
    if require_coverage and warnings and not coverage.risk_confirmed and not allow_risk_confirmation:
        raise AppError(409, "COVERAGE_RISK_CONFIRMATION_REQUIRED", "覆盖检查存在风险，需要老师明确确认。", {"warnings": warnings})
    return tasks, contract, coverage


def freeze(
    workspace_id: str,
    draft_id: str,
    payload: FreezeRequest,
    user: UserRecord,
) -> FreezeAcceptedResponse:
    draft = _authorized_draft(workspace_id, draft_id, user)
    existing_jobs = operation_repository.list_for_target("working_set_draft", draft.id)
    for job in existing_jobs:
        if job.kind == "freeze_package" and job.command_id == payload.command_id:
            if job.status == OperationJobStatus.failed:
                job = operation_repository.retry_failed(job.id)
            return FreezeAcceptedResponse(draft=_draft_view(draft), operation_id=job.id)
    existing_version = repository.get_version_by_freeze_command(workspace_id, payload.command_id)
    if existing_version is not None and existing_version.draft_id != draft.id:
        raise AppError(409, "COMMAND_ID_REUSED", "相同冻结命令已经用于另一份草稿。")
    if draft.revision != payload.draft_revision:
        raise AppError(409, "STALE_DRAFT", "下一版本草稿已经更新，请重新读取。")
    _freeze_inputs(draft, allow_risk_confirmation=payload.coverage_risk_confirmed)
    coverage = repository.get_latest_coverage(draft.id)
    if coverage is None:
        raise AppError(409, "FREEZE_BLOCKED", "请先生成当前草稿的覆盖检查。")
    if coverage.snapshot.get("warnings") and not coverage.risk_confirmed:
        confirmation = CoverageConfirmationRequest(
            command_id=f"freeze-coverage-{hashlib.sha256(payload.command_id.encode()).hexdigest()[:32]}",
            draft_revision=draft.revision,
            confirmed=payload.coverage_risk_confirmed,
            note=payload.risk_confirmation_note,
        )
        try:
            repository.confirm_coverage(draft.id, payload=confirmation, confirmed_by=user.id)
        except repository.RepositoryConflict as exc:
            raise AppError(409, "COVERAGE_RISK_CONFIRMATION_REQUIRED", "覆盖风险还没有得到明确确认。") from exc
    intent = {
        "freeze_command_id": payload.command_id,
        "draft_revision": draft.revision,
        "frozen_by": user.id,
        "frozen_at": _now().isoformat(),
        "coverage_risk_confirmed": bool(payload.coverage_risk_confirmed or coverage.risk_confirmed),
        "risk_confirmation_note": payload.risk_confirmation_note or coverage.risk_confirmation_note,
    }
    if draft.freeze_intent and draft.freeze_intent != intent:
        old_command = draft.freeze_intent.get("freeze_command_id")
        old_job = next((job for job in existing_jobs if job.kind == "freeze_package" and job.command_id == old_command), None)
        if old_job is not None and old_job.status not in {OperationJobStatus.failed, OperationJobStatus.superseded}:
            raise AppError(409, "FREEZE_IN_PROGRESS", "当前草稿已有一个冻结操作。")
        repository.clear_freeze_intent(draft.id, old_command)
    try:
        prepared = repository.set_freeze_intent(draft.id, expected_revision=draft.revision, intent=intent)
    except repository.StaleDraft as exc:
        raise AppError(409, "STALE_DRAFT", "下一版本草稿已经更新，请重新读取。") from exc
    except repository.RepositoryConflict as exc:
        raise AppError(409, "FREEZE_IN_PROGRESS", "当前草稿已有一个冻结操作。") from exc
    try:
        job = operation_repository.create_or_get(
            kind="freeze_package",
            target_type="working_set_draft",
            target_id=draft.id,
            command_id=payload.command_id,
            business_revision=draft.revision,
        )
    except Exception:
        repository.clear_freeze_intent(draft.id, payload.command_id)
        raise
    return FreezeAcceptedResponse(draft=_draft_view(repository.get_draft(draft.id) or prepared), operation_id=job.id)


def list_versions(workspace_id: str, user: UserRecord) -> VersionListResponse:
    workspace_service.assert_owner(workspace_id, user)
    return VersionListResponse(workspace_id=workspace_id, versions=[_version_summary(item) for item in repository.list_versions(workspace_id)])


def _verified_manifest(version: repository.EvaluationSetVersionRecord) -> tuple[dict[str, Any], LocalStorage]:
    storage = LocalStorage()
    try:
        manifest_bytes = storage.read_bytes(version.manifest_key)
        manifest = read_manifest(storage, version.manifest_key)
        if hashlib.sha256(manifest_bytes).hexdigest() != version.manifest_sha256:
            raise VersionPackageError("manifest hash does not match the version record")
        if manifest.get("overall_sha256") != version.overall_sha256:
            raise VersionPackageError("overall hash does not match the version record")
        version_meta = manifest.get("version") or {}
        if not isinstance(version_meta, dict):
            raise VersionPackageError("manifest version metadata is invalid")
        if (
            version_meta.get("id") != version.id
            or version_meta.get("workspace_id") != version.workspace_id
            or version_meta.get("number") != version.version_number
            or manifest.get("schema_version") != version.schema_version
        ):
            raise VersionPackageError("manifest identity does not match the version record")
        if not isinstance(manifest.get("tasks"), list) or not manifest["tasks"]:
            raise VersionPackageError("manifest task list is invalid")
        partition_keys = {
            "runtime": (version.runtime_key, version.runtime_sha256),
            "judge": (version.judge_key, version.judge_sha256),
            "provenance": (version.provenance_key, version.provenance_sha256),
        }
        partitions = manifest.get("partitions")
        if not isinstance(partitions, dict):
            raise VersionPackageError("manifest partition metadata is invalid")
        for name, (key, expected_hash) in partition_keys.items():
            if not storage.is_ready(key):
                raise VersionPackageError(f"{name} partition is not ready")
            content = storage.read_bytes(key)
            if hashlib.sha256(content).hexdigest() != expected_hash:
                raise VersionPackageError(f"{name} partition hash does not match the version record")
            entry = partitions.get(name) or {}
            if not isinstance(entry, dict):
                raise VersionPackageError(f"{name} partition metadata is invalid")
            if entry.get("sha256") != expected_hash or int(entry.get("bytes", -1)) != len(content):
                raise VersionPackageError(f"{name} partition is inconsistent with the manifest")
        if not storage.is_ready(version.package_key):
            raise VersionPackageError("package is not ready")
        with ZipFile(BytesIO(storage.read_bytes(version.package_key))) as archive:
            names = set(archive.namelist())
            if names != {"manifest.json", "runtime.json", "judge.json", "provenance.json"}:
                raise VersionPackageError("package contains an unexpected file")
            expected_files = {
                "manifest.json": manifest_bytes,
                "runtime.json": storage.read_bytes(version.runtime_key),
                "judge.json": storage.read_bytes(version.judge_key),
                "provenance.json": storage.read_bytes(version.provenance_key),
            }
            if any(archive.read(name) != content for name, content in expected_files.items()):
                raise VersionPackageError("package contents do not match the published partitions")
    except (StorageError, BadZipFile, KeyError, TypeError, ValueError) as exc:
        raise VersionPackageError("version package integrity check failed") from exc
    return manifest, storage


def get_manifest(workspace_id: str, version_id: str, user: UserRecord) -> ManifestResponse:
    workspace_service.assert_owner(workspace_id, user)
    version = repository.get_version(version_id)
    if version is None:
        raise AppError(404, "RESOURCE_NOT_FOUND", "历史版本不存在。")
    if version.workspace_id != workspace_id:
        raise AppError(403, "FORBIDDEN", "你无权访问这个历史版本。")
    try:
        manifest, _ = _verified_manifest(version)
    except VersionPackageError as exc:
        code = "VERSION_HASH_MISMATCH" if "hash" in str(exc).casefold() or "inconsistent" in str(exc).casefold() else "VERSION_PACKAGE_UNREADABLE"
        raise AppError(500, code, "历史版本包校验失败。" if code == "VERSION_HASH_MISMATCH" else "历史版本包无法读取。") from exc
    return ManifestResponse(version=_version_summary(version), manifest=manifest)


def download_package(workspace_id: str, version_id: str, user: UserRecord) -> tuple[VersionSummary, bytes]:
    workspace_service.assert_owner(workspace_id, user)
    version = repository.get_version(version_id)
    if version is None:
        raise AppError(404, "RESOURCE_NOT_FOUND", "历史版本不存在。")
    if version.workspace_id != workspace_id:
        raise AppError(403, "FORBIDDEN", "你无权下载这个历史版本。")
    try:
        _, storage = _verified_manifest(version)
        content = storage.read_bytes(version.package_key)
    except (StorageError, VersionPackageError) as exc:
        code = "VERSION_HASH_MISMATCH" if "hash" in str(exc).casefold() or "inconsistent" in str(exc).casefold() else "VERSION_PACKAGE_UNREADABLE"
        raise AppError(500, code, "历史版本包校验失败。" if code == "VERSION_HASH_MISMATCH" else "历史版本包无法下载。") from exc
    return _version_summary(version), content


def handle_coverage_review(job: OperationJob) -> dict[str, Any]:
    draft = repository.get_draft(job.target_id)
    if draft is None:
        raise AppError(404, "RESOURCE_NOT_FOUND", "下一版本草稿不存在。")
    if draft.revision != job.business_revision:
        from app.lib.operations.worker import SupersededOperation

        raise SupersededOperation("下一版本草稿已经更新。")
    tasks, contract, _ = _freeze_inputs(draft, allow_risk_confirmation=True, require_coverage=False)
    capabilities = sorted({item for task in tasks for item in [*task.contract.capabilities, *task.judgment_package.capabilities]})
    dimensions = sorted({item for task in tasks for item in [*task.contract.quality_dimensions, *task.judgment_package.dimensions]})
    failure_modes = sorted({item for task in tasks for item in task.judgment_package.rejected_reasons})
    snapshot_input = {
        "capabilities": capabilities,
        "dimensions": dimensions,
        "failure_modes": failure_modes,
        "task_ids": [task.task_package_id for task in tasks],
        "contract_revision_id": contract.id,
    }
    context = AgentRunContext(
        user_id=workspace_service.owner_id_for_workspace(draft.workspace_id),
        workspace_id=draft.workspace_id,
        target_type="working_set_draft",
        target_id=draft.id,
        thread_key=f"coverage-{job.id}",
        business_revision=draft.revision,
        evidence_file_ids=tuple(file.file_id for task in tasks for file in task.files),
        evidence_scope=f"/evidence/draft/{draft.id}",
        ai_profile_version=get_ai_profile().version,
        graph_schema_version="m0-coverage-v1",
    )
    result = get_adapters().coverage_reviewer.review(context, snapshot_input)
    if not isinstance(result, AgentRunResult) or not isinstance(result.result, CoverageReview):
        raise RuntimeError("coverage reviewer returned an invalid result")
    coverage = result.result.model_dump(mode="json")
    snapshot = repository.save_coverage(draft.id, draft_revision=draft.revision, snapshot=coverage)
    return {"draft_id": draft.id, "coverage_snapshot_id": snapshot.id, "draft_revision": draft.revision}


def _publish_objects(storage: LocalStorage, version_id: str, objects: dict[str, bytes]) -> list[str]:
    final_keys = [f"versions/{version_id}/{name}" for name in objects]
    existing_mismatch = False
    for name, key in zip(objects, final_keys, strict=True):
        if storage.exists(key) and storage.read_bytes(key) != objects[name]:
            existing_mismatch = True
            break
    if existing_mismatch:
        for key in final_keys:
            storage.delete(key)
    published: list[str] = []
    staged: list[str] = []
    try:
        for name, content in objects.items():
            final_key = f"versions/{version_id}/{name}"
            if storage.exists(final_key):
                published.append(final_key)
                continue
            staged_object = storage.stage_bytes(f"freeze-{version_id}", name, content)
            staged.append(staged_object.key)
            storage.publish(staged_object.key, final_key)
            published.append(final_key)
        if not all(storage.is_ready(key) for key in final_keys):
            raise VersionPackageError("package object is not ready")
    except Exception:
        for key in published:
            storage.delete(key)
        for key in staged:
            storage.delete(key)
        raise
    return final_keys


def handle_freeze(job: OperationJob) -> dict[str, Any]:
    draft = repository.get_draft(job.target_id)
    if draft is None:
        raise AppError(404, "RESOURCE_NOT_FOUND", "下一版本草稿不存在。")
    intent = draft.freeze_intent or {}
    command_id = str(intent.get("freeze_command_id") or job.command_id)
    existing = repository.get_version_by_freeze_command(draft.workspace_id, command_id)
    if existing is not None:
        if existing.draft_id != draft.id:
            raise RuntimeError("freeze command belongs to another draft")
        return {"version_id": existing.id, "version_number": existing.version_number, "overall_sha256": existing.overall_sha256}
    if draft.revision != job.business_revision or int(intent.get("draft_revision", -1)) != job.business_revision:
        from app.lib.operations.worker import SupersededOperation

        raise SupersededOperation("冻结意图对应的草稿已经更新。")
    tasks, contract, coverage = _freeze_inputs(draft, allow_risk_confirmation=bool(intent.get("coverage_risk_confirmed")))
    version_number = repository.latest_version_number(draft.workspace_id) + 1
    version_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"skill-eval:{draft.workspace_id}:{command_id}"))
    frozen_at = datetime.fromisoformat(str(intent["frozen_at"]))
    coverage_json = {
        **coverage.snapshot,
        "draft_revision": coverage.draft_revision,
        "risk_confirmed": coverage.risk_confirmed or bool(intent.get("coverage_risk_confirmed")),
        "risk_confirmation_note": coverage.risk_confirmation_note or intent.get("risk_confirmation_note"),
    }
    artifacts = build_package(
        version_id=version_id,
        workspace_id=draft.workspace_id,
        version_number=version_number,
        contract_revision=contract.revision,
        contract_revision_id=contract.id,
        contract=contract.contract,
        coverage=coverage_json,
        tasks=tasks,
        frozen_by=str(intent.get("frozen_by")),
        frozen_at=frozen_at,
        risk_confirmation={
            "confirmed": coverage_json["risk_confirmed"],
            "note": coverage_json["risk_confirmation_note"],
        },
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
        version = repository.create_version_if_current(
            draft.id,
            version_id=version_id,
            expected_revision=job.business_revision,
            version_number=version_number,
            contract_revision_id=contract.id,
            freeze_command_id=command_id,
            schema_version=PACKAGE_SCHEMA_VERSION,
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
            risk_confirmation={"confirmed": coverage_json["risk_confirmed"], "note": coverage_json["risk_confirmation_note"]},
            frozen_by=str(intent.get("frozen_by")),
            frozen_at=frozen_at,
        )
    except repository.StaleDraft as exc:
        for key in keys:
            storage.delete(key)
        from app.lib.operations.worker import SupersededOperation

        raise SupersededOperation(str(exc)) from exc
    except Exception:
        if repository.get_version_by_freeze_command(draft.workspace_id, command_id) is None:
            for key in keys:
                storage.delete(key)
        raise
    return {"version_id": version.id, "version_number": version.version_number, "overall_sha256": version.overall_sha256}
