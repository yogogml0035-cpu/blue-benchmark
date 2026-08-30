from __future__ import annotations

from hashlib import sha256
from io import BytesIO
import json
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from fastapi.testclient import TestClient

from app.features.case_builder import cocreation_repository, cocreation_service
from app.features.evaluation_sets import repository as evaluation_repository
from app.lib.ai_runtime import get_adapters, reset_adapters, set_adapters
from app.lib.ai_runtime.adapters import AgentRunResult, FakeCoverageReviewer, RuntimeAdapters
from app.lib.ai_runtime.evidence import ReadOnlyEvidenceBackend, documents_for_files
from app.lib.database import clear_business_data
from app.lib.errors import AppError
from app.lib.operations.worker import default_worker
from app.lib.storage import LocalStorage
from app.main import app


@pytest.fixture(autouse=True)
def reset_state() -> None:
    clear_business_data()
    reset_adapters()
    yield
    reset_adapters()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _register_and_create_workspace(client: TestClient) -> str:
    suffix = uuid4().hex[:10]
    registered = client.post(
        "/api/auth/register",
        json={
            "username": f"integration-{suffix}",
            "email": f"integration-{suffix}@example.com",
            "password": "password123",
        },
    )
    assert registered.status_code == 201
    created = client.post("/api/workspaces", json={"name": "合成集成场景"})
    assert created.status_code == 201
    return created.json()["workspace"]["id"]


def _jsonl_fixture() -> bytes:
    rows = []
    for index in range(1, 131):
        row = {"event_id": f"synthetic-event-{index}", "type": "assistant", "index": index}
        if index == 125:
            row["teacher_feedback"] = "synthetic-tail-feedback"
        if index == 130:
            row["final_result"] = "synthetic-tail-final"
        rows.append(json.dumps(row, ensure_ascii=False))
    return ("\n".join(rows) + "\n").encode()


def _mega_fixture() -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("script-v2.md", "# 合成讲稿\n开场与事实顺序。\n")
        archive.writestr("shooting-guide.md", "# 合成拍摄指引\n镜头和节奏要求。\n")
        archive.writestr("conversation.md", "# 合成完整对话\nsynthetic-provenance-only\n")
    return output.getvalue()


def _upload_fixture(client: TestClient, workspace_id: str) -> tuple[str, dict[str, str]]:
    response = client.post(
        f"/api/workspaces/{workspace_id}/upload-batches",
        data={"title": "合成异构任务包", "task_description": "形成可复用的主观新闻稿评测题"},
        files=[
            ("files", ("financial-events.jsonl", _jsonl_fixture(), "application/jsonl")),
            ("files", ("mega-evidence.zip", _mega_fixture(), "application/zip")),
            ("files", ("media-brief.md", "# 合成媒体 Brief\n允许使用的事实和输出边界。\n".encode(), "text/markdown")),
        ],
    )
    assert response.status_code == 202
    batch = response.json()["batch"]
    files = {item["original_name"]: item["id"] for item in batch["files"]}
    assert set(files) == {
        "financial-events.jsonl",
        "script-v2.md",
        "shooting-guide.md",
        "conversation.md",
        "media-brief.md",
    }
    assert len(files) == 5
    assert response.json()["studio"]["active_operation"]["status"] == "queued"
    return batch["id"], files


def _confirm_file_roles(client: TestClient, workspace_id: str, batch_id: str, files: dict[str, str]) -> int:
    role_by_name = {
        "financial-events.jsonl": ("provenance", "provenance", False),
        "script-v2.md": ("runtime", "runtime", True),
        "shooting-guide.md": ("runtime", "runtime", True),
        "conversation.md": ("provenance", "provenance", False),
        "media-brief.md": ("brief", "runtime", True),
    }
    batch = client.get(f"/api/workspaces/{workspace_id}/upload-batches/{batch_id}")
    assert batch.status_code == 200
    revision = batch.json()["batch"]["revision"]
    for name, file_id in files.items():
        role, visibility, required = role_by_name[name]
        response = client.patch(
            f"/api/workspaces/{workspace_id}/upload-batches/{batch_id}/files/{file_id}/disposition",
            json={
                "role": role,
                "visibility": visibility,
                "required": required,
                "batch_revision": revision,
            },
        )
        assert response.status_code == 200, response.text
        revision = response.json()["batch"]["revision"]
    assert revision == len(files)
    return revision


def _confirm_two_tasks(
    client: TestClient,
    workspace_id: str,
    batch_id: str,
    files: dict[str, str],
    batch_revision: int,
) -> list[dict]:
    grouped = client.post(
        f"/api/workspaces/{workspace_id}/upload-batches/{batch_id}/task-groups/confirmation",
        json={
            "command_id": "synthetic-two-task-grouping",
            "batch_revision": batch_revision,
            "groups": [
                {
                    "title": "财报媒体供稿任务",
                    "summary": "一条事件流和对应 Brief 共同描述一个供稿任务。",
                    "evidence_file_ids": [files["financial-events.jsonl"], files["media-brief.md"]],
                    "attempts": [
                        {
                            "attempt_key": "financial-draft-1",
                            "label": "事件流中的初稿",
                            "evidence_file_ids": [files["financial-events.jsonl"]],
                        },
                        {
                            "attempt_key": "financial-draft-2",
                            "label": "老师反馈后的修订",
                            "evidence_file_ids": [files["financial-events.jsonl"]],
                        },
                    ],
                },
                {
                    "title": "MEGA 新闻稿任务",
                    "summary": "讲稿、拍摄指引和对话导出共同描述一个任务。",
                    "evidence_file_ids": [
                        files["script-v2.md"],
                        files["shooting-guide.md"],
                        files["conversation.md"],
                    ],
                    "attempts": [
                        {
                            "attempt_key": "mega-revision-2",
                            "label": "更新材料与多轮反馈",
                            "evidence_file_ids": [
                                files["script-v2.md"],
                                files["shooting-guide.md"],
                                files["conversation.md"],
                            ],
                        }
                    ],
                },
            ],
        },
    )
    assert grouped.status_code == 200, grouped.text
    packages = grouped.json()["task_packages"]
    assert len(packages) == 2
    assert sorted(len(item["attempts"]) for item in packages) == [1, 2]
    repeated = client.post(
        f"/api/workspaces/{workspace_id}/upload-batches/{batch_id}/task-groups/confirmation",
        json={
            "command_id": "synthetic-two-task-grouping",
            "batch_revision": batch_revision,
            "groups": [
                {
                    "title": "财报媒体供稿任务",
                    "summary": "一条事件流和对应 Brief 共同描述一个供稿任务。",
                    "evidence_file_ids": [files["financial-events.jsonl"], files["media-brief.md"]],
                    "attempts": [
                        {"attempt_key": "financial-draft-1", "label": "事件流中的初稿", "evidence_file_ids": [files["financial-events.jsonl"]]},
                        {"attempt_key": "financial-draft-2", "label": "老师反馈后的修订", "evidence_file_ids": [files["financial-events.jsonl"]]},
                    ],
                },
                {
                    "title": "MEGA 新闻稿任务",
                    "summary": "讲稿、拍摄指引和对话导出共同描述一个任务。",
                    "evidence_file_ids": [files["script-v2.md"], files["shooting-guide.md"], files["conversation.md"]],
                    "attempts": [
                        {"attempt_key": "mega-revision-2", "label": "更新材料与多轮反馈", "evidence_file_ids": [files["script-v2.md"], files["shooting-guide.md"], files["conversation.md"]]},
                    ],
                },
            ],
        },
    )
    assert repeated.status_code == 200
    assert [item["id"] for item in repeated.json()["task_packages"]] == [item["id"] for item in packages]
    return packages


def _run_worker_once() -> None:
    result = default_worker().run_once()
    assert result is not None
    assert result.status.value == "succeeded", result.last_error


def _finish_cocreation(
    client: TestClient,
    workspace_id: str,
    package_id: str,
    kind: str,
    prefix: str,
) -> dict:
    package = client.get(f"/api/workspaces/{workspace_id}/task-packages/{package_id}").json()["task_package"]
    started = client.post(
        f"/api/workspaces/{workspace_id}/task-packages/{package_id}/co-creation",
        json={"command_id": f"{prefix}-start", "kind": kind, "task_package_revision": package["revision"]},
    )
    assert started.status_code == 202, started.text
    session_id = started.json()["session"]["id"]
    _run_worker_once()
    for index in range(2):
        session = client.get(f"/api/workspaces/{workspace_id}/co-creation/{session_id}").json()["session"]
        assert session["next_action"] == "answer_question"
        assert session["pending_question"]
        assert "checkpoint" not in client.get(f"/api/workspaces/{workspace_id}/co-creation/{session_id}").text.casefold()
        answer = f"{prefix}：合成老师确认的第 {index + 1} 轮业务判断。"
        answered = client.post(
            f"/api/workspaces/{workspace_id}/co-creation/{session_id}/answers",
            json={
                "command_id": f"{prefix}-answer-{index}",
                "question_id": session["pending_question"]["id"],
                "answer": answer,
                "business_revision": session["business_revision"],
            },
        )
        assert answered.status_code == 202, answered.text
        saved = client.get(f"/api/workspaces/{workspace_id}/co-creation/{session_id}").json()["session"]
        assert saved["status"] == "processing"
        assert saved["turns"][-1]["answer"] == answer
        _run_worker_once()
    ready = client.get(f"/api/workspaces/{workspace_id}/co-creation/{session_id}").json()["session"]
    assert ready["status"] == "ready_for_confirmation"
    confirmation_path = "contract-confirmation" if kind == "scenario_contract" else "judgment-confirmation"
    confirmed = client.post(
        f"/api/workspaces/{workspace_id}/co-creation/{session_id}/{confirmation_path}",
        json={"command_id": f"{prefix}-confirm", "business_revision": ready["business_revision"]},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["session"]["status"] == "confirmed"
    return confirmed.json()["session"]


def _freeze(client: TestClient, workspace_id: str, package_ids: list[str]) -> tuple[dict, bytes]:
    created = client.post(
        f"/api/workspaces/{workspace_id}/evaluation-sets/drafts",
        json={"command_id": "synthetic-v1-draft"},
    )
    assert created.status_code == 201
    draft = created.json()["draft"]
    for index, package_id in enumerate(package_ids):
        package = client.get(f"/api/workspaces/{workspace_id}/task-packages/{package_id}").json()["task_package"]
        included = client.post(
            f"/api/workspaces/{workspace_id}/evaluation-sets/drafts/{draft['id']}/members",
            json={
                "command_id": f"synthetic-v1-include-{index}",
                "draft_revision": draft["revision"],
                "task_package_id": package_id,
                "task_package_revision": package["revision"],
                "action": "include",
            },
        )
        assert included.status_code == 200, included.text
        draft = included.json()["draft"]
    coverage = client.post(
        f"/api/workspaces/{workspace_id}/evaluation-sets/drafts/{draft['id']}/coverage-review",
        json={"command_id": "synthetic-v1-coverage", "draft_revision": draft["revision"]},
    )
    assert coverage.status_code == 202, coverage.text
    _run_worker_once()
    draft = client.get(f"/api/workspaces/{workspace_id}/evaluation-sets/drafts/{draft['id']}").json()["draft"]
    assert draft["next_action"] == "freeze"
    freeze = client.post(
        f"/api/workspaces/{workspace_id}/evaluation-sets/drafts/{draft['id']}/freeze",
        json={"command_id": "synthetic-v1-freeze", "draft_revision": draft["revision"]},
    )
    assert freeze.status_code == 202, freeze.text
    operation_id = freeze.json()["operation_id"]
    reopened = TestClient(app)
    reopened.cookies.update(client.cookies)
    assert reopened.get(f"/api/workspaces/{workspace_id}/evaluation-sets/drafts/{draft['id']}").status_code == 200
    finished = default_worker().run_once()
    assert finished is not None and finished.id == operation_id and finished.status.value == "succeeded"
    versions = reopened.get(f"/api/workspaces/{workspace_id}/evaluation-sets/versions")
    assert versions.status_code == 200
    assert [item["version_number"] for item in versions.json()["versions"]] == [1]
    version = versions.json()["versions"][0]
    manifest_response = reopened.get(
        f"/api/workspaces/{workspace_id}/evaluation-sets/versions/{version['id']}/manifest"
    )
    assert manifest_response.status_code == 200
    manifest = manifest_response.json()["manifest"]
    download = reopened.get(f"/api/workspaces/{workspace_id}/evaluation-sets/versions/{version['id']}/download")
    assert download.status_code == 200
    assert download.headers["x-evaluation-version-sha256"] == version["overall_sha256"]
    return manifest, download.content


def test_synthetic_m0_flow_preserves_tasks_attempts_and_partition_contract(client: TestClient) -> None:
    workspace_id = _register_and_create_workspace(client)
    batch_id, files = _upload_fixture(client, workspace_id)
    reopened = TestClient(app)
    reopened.cookies.update(client.cookies)
    assert reopened.get(f"/api/workspaces/{workspace_id}/upload-batches/{batch_id}").status_code == 200
    _run_worker_once()
    batch = reopened.get(f"/api/workspaces/{workspace_id}/upload-batches/{batch_id}").json()
    assert batch["batch"]["status"] == "ready_for_confirmation"
    assert batch["batch"]["revision"] == 0
    assert batch["studio"]["next_action"]["kind"] == "confirm_file_roles"

    batch_revision = _confirm_file_roles(reopened, workspace_id, batch_id, files)
    packages = _confirm_two_tasks(reopened, workspace_id, batch_id, files, batch_revision)
    package_by_title = {item["title"]: item for item in packages}
    assert package_by_title["财报媒体供稿任务"]["attempts"]
    assert package_by_title["MEGA 新闻稿任务"]["attempts"]
    all_workspace_tasks = reopened.get(f"/api/workspaces/{workspace_id}/task-packages")
    assert all_workspace_tasks.status_code == 200
    assert {item["id"] for item in all_workspace_tasks.json()["task_packages"]} == {
        item["id"] for item in packages
    }
    latest_batch = reopened.get(f"/api/workspaces/{workspace_id}/upload-batches/{batch_id}").json()["batch"]
    locked_disposition = reopened.patch(
        f"/api/workspaces/{workspace_id}/upload-batches/{batch_id}/files/{files['media-brief.md']}/disposition",
        json={
            "role": "judge",
            "visibility": "judge",
            "batch_revision": latest_batch["revision"],
        },
    )
    assert locked_disposition.status_code == 409
    assert locked_disposition.json()["error"]["code"] == "FILE_DISPOSITION_LOCKED"

    # The tail of the long event stream is readable through the virtual evidence scope.
    documents = documents_for_files([files["financial-events.jsonl"]])
    evidence = ReadOnlyEvidenceBackend(documents)
    tail = evidence.read(f"/evidence/{files['financial-events.jsonl']}", offset=100, limit=100)
    assert tail.next_offset is None
    tail_content = (tail.file_data or {}).get("content", "")
    assert "synthetic-tail-feedback" in tail_content
    assert "synthetic-tail-final" in tail_content

    contract = _finish_cocreation(
        reopened,
        workspace_id,
        package_by_title["财报媒体供稿任务"]["id"],
        "scenario_contract",
        "synthetic-contract",
    )
    assert contract["contract"]
    assert cocreation_repository.list_contract_revisions(workspace_id)
    for package in package_by_title.values():
        refreshed = reopened.get(
            f"/api/workspaces/{workspace_id}/task-packages/{package['id']}"
        )
        assert refreshed.status_code == 200
        assert refreshed.json()["task_package"]["revision"] > package["revision"]
    for title, prefix in (("财报媒体供稿任务", "synthetic-financial-judgment"), ("MEGA 新闻稿任务", "synthetic-mega-judgment")):
        package = reopened.get(
            f"/api/workspaces/{workspace_id}/task-packages/{package_by_title[title]['id']}"
        ).json()["task_package"]
        judgment = _finish_cocreation(
            reopened,
            workspace_id,
            package["id"],
            "task_judgment",
            prefix,
        )
        assert judgment["judgment_package"]

    refreshed_packages = [
        reopened.get(f"/api/workspaces/{workspace_id}/task-packages/{item['id']}").json()["task_package"]
        for item in packages
    ]
    manifest, package_bytes = _freeze(reopened, workspace_id, [item["id"] for item in refreshed_packages])
    assert len(manifest["tasks"]) == 2
    assert manifest["partitions"]["runtime"]["sha256"]
    assert manifest["partitions"]["judge"]["sha256"]
    assert manifest["partitions"]["provenance"]["sha256"]
    assert manifest["overall_sha256"] == sha256(
        json.dumps(
            {key: value for key, value in manifest.items() if key != "overall_sha256"},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()

    with ZipFile(BytesIO(package_bytes)) as archive:
        assert set(archive.namelist()) == {"manifest.json", "runtime.json", "judge.json", "provenance.json"}
        runtime = json.loads(archive.read("runtime.json"))
        judge = json.loads(archive.read("judge.json"))
        provenance = json.loads(archive.read("provenance.json"))
        assert len(runtime["tasks"]) == len(judge["tasks"]) == len(provenance["tasks"]) == 2
        runtime_text = archive.read("runtime.json").decode()
        assert "reference_results" not in runtime_text
        assert "minimum_quality_line" not in runtime_text
        assert "hard_gates" not in runtime_text
        assert "synthetic-provenance-only" not in runtime_text
        assert "attempts" not in runtime_text

    version_record = evaluation_repository.list_versions(workspace_id)[0]
    other = TestClient(app)
    suffix = uuid4().hex[:10]
    registered = other.post(
        "/api/auth/register",
        json={
            "username": f"other-{suffix}",
            "email": f"other-{suffix}@example.com",
            "password": "password123",
        },
    )
    assert registered.status_code == 201
    for path in (
        f"/api/workspaces/{workspace_id}/task-packages",
        f"/api/workspaces/{workspace_id}/evaluation-sets/versions",
        f"/api/workspaces/{workspace_id}/evaluation-sets/versions/{version_record.id}/manifest",
        f"/api/workspaces/{workspace_id}/evaluation-sets/versions/{version_record.id}/download",
    ):
        forbidden = other.get(path)
        assert forbidden.status_code == 403
        assert "财报媒体供稿任务" not in forbidden.text

    duplicate_entry = BytesIO(package_bytes)
    with pytest.warns(UserWarning):
        with ZipFile(duplicate_entry, "a") as archive:
            archive.writestr("manifest.json", archive.read("manifest.json"))
    LocalStorage().write_bytes(version_record.package_key, duplicate_entry.getvalue())
    assert reopened.get(
        f"/api/workspaces/{workspace_id}/evaluation-sets/versions/{version_record.id}/manifest"
    ).status_code == 500

    assert len(cocreation_repository.list_contract_revisions(workspace_id)) == 1
    assert evaluation_repository.list_versions(workspace_id)


def test_workspace_task_pool_includes_confirmed_tasks_from_later_batches(client: TestClient) -> None:
    workspace_id = _register_and_create_workspace(client)
    first_batch_id, files = _upload_fixture(client, workspace_id)
    _run_worker_once()
    first_revision = _confirm_file_roles(client, workspace_id, first_batch_id, files)
    first_packages = _confirm_two_tasks(client, workspace_id, first_batch_id, files, first_revision)

    later_upload = client.post(
        f"/api/workspaces/{workspace_id}/upload-batches",
        data={"title": "后续批次"},
        files={"files": ("later.md", b"later task", "text/markdown")},
    )
    assert later_upload.status_code == 202
    later_batch = later_upload.json()["batch"]
    _run_worker_once()
    later_file_id = later_batch["files"][0]["id"]
    disposition = client.patch(
        f"/api/workspaces/{workspace_id}/upload-batches/{later_batch['id']}/files/{later_file_id}/disposition",
        json={"role": "runtime", "visibility": "runtime", "required": True, "batch_revision": 0},
    )
    assert disposition.status_code == 200
    grouping = client.post(
        f"/api/workspaces/{workspace_id}/upload-batches/{later_batch['id']}/task-groups/confirmation",
        json={
            "command_id": "later-batch-grouping",
            "batch_revision": disposition.json()["batch"]["revision"],
            "groups": [{"title": "后续确认题", "evidence_file_ids": [later_file_id]}],
        },
    )
    assert grouping.status_code == 200
    later_package_id = grouping.json()["task_packages"][0]["id"]

    current_batch = client.get(f"/api/workspaces/{workspace_id}/upload-batches/{first_batch_id}/task-packages")
    assert current_batch.status_code == 200
    assert {item["id"] for item in current_batch.json()["task_packages"]} == {item["id"] for item in first_packages}
    workspace_pool = client.get(f"/api/workspaces/{workspace_id}/task-packages")
    assert workspace_pool.status_code == 200
    assert {item["id"] for item in workspace_pool.json()["task_packages"]} == {
        *[item["id"] for item in first_packages],
        later_package_id,
    }


def test_approved_standard_promotion_invalidates_task_judgments(client: TestClient) -> None:
    workspace_id = _register_and_create_workspace(client)
    batch_id, files = _upload_fixture(client, workspace_id)
    _run_worker_once()
    batch_revision = _confirm_file_roles(client, workspace_id, batch_id, files)
    packages = _confirm_two_tasks(client, workspace_id, batch_id, files, batch_revision)
    _finish_cocreation(client, workspace_id, packages[0]["id"], "scenario_contract", "promotion-contract")
    for index, package in enumerate(packages):
        _finish_cocreation(client, workspace_id, package["id"], "task_judgment", f"promotion-judgment-{index}")

    feedback = client.post(
        f"/api/workspaces/{workspace_id}/task-packages/{packages[0]['id']}/feedback",
        json={"source_id": files["financial-events.jsonl"], "text": "关键事实需要成为场景级硬门禁。"},
    )
    assert feedback.status_code == 200
    promotion = client.post(
        f"/api/workspaces/{workspace_id}/standard-promotions/{feedback.json()['promotion_id']}/decision",
        json={"decision": "approve"},
    )
    assert promotion.status_code == 200
    for package in packages:
        refreshed = client.get(f"/api/workspaces/{workspace_id}/task-packages/{package['id']}")
        assert refreshed.status_code == 200
        assert refreshed.json()["task_package"]["has_judgment_package"] is False


def test_completed_thread_deletion_does_not_delete_business_projection(client: TestClient) -> None:
    workspace_id = _register_and_create_workspace(client)
    batch_id, files = _upload_fixture(client, workspace_id)
    _run_worker_once()
    batch_revision = _confirm_file_roles(client, workspace_id, batch_id, files)
    packages = _confirm_two_tasks(client, workspace_id, batch_id, files, batch_revision)
    session = _finish_cocreation(client, workspace_id, packages[0]["id"], "scenario_contract", "delete-thread-contract")
    record = cocreation_repository.get_latest_session(packages[0]["id"], "scenario_contract")
    assert record is not None
    adapter = get_adapters().standard_cocreator
    adapter.checkpoints.delete_thread(record.stable_thread_key)  # type: ignore[attr-defined]
    fetched = client.get(f"/api/workspaces/{workspace_id}/co-creation/{session['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["session"]["status"] == "confirmed"
    assert client.get(f"/api/workspaces/{workspace_id}/task-packages/{packages[0]['id']}").status_code == 200


def test_contract_revision_invalidates_old_judgments_for_every_task(client: TestClient) -> None:
    workspace_id = _register_and_create_workspace(client)
    batch_id, files = _upload_fixture(client, workspace_id)
    _run_worker_once()
    batch_revision = _confirm_file_roles(client, workspace_id, batch_id, files)
    packages = _confirm_two_tasks(client, workspace_id, batch_id, files, batch_revision)
    first_package_id, second_package_id = [item["id"] for item in packages]

    _finish_cocreation(client, workspace_id, first_package_id, "scenario_contract", "revision-contract-base")
    _finish_cocreation(client, workspace_id, first_package_id, "task_judgment", "revision-judgment-first")
    _finish_cocreation(client, workspace_id, second_package_id, "task_judgment", "revision-judgment-second")
    _freeze(client, workspace_id, [first_package_id, second_package_id])

    _finish_cocreation(client, workspace_id, first_package_id, "scenario_contract", "revision-contract-new")
    next_draft = client.post(
        f"/api/workspaces/{workspace_id}/evaluation-sets/drafts",
        json={"command_id": "revision-removal-draft"},
    ).json()["draft"]
    removal = client.post(
        f"/api/workspaces/{workspace_id}/evaluation-sets/drafts/{next_draft['id']}/members",
        json={
            "command_id": "revision-remove-old-task",
            "draft_revision": next_draft["revision"],
            "task_package_id": first_package_id,
            "task_package_revision": client.get(
                f"/api/workspaces/{workspace_id}/task-packages/{first_package_id}"
            ).json()["task_package"]["revision"],
            "action": "remove",
        },
    )
    assert removal.status_code == 200, removal.text
    assert next(
        member for member in removal.json()["draft"]["members"] if member["task_package_id"] == first_package_id
    )["status"] == "removed"
    for package_id in (first_package_id, second_package_id):
        package_response = client.get(f"/api/workspaces/{workspace_id}/task-packages/{package_id}")
        assert package_response.status_code == 200
        package = package_response.json()["task_package"]
        assert package["has_contract"] is True
        assert package["has_judgment_package"] is False
        with pytest.raises(AppError, match="判定依据对应"):
            cocreation_service.get_evaluation_task_snapshot(workspace_id, package_id)

        restarted = client.post(
            f"/api/workspaces/{workspace_id}/task-packages/{package_id}/co-creation",
            json={
                "command_id": f"revision-judgment-restart-{package_id}",
                "kind": "task_judgment",
                "task_package_revision": package["revision"],
            },
        )
        assert restarted.status_code == 202, restarted.text


def test_coverage_warning_confirmation_and_duplicate_review_are_fail_closed(client: TestClient) -> None:
    workspace_id = _register_and_create_workspace(client)
    batch_id, files = _upload_fixture(client, workspace_id)
    _run_worker_once()
    batch_revision = _confirm_file_roles(client, workspace_id, batch_id, files)
    packages = _confirm_two_tasks(client, workspace_id, batch_id, files, batch_revision)
    _finish_cocreation(client, workspace_id, packages[0]["id"], "scenario_contract", "coverage-contract")
    for index, package in enumerate(packages):
        _finish_cocreation(client, workspace_id, package["id"], "task_judgment", f"coverage-judgment-{index}")

    class WarningReviewer(FakeCoverageReviewer):
        def review(self, context, snapshot):
            result = super().review(context, snapshot)
            return AgentRunResult(result.result.model_copy(update={"warnings": ["合成覆盖风险"]}))

    current_adapters = get_adapters()
    set_adapters(RuntimeAdapters(current_adapters.evidence_analyzer, current_adapters.standard_cocreator, WarningReviewer()))
    try:
        draft_response = client.post(
            f"/api/workspaces/{workspace_id}/evaluation-sets/drafts",
            json={"command_id": "coverage-draft"},
        )
        assert draft_response.status_code == 201
        draft = draft_response.json()["draft"]
        for index, package in enumerate(packages):
            package_response = client.get(f"/api/workspaces/{workspace_id}/task-packages/{package['id']}")
            current_package = package_response.json()["task_package"]
            included = client.post(
                f"/api/workspaces/{workspace_id}/evaluation-sets/drafts/{draft['id']}/members",
                json={
                    "command_id": f"coverage-include-{index}",
                    "draft_revision": draft["revision"],
                    "task_package_id": current_package["id"],
                    "task_package_revision": current_package["revision"],
                    "action": "include",
                },
            )
            assert included.status_code == 200, included.text
            draft = included.json()["draft"]

        first = client.post(
            f"/api/workspaces/{workspace_id}/evaluation-sets/drafts/{draft['id']}/coverage-review",
            json={"command_id": "coverage-first", "draft_revision": draft["revision"]},
        )
        assert first.status_code == 202
        duplicate = client.post(
            f"/api/workspaces/{workspace_id}/evaluation-sets/drafts/{draft['id']}/coverage-review",
            json={"command_id": "coverage-second", "draft_revision": draft["revision"]},
        )
        assert duplicate.status_code == 409
        assert duplicate.json()["error"]["code"] == "COVERAGE_IN_PROGRESS"
        _run_worker_once()
        current = client.get(f"/api/workspaces/{workspace_id}/evaluation-sets/drafts/{draft['id']}").json()["draft"]
        assert current["coverage"]["warnings"] == ["合成覆盖风险"]
        assert current["coverage"]["confirmed_at"] is None
        rejected = client.post(
            f"/api/workspaces/{workspace_id}/evaluation-sets/drafts/{draft['id']}/coverage-confirmation",
            json={
                "command_id": "coverage-reject",
                "draft_revision": current["revision"],
                "confirmed": False,
                "note": "暂不接受这个风险提示。",
            },
        )
        assert rejected.status_code == 200
        assert rejected.json()["draft"]["coverage"]["confirmed_at"] is None
        assert rejected.json()["draft"]["next_action"] == "confirm_coverage_risk"
        accepted = client.post(
            f"/api/workspaces/{workspace_id}/evaluation-sets/drafts/{draft['id']}/coverage-confirmation",
            json={
                "command_id": "coverage-accept",
                "draft_revision": current["revision"],
                "confirmed": True,
                "note": "老师确认当前样本范围下接受该覆盖风险。",
            },
        )
        assert accepted.status_code == 200
        assert accepted.json()["draft"]["coverage"]["confirmed_at"] is not None
        assert accepted.json()["draft"]["next_action"] == "freeze"
    finally:
        set_adapters(current_adapters)
