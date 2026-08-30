"""Run an explicit, local-only M0 acceptance flow against the three real samples.

The runner intentionally uses a temporary business database and storage root,
the deterministic Fake adapters, and emits only stage markers. It must never
be part of the default test discovery path.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
import sys
import tempfile
from uuid import uuid4
from zipfile import BadZipFile, ZipFile


class AcceptanceFailure(RuntimeError):
    def __init__(self, stage: str) -> None:
        super().__init__(stage)
        self.stage = stage


def require(condition: bool, stage: str) -> None:
    if not condition:
        raise AcceptanceFailure(stage)


def require_status(response, expected: int, stage: str) -> None:
    require(response.status_code == expected, stage)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the explicit local M0 real-sample acceptance flow.")
    parser.add_argument(
        "--samples-dir",
        type=Path,
        required=True,
        help="Directory containing exactly one .jsonl, one .zip and one .md sample.",
    )
    return parser.parse_args()


def _discover_samples(samples_dir: Path) -> tuple[Path, Path, Path]:
    require(samples_dir.is_dir(), "sample_directory")
    files = sorted(item for item in samples_dir.iterdir() if item.is_file())
    jsonl = [item for item in files if item.suffix.casefold() == ".jsonl"]
    archives = [item for item in files if item.suffix.casefold() == ".zip"]
    markdown = [item for item in files if item.suffix.casefold() == ".md"]
    require(len(files) == 3 and len(jsonl) == len(archives) == len(markdown) == 1, "sample_file_set")
    return jsonl[0], archives[0], markdown[0]


def _inspect_samples(jsonl_path: Path, archive_path: Path, brief_path: Path) -> tuple[bytes, bytes, bytes]:
    jsonl_bytes = jsonl_path.read_bytes()
    jsonl_lines = jsonl_bytes.decode("utf-8-sig").splitlines()
    require(len(jsonl_lines) >= 100, "jsonl_line_count")
    records = []
    for line in jsonl_lines:
        require(bool(line.strip()), "jsonl_blank_line")
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise AcceptanceFailure("jsonl_parse") from exc
        require(isinstance(value, dict), "jsonl_record_shape")
        records.append(value)
    tail_text = json.dumps(records[100:], ensure_ascii=False).casefold()
    require(
        any(keyword in tail_text for keyword in ("老师", "反馈", "终稿", "修改", "feedback", "final", "revision")),
        "jsonl_tail_feedback",
    )

    archive_bytes = archive_path.read_bytes()
    try:
        with ZipFile(BytesIO(archive_bytes)) as archive:
            names = archive.namelist()
            require(len(names) == 3 and all(name.casefold().endswith(".md") for name in names), "zip_member_set")
            for name in names:
                require(".." not in Path(name).parts and not Path(name).is_absolute(), "zip_member_path")
                require(bool(archive.read(name).decode("utf-8-sig").strip()), "zip_member_content")
    except (BadZipFile, OSError, UnicodeDecodeError) as exc:
        raise AcceptanceFailure("zip_read") from exc

    brief_bytes = brief_path.read_bytes()
    brief_lines = brief_bytes.decode("utf-8-sig").splitlines()
    require(len(brief_lines) >= 100, "brief_content")
    return jsonl_bytes, archive_bytes, brief_bytes


def _run_flow(jsonl_path: Path, archive_path: Path, brief_path: Path, *, temp_root: Path) -> None:
    os.environ["DATABASE_URL"] = f"sqlite:///{temp_root / 'business.db'}"
    os.environ["STORAGE_ROOT"] = str(temp_root / "storage")
    os.environ["AI_RUNTIME_MODE"] = "fake"
    os.environ["DATABASE_SCHEMA_CHECK_ON_STARTUP"] = "false"

    backend_root = Path(__file__).resolve().parents[1]
    if str(backend_root) not in sys.path:
        sys.path.insert(0, str(backend_root))

    from fastapi.testclient import TestClient

    from app.features.case_builder import cocreation_repository
    from app.lib.ai_runtime import get_adapters, reset_adapters
    from app.lib.ai_runtime.evidence import ReadOnlyEvidenceBackend, documents_for_files
    from app.lib.database import clear_business_data
    from app.lib.operations.worker import default_worker
    from app.main import app

    reset_adapters()
    clear_business_data()
    jsonl_bytes, archive_bytes, brief_bytes = _inspect_samples(jsonl_path, archive_path, brief_path)

    with TestClient(app) as client:
        suffix = uuid4().hex[:10]
        require_status(
            client.post(
                "/api/auth/register",
                json={
                    "username": f"real-sample-{suffix}",
                    "email": f"real-sample-{suffix}@example.com",
                    "password": "password123",
                },
            ),
            201,
            "register",
        )
        workspace_response = client.post("/api/workspaces", json={"name": "本地真实样本验收"})
        require_status(workspace_response, 201, "workspace")
        workspace_id = workspace_response.json()["workspace"]["id"]

        upload = client.post(
            f"/api/workspaces/{workspace_id}/upload-batches",
            data={"title": "真实样本验收批次", "task_description": "形成主观新闻稿评测题"},
            files=[
                ("files", (jsonl_path.name, jsonl_bytes, "application/jsonl")),
                ("files", (archive_path.name, archive_bytes, "application/zip")),
                ("files", (brief_path.name, brief_bytes, "text/markdown")),
            ],
        )
        require_status(upload, 202, "real_import")
        batch = upload.json()["batch"]
        batch_id = batch["id"]
        file_by_name = {item["original_name"]: item["id"] for item in batch["files"]}
        jsonl_id = file_by_name.get(jsonl_path.name)
        brief_id = file_by_name.get(brief_path.name)
        require(jsonl_id is not None and brief_id is not None, "uploaded_source_files")
        zip_file_ids = [
            file_id
            for name, file_id in file_by_name.items()
            if name not in {jsonl_path.name, brief_path.name}
        ]
        require(len(zip_file_ids) == 3, "expanded_zip_files")

        reopened = TestClient(app)
        reopened.cookies.update(client.cookies)
        require_status(reopened.get(f"/api/workspaces/{workspace_id}/upload-batches/{batch_id}"), 200, "refresh_before_batch")
        batch_job = default_worker().run_once()
        require(batch_job is not None and batch_job.status.value == "succeeded", "batch_analysis")

        current = reopened.get(f"/api/workspaces/{workspace_id}/upload-batches/{batch_id}")
        require_status(current, 200, "batch_projection")
        require(current.json()["batch"]["status"] == "ready_for_confirmation", "batch_ready")
        revision = current.json()["batch"]["revision"]
        names_by_id = {file_id: name for name, file_id in file_by_name.items()}
        for file_id, name in names_by_id.items():
            if name == jsonl_path.name or "对话" in name or "conversation" in name.casefold():
                role, visibility, required = "provenance", "provenance", False
            elif name == brief_path.name:
                role, visibility, required = "brief", "runtime", True
            else:
                role, visibility, required = "runtime", "runtime", True
            disposition = reopened.patch(
                f"/api/workspaces/{workspace_id}/upload-batches/{batch_id}/files/{file_id}/disposition",
                json={"role": role, "visibility": visibility, "required": required, "batch_revision": revision},
            )
            require_status(disposition, 200, "file_disposition")
            revision = disposition.json()["batch"]["revision"]

        evidence = ReadOnlyEvidenceBackend(documents_for_files([jsonl_id]))
        tail = evidence.read(f"/evidence/{jsonl_id}", offset=100, limit=500)
        tail_content = (tail.file_data or {}).get("content", "")
        require(tail.next_offset is None and any(keyword in tail_content for keyword in ("反馈", "终稿", "feedback", "final")), "evidence_tail_read")

        conversation_ids = [
            file_id
            for file_id, name in names_by_id.items()
            if file_id in zip_file_ids and ("对话" in name or "conversation" in name.casefold())
        ]
        mega_runtime_ids = [file_id for file_id in zip_file_ids if file_id not in conversation_ids]
        require(len(conversation_ids) == 1 and len(mega_runtime_ids) == 2, "sample_role_classification")
        groups = [
            {
                "title": "财报媒体供稿任务",
                "summary": "事件流和媒体 Brief 共同描述一个真实任务。",
                "evidence_file_ids": [jsonl_id, brief_id],
                "attempts": [
                    {"attempt_key": "financial-draft-1", "label": "原始事件流", "evidence_file_ids": [jsonl_id]},
                    {"attempt_key": "financial-draft-2", "label": "反馈后的修订", "evidence_file_ids": [jsonl_id]},
                ],
            },
            {
                "title": "MEGA 新闻稿任务",
                "summary": "讲稿、拍摄指引和对话导出共同描述一个真实任务。",
                "evidence_file_ids": [*mega_runtime_ids, *conversation_ids],
                "attempts": [
                    {
                        "attempt_key": "mega-revision-2",
                        "label": "更新材料与多轮反馈",
                        "evidence_file_ids": [*mega_runtime_ids, *conversation_ids],
                    }
                ],
            },
        ]
        grouped = reopened.post(
            f"/api/workspaces/{workspace_id}/upload-batches/{batch_id}/task-groups/confirmation",
            json={"command_id": "real-sample-grouping", "batch_revision": revision, "groups": groups},
        )
        require_status(grouped, 200, "task_grouping")
        packages = grouped.json()["task_packages"]
        require(len(packages) == 2 and sorted(len(item["attempts"]) for item in packages) == [1, 2], "task_attempts")
        repeated = reopened.post(
            f"/api/workspaces/{workspace_id}/upload-batches/{batch_id}/task-groups/confirmation",
            json={"command_id": "real-sample-grouping", "batch_revision": revision, "groups": groups},
        )
        require_status(repeated, 200, "grouping_idempotency")
        require(
            [item["id"] for item in repeated.json()["task_packages"]] == [item["id"] for item in packages],
            "grouping_no_duplicate",
        )

        by_title = {item["title"]: item for item in packages}

        def finish(package_id: str, kind: str, prefix: str) -> dict:
            package_response = reopened.get(f"/api/workspaces/{workspace_id}/task-packages/{package_id}")
            require_status(package_response, 200, "task_package_refresh")
            package = package_response.json()["task_package"]
            started = reopened.post(
                f"/api/workspaces/{workspace_id}/task-packages/{package_id}/co-creation",
                json={"command_id": f"{prefix}-start", "kind": kind, "task_package_revision": package["revision"]},
            )
            require_status(started, 202, "cocreation_start")
            session_id = started.json()["session"]["id"]
            require(default_worker().run_once().status.value == "succeeded", "cocreation_start_worker")
            for index in range(2):
                session_response = reopened.get(f"/api/workspaces/{workspace_id}/co-creation/{session_id}")
                require_status(session_response, 200, "cocreation_refresh")
                session = session_response.json()["session"]
                require(session["next_action"] == "answer_question" and session["pending_question"], "one_question")
                answered = reopened.post(
                    f"/api/workspaces/{workspace_id}/co-creation/{session_id}/answers",
                    json={
                        "command_id": f"{prefix}-answer-{index}",
                        "question_id": session["pending_question"]["id"],
                        "answer": f"真实样本验收的第 {index + 1} 轮业务判断。",
                        "business_revision": session["business_revision"],
                    },
                )
                require_status(answered, 202, "answer_accepted")
                saved = reopened.get(f"/api/workspaces/{workspace_id}/co-creation/{session_id}")
                require_status(saved, 200, "answer_persisted")
                require(saved.json()["session"]["status"] == "processing", "answer_processing")
                require(saved.json()["session"]["turns"][-1]["answer"], "answer_not_lost")
                require(default_worker().run_once().status.value == "succeeded", "cocreation_resume_worker")
            ready = reopened.get(f"/api/workspaces/{workspace_id}/co-creation/{session_id}")
            require_status(ready, 200, "cocreation_ready")
            ready_session = ready.json()["session"]
            require(ready_session["status"] == "ready_for_confirmation", "cocreation_complete")
            confirm_path = "contract-confirmation" if kind == "scenario_contract" else "judgment-confirmation"
            confirmed = reopened.post(
                f"/api/workspaces/{workspace_id}/co-creation/{session_id}/{confirm_path}",
                json={"command_id": f"{prefix}-confirm", "business_revision": ready_session["business_revision"]},
            )
            require_status(confirmed, 200, "cocreation_confirmation")
            require(confirmed.json()["session"]["status"] == "confirmed", "cocreation_confirmed")
            return confirmed.json()["session"]

        contract_session = finish(by_title["财报媒体供稿任务"]["id"], "scenario_contract", "real-contract")
        require(contract_session["contract"] is not None, "contract_projection")
        for title, prefix in (("财报媒体供稿任务", "real-financial-judgment"), ("MEGA 新闻稿任务", "real-mega-judgment")):
            package = reopened.get(
                f"/api/workspaces/{workspace_id}/task-packages/{by_title[title]['id']}"
            ).json()["task_package"]
            judgment_session = finish(package["id"], "task_judgment", prefix)
            require(judgment_session["judgment_package"] is not None, "judgment_projection")

        draft_response = reopened.post(
            f"/api/workspaces/{workspace_id}/evaluation-sets/drafts",
            json={"command_id": "real-v1-draft"},
        )
        require_status(draft_response, 201, "draft_create")
        draft = draft_response.json()["draft"]
        for index, package in enumerate(packages):
            current_package = reopened.get(
                f"/api/workspaces/{workspace_id}/task-packages/{package['id']}"
            ).json()["task_package"]
            included = reopened.post(
                f"/api/workspaces/{workspace_id}/evaluation-sets/drafts/{draft['id']}/members",
                json={
                    "command_id": f"real-v1-include-{index}",
                    "draft_revision": draft["revision"],
                    "task_package_id": current_package["id"],
                    "task_package_revision": current_package["revision"],
                    "action": "include",
                },
            )
            require_status(included, 200, "draft_include")
            draft = included.json()["draft"]
        coverage = reopened.post(
            f"/api/workspaces/{workspace_id}/evaluation-sets/drafts/{draft['id']}/coverage-review",
            json={"command_id": "real-v1-coverage", "draft_revision": draft["revision"]},
        )
        require_status(coverage, 202, "coverage_enqueue")
        require(default_worker().run_once().status.value == "succeeded", "coverage_worker")
        draft = reopened.get(f"/api/workspaces/{workspace_id}/evaluation-sets/drafts/{draft['id']}").json()["draft"]
        require(draft["next_action"] == "freeze", "freeze_ready")
        freeze = reopened.post(
            f"/api/workspaces/{workspace_id}/evaluation-sets/drafts/{draft['id']}/freeze",
            json={"command_id": "real-v1-freeze", "draft_revision": draft["revision"]},
        )
        require_status(freeze, 202, "freeze_enqueue")
        freeze_operation_id = freeze.json()["operation_id"]
        require_status(reopened.get(f"/api/workspaces/{workspace_id}/evaluation-sets/drafts/{draft['id']}"), 200, "refresh_during_freeze")
        freeze_job = default_worker().run_once()
        require(freeze_job is not None and freeze_job.id == freeze_operation_id and freeze_job.status.value == "succeeded", "freeze_worker")

        versions = reopened.get(f"/api/workspaces/{workspace_id}/evaluation-sets/versions")
        require_status(versions, 200, "version_list")
        version = versions.json()["versions"]
        require(len(version) == 1 and version[0]["version_number"] == 1, "single_v1")
        version_id = version[0]["id"]
        manifest_response = reopened.get(
            f"/api/workspaces/{workspace_id}/evaluation-sets/versions/{version_id}/manifest"
        )
        require_status(manifest_response, 200, "manifest_read")
        manifest = manifest_response.json()["manifest"]
        download = reopened.get(f"/api/workspaces/{workspace_id}/evaluation-sets/versions/{version_id}/download")
        require_status(download, 200, "package_download")
        require(download.headers.get("x-evaluation-version-sha256") == version[0]["overall_sha256"], "package_header_hash")
        expected_overall = sha256(
            json.dumps(
                {key: value for key, value in manifest.items() if key != "overall_sha256"},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        require(manifest.get("overall_sha256") == expected_overall, "manifest_overall_hash")
        with ZipFile(BytesIO(download.content)) as package_archive:
            names = set(package_archive.namelist())
            require(names == {"manifest.json", "runtime.json", "judge.json", "provenance.json"}, "package_entries")
            manifest_bytes = package_archive.read("manifest.json")
            runtime_bytes = package_archive.read("runtime.json")
            judge_bytes = package_archive.read("judge.json")
            provenance_bytes = package_archive.read("provenance.json")
            require(json.loads(manifest_bytes) == manifest, "manifest_api_download_identity")
            require(len(json.loads(runtime_bytes)["tasks"]) == 2, "runtime_task_count")
            require(len(json.loads(judge_bytes)["tasks"]) == len(json.loads(provenance_bytes)["tasks"]) == 2, "partition_task_count")
            for partition, content in (("runtime", runtime_bytes), ("judge", judge_bytes), ("provenance", provenance_bytes)):
                require(
                    sha256(content).hexdigest() == manifest["partitions"][partition]["sha256"],
                    f"{partition}_hash",
                )
            runtime = json.loads(runtime_bytes)
            require(set(runtime) == {"schema_version", "tasks"}, "runtime_allowlist")
            require(all(set(task) == {"task_id", "title", "brief", "input_files"} for task in runtime["tasks"]), "runtime_task_allowlist")
            require(
                all(set(file) == {"file_id", "name", "media_type", "sha256", "content"} for task in runtime["tasks"] for file in task["input_files"]),
                "runtime_file_allowlist",
            )

        contract_record = cocreation_repository.get_latest_session(by_title["财报媒体供稿任务"]["id"], "scenario_contract")
        require(contract_record is not None, "contract_record")
        get_adapters().standard_cocreator.checkpoints.delete_thread(contract_record.stable_thread_key)  # type: ignore[attr-defined]
        require_status(
            reopened.get(f"/api/workspaces/{workspace_id}/co-creation/{contract_record.id}"),
            200,
            "completed_thread_cleanup",
        )
        require_status(
            reopened.get(f"/api/workspaces/{workspace_id}/task-packages/{by_title['财报媒体供稿任务']['id']}"),
            200,
            "business_projection_after_cleanup",
        )


def main() -> int:
    args = _arguments()
    try:
        jsonl_path, archive_path, brief_path = _discover_samples(args.samples_dir)
        with tempfile.TemporaryDirectory(prefix="skill-eval-real-sample-") as temporary:
            _run_flow(jsonl_path, archive_path, brief_path, temp_root=Path(temporary))
    except AcceptanceFailure as exc:
        print(f"M0_REAL_SAMPLE_ACCEPTANCE=FAIL stage={exc.stage}")
        return 1
    except (OSError, UnicodeDecodeError, ValueError, KeyError, TypeError) as exc:
        del exc
        print("M0_REAL_SAMPLE_ACCEPTANCE=FAIL stage=unexpected_local_error")
        return 1
    print("SAMPLE_SHAPES=PASS count=3")
    print("REAL_IMPORT_AND_CLASSIFICATION=PASS tasks=2 attempts=3")
    print("COCREATION_RECOVERY_AND_CONFIRMATION=PASS")
    print("VERSION_HASH_AND_RUNTIME_ISOLATION=PASS version=1")
    print("M0_REAL_SAMPLE_ACCEPTANCE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
