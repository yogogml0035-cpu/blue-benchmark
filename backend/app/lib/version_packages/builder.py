from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
from io import BytesIO
import json
from typing import Any, Iterable
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from app.features.case_builder.cocreation_schemas import EvaluationTaskSnapshot
from app.lib.storage import LocalStorage, StorageError


PACKAGE_SCHEMA_VERSION = "m0-evaluation-package-v1"


class VersionPackageError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class PackageArtifacts:
    manifest: dict[str, Any]
    manifest_bytes: bytes
    runtime_bytes: bytes
    judge_bytes: bytes
    provenance_bytes: bytes
    package_bytes: bytes
    manifest_sha256: str
    runtime_sha256: str
    judge_sha256: str
    provenance_sha256: str
    overall_sha256: str


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _file_metadata(file: Any) -> dict[str, Any]:
    return {
        "file_id": file.file_id,
        "name": file.name,
        "media_type": file.media_type,
        "size_bytes": file.size_bytes,
        "sha256": file.sha256,
        "role": file.role,
        "required": file.required,
        "visibility": file.visibility,
    }


def _read_runtime_file(storage: LocalStorage, file: Any) -> dict[str, Any]:
    try:
        if not storage.is_ready(file.storage_key):
            raise VersionPackageError(f"runtime file is not ready: {file.file_id}")
        raw = storage.read_bytes(file.storage_key)
        if _sha256(raw) != file.sha256 or len(raw) != file.size_bytes:
            raise VersionPackageError(f"runtime file hash does not match metadata: {file.file_id}")
        content = raw.decode("utf-8-sig")
    except (StorageError, UnicodeDecodeError) as exc:
        raise VersionPackageError(f"required runtime file is not readable: {file.file_id}") from exc
    return {
        "file_id": file.file_id,
        "name": file.name,
        "media_type": file.media_type,
        "sha256": file.sha256,
        "content": content,
    }


def _runtime_partition(tasks: Iterable[EvaluationTaskSnapshot], storage: LocalStorage) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for task in sorted(tasks, key=lambda item: item.task_package_id):
        input_files = [
            _read_runtime_file(storage, file)
            for file in sorted(task.files, key=lambda item: item.file_id)
            if not file.ignored and file.visibility == "runtime" and file.role in {"runtime", "brief"}
        ]
        if not input_files:
            raise VersionPackageError(f"task {task.task_package_id} has no runtime input")
        summary = task.task_description or ""
        entries.append(
            {
                "task_id": task.task_package_id,
                "title": task.title,
                "brief": summary,
                "input_files": input_files,
            }
        )
    return {"schema_version": PACKAGE_SCHEMA_VERSION, "tasks": entries}


def _judge_partition(tasks: Iterable[EvaluationTaskSnapshot]) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for task in sorted(tasks, key=lambda item: item.task_package_id):
        judgment = task.judgment_package.model_dump(mode="json")
        entries.append(
            {
                "task_id": task.task_package_id,
                "task_revision": task.revision,
                "reference_results": judgment["reference_results"],
                "accepted_reasons": judgment["accepted_reasons"],
                "rejected_reasons": judgment["rejected_reasons"],
                "hard_gates": judgment["hard_gates"],
                "minimum_quality_line": judgment["minimum_quality_line"],
                "task_specific_rules": judgment["task_specific_rules"],
                "capabilities": judgment["capabilities"],
                "dimensions": judgment["dimensions"],
                "source_files": [_file_metadata(file) for file in sorted(task.files, key=lambda item: item.file_id)],
            }
        )
    return {"schema_version": PACKAGE_SCHEMA_VERSION, "tasks": entries}


def _provenance_partition(tasks: Iterable[EvaluationTaskSnapshot]) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for task in sorted(tasks, key=lambda item: item.task_package_id):
        entries.append(
            {
                "task_id": task.task_package_id,
                "task_revision": task.revision,
                "contract_revision_id": task.contract_revision_id,
                "files": [_file_metadata(file) for file in sorted(task.files, key=lambda item: item.file_id)],
                "attempts": [attempt.model_dump(mode="json") for attempt in task.attempts],
                "formation": task.provenance,
            }
        )
    return {"schema_version": PACKAGE_SCHEMA_VERSION, "tasks": entries}


def _deterministic_zip(files: dict[str, bytes]) -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for name in sorted(files):
            info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            archive.writestr(info, files[name])
    return output.getvalue()


def _assert_runtime_allowlist(runtime: dict[str, Any]) -> None:
    allowed_root = {"schema_version", "tasks"}
    allowed_task = {"task_id", "title", "brief", "input_files"}
    allowed_file = {"file_id", "name", "media_type", "sha256", "content"}
    if set(runtime) != allowed_root:
        raise VersionPackageError("runtime partition contains an unknown top-level field")
    for task in runtime["tasks"]:
        if set(task) != allowed_task:
            raise VersionPackageError("runtime partition contains a judge/provenance field")
        for file in task["input_files"]:
            if set(file) != allowed_file:
                raise VersionPackageError("runtime file contains a non-runtime field")


def build_package(
    *,
    version_id: str,
    workspace_id: str,
    version_number: int,
    contract_revision: int,
    contract_revision_id: str,
    contract: dict[str, Any],
    coverage: dict[str, Any],
    tasks: list[EvaluationTaskSnapshot],
    frozen_by: str,
    frozen_at: datetime,
    risk_confirmation: dict[str, Any],
    storage: LocalStorage | None = None,
) -> PackageArtifacts:
    if not tasks:
        raise VersionPackageError("at least one task is required")
    local_storage = storage or LocalStorage()
    runtime = _runtime_partition(tasks, local_storage)
    judge = _judge_partition(tasks)
    provenance = _provenance_partition(tasks)
    _assert_runtime_allowlist(runtime)
    runtime_bytes = canonical_json(runtime)
    judge_bytes = canonical_json(judge)
    provenance_bytes = canonical_json(provenance)
    runtime_hash = _sha256(runtime_bytes)
    judge_hash = _sha256(judge_bytes)
    provenance_hash = _sha256(provenance_bytes)
    base_manifest: dict[str, Any] = {
        "schema_version": PACKAGE_SCHEMA_VERSION,
        "version": {
            "id": version_id,
            "workspace_id": workspace_id,
            "number": version_number,
        },
        "contract": {"revision": contract_revision, "content": contract},
        "coverage": coverage,
        "tasks": [
            {
                "task_id": task.task_package_id,
                "revision": task.revision,
                "contract_revision_id": contract_revision_id,
            }
            for task in sorted(tasks, key=lambda item: item.task_package_id)
        ],
        "partitions": {
            "runtime": {"file": "runtime.json", "sha256": runtime_hash, "bytes": len(runtime_bytes)},
            "judge": {"file": "judge.json", "sha256": judge_hash, "bytes": len(judge_bytes)},
            "provenance": {"file": "provenance.json", "sha256": provenance_hash, "bytes": len(provenance_bytes)},
        },
        "frozen": {
            "by": frozen_by,
            "at": frozen_at.isoformat(),
            "risk_confirmation": risk_confirmation,
        },
    }
    overall_hash = _sha256(canonical_json(base_manifest))
    manifest = {**base_manifest, "overall_sha256": overall_hash}
    manifest_bytes = canonical_json(manifest)
    package_bytes = _deterministic_zip(
        {
            "judge.json": judge_bytes,
            "manifest.json": manifest_bytes,
            "provenance.json": provenance_bytes,
            "runtime.json": runtime_bytes,
        }
    )
    return PackageArtifacts(
        manifest=manifest,
        manifest_bytes=manifest_bytes,
        runtime_bytes=runtime_bytes,
        judge_bytes=judge_bytes,
        provenance_bytes=provenance_bytes,
        package_bytes=package_bytes,
        manifest_sha256=_sha256(manifest_bytes),
        runtime_sha256=runtime_hash,
        judge_sha256=judge_hash,
        provenance_sha256=provenance_hash,
        overall_sha256=overall_hash,
    )


def read_manifest(storage: LocalStorage, key: str) -> dict[str, Any]:
    try:
        if not storage.is_ready(key):
            raise VersionPackageError("version manifest is not ready")
        value = json.loads(storage.read_bytes(key))
    except (StorageError, json.JSONDecodeError) as exc:
        raise VersionPackageError("version manifest cannot be read") from exc
    if not isinstance(value, dict) or value.get("schema_version") != PACKAGE_SCHEMA_VERSION:
        raise VersionPackageError("version manifest schema is invalid")
    return value
