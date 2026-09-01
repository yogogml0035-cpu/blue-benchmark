"""Version-two package primitives for immutable authored question revisions.

The v1 builder is intentionally left untouched.  This module owns the new
question-revision shape so a future package change cannot silently rewrite the
bytes or leakage contract of historical v1 packages.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
import hashlib
import json
from typing import Any, Iterable
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from app.lib.storage import LocalStorage, StorageError
from app.lib.version_packages.builder import VersionPackageError


QUESTION_REVISION_PACKAGE_SCHEMA_VERSION = "m0-evaluation-package-v2"
_RUNTIME_ROLES = frozenset({"brief", "fact", "style", "current_draft", "background", "runtime"})


class QuestionRevisionPackageError(VersionPackageError):
    pass


@dataclass(frozen=True, slots=True)
class QuestionRevisionPackageFile:
    file_id: str
    name: str
    media_type: str
    size_bytes: int
    sha256: str
    storage_key: str
    role: str
    required: bool
    visibility: str


@dataclass(frozen=True, slots=True)
class QuestionRevisionPackageTask:
    task_id: str
    revision: int
    title: str
    brief: str
    input: dict[str, Any]
    files: tuple[QuestionRevisionPackageFile, ...]
    judge: dict[str, Any]
    provenance: dict[str, Any]
    question_revision_id: str | None = None
    content_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class QuestionRevisionPackageArtifacts:
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


def _file_metadata(file: QuestionRevisionPackageFile) -> dict[str, Any]:
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


def _read_runtime_file(storage: LocalStorage, file: QuestionRevisionPackageFile) -> dict[str, Any]:
    try:
        if file.visibility != "runtime" or file.role not in _RUNTIME_ROLES:
            raise QuestionRevisionPackageError(f"file is not runtime-visible: {file.file_id}")
        if not storage.is_ready(file.storage_key):
            raise QuestionRevisionPackageError(f"runtime file is not ready: {file.file_id}")
        raw = storage.read_bytes(file.storage_key)
        if len(raw) != file.size_bytes or _sha256(raw) != file.sha256:
            raise QuestionRevisionPackageError(f"runtime file hash does not match metadata: {file.file_id}")
        content = raw.decode("utf-8-sig")
    except (StorageError, UnicodeDecodeError) as exc:
        raise QuestionRevisionPackageError(f"required runtime file is not readable: {file.file_id}") from exc
    return {
        "file_id": file.file_id,
        "name": file.name,
        "media_type": file.media_type,
        "sha256": file.sha256,
        "content": content,
    }


def _runtime_partition(tasks: Iterable[QuestionRevisionPackageTask], storage: LocalStorage) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for task in sorted(tasks, key=lambda item: item.task_id):
        # Keep the filtering explicit: the package task is an internal
        # snapshot, while runtime visibility is rechecked at build time.
        input_files = [
            _read_runtime_file(storage, file)
            for file in sorted(task.files, key=lambda item: item.file_id)
            if file.visibility == "runtime" and file.role in _RUNTIME_ROLES
        ]
        if task.files and not input_files:
            raise QuestionRevisionPackageError(f"task {task.task_id} has no runtime-visible input")
        entries.append(
            {
                "task_id": task.task_id,
                "title": task.title,
                "brief": task.brief,
                "input": task.input,
                "input_files": input_files,
            }
        )
    return {"schema_version": QUESTION_REVISION_PACKAGE_SCHEMA_VERSION, "tasks": entries}


def _judge_partition(tasks: Iterable[QuestionRevisionPackageTask]) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for task in sorted(tasks, key=lambda item: item.task_id):
        entry = {
            "task_id": task.task_id,
            "task_revision": task.revision,
            **task.judge,
        }
        if task.question_revision_id is not None:
            entry["question_revision_id"] = task.question_revision_id
        if task.content_sha256 is not None:
            entry["content_sha256"] = task.content_sha256
        entries.append(entry)
    return {"schema_version": QUESTION_REVISION_PACKAGE_SCHEMA_VERSION, "tasks": entries}


def _provenance_partition(tasks: Iterable[QuestionRevisionPackageTask]) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for task in sorted(tasks, key=lambda item: item.task_id):
        entry = {
            "task_id": task.task_id,
            "task_revision": task.revision,
            "files": [_file_metadata(file) for file in sorted(task.files, key=lambda item: item.file_id)],
            "provenance": task.provenance,
        }
        if task.question_revision_id is not None:
            entry["question_revision_id"] = task.question_revision_id
        if task.content_sha256 is not None:
            entry["content_sha256"] = task.content_sha256
        entries.append(entry)
    return {"schema_version": QUESTION_REVISION_PACKAGE_SCHEMA_VERSION, "tasks": entries}


def _deterministic_zip(files: dict[str, bytes]) -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for name in sorted(files):
            info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            archive.writestr(info, files[name])
    return output.getvalue()


_RUNTIME_FORBIDDEN_KEYS = frozenset(
    {
        "reference_answer_text",
        "reference_results",
        "rubric",
        "criteria",
        "pass_threshold",
        "hard_gates",
        "minimum_quality_line",
        "accepted_reasons",
        "rejected_reasons",
        "attempts",
        "formation",
        "provenance",
        "published_by",
        "published_at",
        "source_refs",
        "score",
        "passed",
    }
)


def _assert_runtime_allowlist(runtime: dict[str, Any]) -> None:
    if set(runtime) != {"schema_version", "tasks"} or runtime["schema_version"] != QUESTION_REVISION_PACKAGE_SCHEMA_VERSION:
        raise QuestionRevisionPackageError("runtime partition shape is invalid")
    for task in runtime["tasks"]:
        if set(task) != {"task_id", "title", "brief", "input", "input_files"}:
            raise QuestionRevisionPackageError("runtime partition contains a judge/provenance field")
        if set(task["input"]) != {"task_instruction", "must_include", "prohibited", "background", "materials"}:
            raise QuestionRevisionPackageError("runtime input shape is invalid")
        for material in task["input"]["materials"]:
            if set(material) != {"file_id", "role", "priority", "rationale"}:
                raise QuestionRevisionPackageError("runtime material contains a non-runtime field")
        for file in task["input_files"]:
            if set(file) != {"file_id", "name", "media_type", "sha256", "content"}:
                raise QuestionRevisionPackageError("runtime file contains a non-runtime field")
        _assert_no_forbidden_runtime_keys(task)


def _assert_no_forbidden_runtime_keys(value: Any) -> None:
    if isinstance(value, dict):
        if set(value).intersection(_RUNTIME_FORBIDDEN_KEYS):
            raise QuestionRevisionPackageError("runtime partition contains judge/provenance data")
        for child in value.values():
            _assert_no_forbidden_runtime_keys(child)
    elif isinstance(value, list):
        for child in value:
            _assert_no_forbidden_runtime_keys(child)


def build_question_revision_package(
    *,
    version_id: str,
    workspace_id: str,
    version_number: int,
    contract_revision: int,
    contract_revision_id: str,
    contract: dict[str, Any],
    coverage: dict[str, Any],
    tasks: list[QuestionRevisionPackageTask],
    frozen_by: str,
    frozen_at: datetime,
    risk_confirmation: dict[str, Any],
    storage: LocalStorage | None = None,
) -> QuestionRevisionPackageArtifacts:
    if not tasks:
        raise QuestionRevisionPackageError("at least one task is required")
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
        "schema_version": QUESTION_REVISION_PACKAGE_SCHEMA_VERSION,
        "version": {"id": version_id, "workspace_id": workspace_id, "number": version_number},
        "contract": {"revision": contract_revision, "content": contract},
        "coverage": coverage,
        "tasks": [
            {
                "task_id": task.task_id,
                "revision": task.revision,
                "contract_revision_id": contract_revision_id,
                **({"question_revision_id": task.question_revision_id} if task.question_revision_id else {}),
                **({"content_sha256": task.content_sha256} if task.content_sha256 else {}),
            }
            for task in sorted(tasks, key=lambda item: item.task_id)
        ],
        "partitions": {
            "runtime": {"file": "runtime.json", "sha256": runtime_hash, "bytes": len(runtime_bytes)},
            "judge": {"file": "judge.json", "sha256": judge_hash, "bytes": len(judge_bytes)},
            "provenance": {"file": "provenance.json", "sha256": provenance_hash, "bytes": len(provenance_bytes)},
        },
        "frozen": {"by": frozen_by, "at": frozen_at.isoformat(), "risk_confirmation": risk_confirmation},
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
    return QuestionRevisionPackageArtifacts(
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


def read_manifest_v2(storage: LocalStorage, key: str) -> dict[str, Any]:
    try:
        if not storage.is_ready(key):
            raise QuestionRevisionPackageError("version manifest is not ready")
        value = json.loads(storage.read_bytes(key))
    except (StorageError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QuestionRevisionPackageError("version manifest cannot be read") from exc
    if not isinstance(value, dict) or value.get("schema_version") != QUESTION_REVISION_PACKAGE_SCHEMA_VERSION:
        raise QuestionRevisionPackageError("version manifest schema is invalid")
    return value
