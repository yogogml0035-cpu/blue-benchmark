from __future__ import annotations

from io import BytesIO
from uuid import uuid4
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient

from app.features.evaluation_sets import repository as evaluation_repository
from app.features.evaluation_sets import service as evaluation_service
from app.lib.database import clear_business_data
from app.lib.operations.worker import default_worker
from app.lib.operations import repository as operation_repository
from app.lib.operations.worker import SupersededOperation
from app.lib.ai_runtime import reset_adapters
from app.lib.ai_runtime import get_adapters, set_adapters
from app.lib.ai_runtime.adapters import AgentRunResult, FakeCoverageReviewer, FakeEvidenceAnalyzer, RuntimeAdapters
from app.features.case_builder.cocreation_schemas import CoverageReview
from app.lib.storage import LocalStorage
from app.main import app


@pytest.fixture(autouse=True)
def reset_state():
    clear_business_data()
    reset_adapters()
    yield
    reset_adapters()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _formal_task(client: TestClient) -> tuple[str, str, int]:
    suffix = uuid4().hex[:8]
    assert client.post(
        "/api/auth/register",
        json={"username": f"version-{suffix}", "email": f"version-{suffix}@example.com", "password": "password123"},
    ).status_code == 201
    workspace_id = client.post("/api/workspaces", json={"name": "版本场景"}).json()["workspace"]["id"]
    upload = client.post(
        f"/api/workspaces/{workspace_id}/upload-batches",
        data={"title": "正式题包", "task_description": "完成一份可交付新闻稿"},
        files={"files": ("brief.md", BytesIO(b"runtime brief"), "text/markdown")},
    )
    assert upload.status_code == 202
    batch_id = upload.json()["batch"]["id"]
    assert default_worker().run_once().status.value == "succeeded"
    proposal = client.get(f"/api/workspaces/{workspace_id}/upload-batches/{batch_id}/task-packages").json()
    file_id = proposal["task_packages"][0]["evidence_file_ids"][0]
    assert client.patch(
        f"/api/workspaces/{workspace_id}/upload-batches/{batch_id}/files/{file_id}/disposition",
        json={"role": "runtime", "visibility": "runtime", "required": True, "batch_revision": proposal["batch_revision"]},
    ).status_code == 200
    proposal = client.get(f"/api/workspaces/{workspace_id}/upload-batches/{batch_id}/task-packages").json()
    grouped = client.post(
        f"/api/workspaces/{workspace_id}/upload-batches/{batch_id}/task-groups/confirmation",
        json={
            "command_id": "version-group",
            "batch_revision": proposal["batch_revision"],
            "groups": [{"title": "新闻稿题", "evidence_file_ids": [file_id]}],
        },
    )
    assert grouped.status_code == 200
    package_id = grouped.json()["task_packages"][0]["id"]

    def finish(kind: str, prefix: str, confirmation: str) -> None:
        package = client.get(f"/api/workspaces/{workspace_id}/task-packages/{package_id}").json()["task_package"]
        started = client.post(
            f"/api/workspaces/{workspace_id}/task-packages/{package_id}/co-creation",
            json={"command_id": f"{prefix}-start", "kind": kind, "task_package_revision": package["revision"]},
        )
        assert started.status_code == 202
        session_id = started.json()["session"]["id"]
        assert default_worker().run_once().status.value == "succeeded"
        for index in range(2):
            session = client.get(f"/api/workspaces/{workspace_id}/co-creation/{session_id}").json()["session"]
            answered = client.post(
                f"/api/workspaces/{workspace_id}/co-creation/{session_id}/answers",
                json={
                    "command_id": f"{prefix}-answer-{index}",
                    "question_id": session["pending_question"]["id"],
                    "answer": "老师确认的业务回答",
                    "business_revision": session["business_revision"],
                },
            )
            assert answered.status_code == 202
            assert default_worker().run_once().status.value == "succeeded"
        session = client.get(f"/api/workspaces/{workspace_id}/co-creation/{session_id}").json()["session"]
        confirmed = client.post(
            f"/api/workspaces/{workspace_id}/co-creation/{session_id}/{confirmation}",
            json={"command_id": f"{prefix}-confirm", "business_revision": session["business_revision"]},
        )
        assert confirmed.status_code == 200

    finish("scenario_contract", "version-contract", "contract-confirmation")
    finish("task_judgment", "version-judgment", "judgment-confirmation")
    package = client.get(f"/api/workspaces/{workspace_id}/task-packages/{package_id}").json()["task_package"]
    return workspace_id, package_id, package["revision"]


def _freeze_one(client: TestClient, workspace_id: str, package_id: str, command: str) -> tuple[str, bytes, str]:
    draft = client.post(f"/api/workspaces/{workspace_id}/evaluation-sets/drafts", json={"command_id": f"{command}-draft"})
    assert draft.status_code == 201
    draft_body = draft.json()["draft"]
    included = client.post(
        f"/api/workspaces/{workspace_id}/evaluation-sets/drafts/{draft_body['id']}/members",
        json={
            "command_id": f"{command}-include",
            "draft_revision": draft_body["revision"],
            "task_package_id": package_id,
            "task_package_revision": client.get(f"/api/workspaces/{workspace_id}/task-packages/{package_id}").json()["task_package"]["revision"],
            "action": "include",
        },
    )
    assert included.status_code == 200
    current = included.json()["draft"]
    repeated_member = client.post(
        f"/api/workspaces/{workspace_id}/evaluation-sets/drafts/{draft_id}/members",
        json={
            "command_id": "v1-include",
            "draft_revision": 0,
            "task_package_id": package_id,
            "task_package_revision": package["revision"],
            "action": "include",
        },
    )
    assert repeated_member.status_code == 200
    assert repeated_member.json()["draft"]["revision"] == current["revision"]
    conflicting_member = client.post(
        f"/api/workspaces/{workspace_id}/evaluation-sets/drafts/{draft_id}/members",
        json={
            "command_id": "v1-include",
            "draft_revision": 0,
            "task_package_id": package_id,
            "task_package_revision": package["revision"],
            "action": "remove",
        },
    )
    assert conflicting_member.status_code == 409
    assert conflicting_member.json()["error"]["code"] == "DRAFT_NOT_EDITABLE"
    coverage = client.post(
        f"/api/workspaces/{workspace_id}/evaluation-sets/drafts/{current['id']}/coverage-review",
        json={"command_id": f"{command}-coverage", "draft_revision": current["revision"]},
    )
    assert coverage.status_code == 202
    assert default_worker().run_once().status.value == "succeeded"
    current = client.get(f"/api/workspaces/{workspace_id}/evaluation-sets/drafts/{current['id']}").json()["draft"]
    frozen = client.post(
        f"/api/workspaces/{workspace_id}/evaluation-sets/drafts/{current['id']}/freeze",
        json={"command_id": command, "draft_revision": current["revision"]},
    )
    assert frozen.status_code == 202
    repeated = client.post(
        f"/api/workspaces/{workspace_id}/evaluation-sets/drafts/{current['id']}/freeze",
        json={"command_id": command, "draft_revision": current["revision"]},
    )
    assert repeated.status_code == 202
    assert repeated.json()["operation_id"] == frozen.json()["operation_id"]
    assert default_worker().run_once().status.value == "succeeded"
    versions = client.get(f"/api/workspaces/{workspace_id}/evaluation-sets/versions").json()["versions"]
    version = versions[0]
    download = client.get(f"/api/workspaces/{workspace_id}/evaluation-sets/versions/{version['id']}/download")
    assert download.status_code == 200
    return version["id"], download.content, frozen.json()["draft"]["id"]


def test_freeze_v1_v2_is_continuous_and_history_is_immutable(client: TestClient):
    workspace_id, package_id, _ = _formal_task(client)
    blocked = client.post(
        f"/api/workspaces/{workspace_id}/evaluation-sets/drafts",
        json={"command_id": "draft-for-block"},
    )
    assert blocked.status_code == 201
    draft_id = blocked.json()["draft"]["id"]
    freeze = client.post(
        f"/api/workspaces/{workspace_id}/evaluation-sets/drafts/{draft_id}/freeze",
        json={"command_id": "blocked-no-task", "draft_revision": 0},
    )
    assert freeze.status_code == 409
    assert freeze.json()["error"]["code"] == "FREEZE_BLOCKED"

    # The first draft is still active, so add the formal task and freeze v1.
    included = client.post(
        f"/api/workspaces/{workspace_id}/evaluation-sets/drafts/{draft_id}/members",
        json={
            "command_id": "v1-include",
            "draft_revision": 0,
            "task_package_id": package_id,
            "task_package_revision": client.get(f"/api/workspaces/{workspace_id}/task-packages/{package_id}").json()["task_package"]["revision"],
            "action": "include",
        },
    )
    assert included.status_code == 200
    current = included.json()["draft"]
    no_coverage = client.post(
        f"/api/workspaces/{workspace_id}/evaluation-sets/drafts/{draft_id}/freeze",
        json={"command_id": "no-coverage", "draft_revision": current["revision"]},
    )
    assert no_coverage.status_code == 409
    assert no_coverage.json()["error"]["code"] == "FREEZE_BLOCKED"
    coverage = client.post(
        f"/api/workspaces/{workspace_id}/evaluation-sets/drafts/{draft_id}/coverage-review",
        json={"command_id": "v1-coverage", "draft_revision": current["revision"]},
    )
    assert coverage.status_code == 202
    assert default_worker().run_once().status.value == "succeeded"
    current = client.get(f"/api/workspaces/{workspace_id}/evaluation-sets/drafts/{draft_id}").json()["draft"]
    frozen = client.post(
        f"/api/workspaces/{workspace_id}/evaluation-sets/drafts/{draft_id}/freeze",
        json={"command_id": "v1-freeze", "draft_revision": current["revision"]},
    )
    assert frozen.status_code == 202
    assert default_worker().run_once().status.value == "succeeded"
    versions = client.get(f"/api/workspaces/{workspace_id}/evaluation-sets/versions").json()["versions"]
    assert [item["version_number"] for item in versions] == [1]
    v1 = versions[0]
    v1_manifest = client.get(f"/api/workspaces/{workspace_id}/evaluation-sets/versions/{v1['id']}/manifest")
    assert v1_manifest.status_code == 200
    assert v1_manifest.json()["manifest"]["version"]["id"] == v1["id"]
    v1_download = client.get(f"/api/workspaces/{workspace_id}/evaluation-sets/versions/{v1['id']}/download").content
    with ZipFile(BytesIO(v1_download)) as archive:
        runtime = archive.read("runtime.json").decode()
        assert "reference_results" not in runtime
        assert "minimum_quality_line" not in runtime
        assert "hard_gates" not in runtime
        assert set(archive.namelist()) == {"manifest.json", "runtime.json", "judge.json", "provenance.json"}

    # A new draft is derived from the frozen manifest, not mutable task rows.
    next_draft = client.post(f"/api/workspaces/{workspace_id}/evaluation-sets/drafts", json={"command_id": "v2-draft"})
    assert next_draft.status_code == 201
    derived = next_draft.json()["draft"]
    assert derived["base_version_id"] == v1["id"]
    assert len(derived["members"]) == 1
    assert derived["members"][0]["status"] == "included"
    reused_command = client.post(
        f"/api/workspaces/{workspace_id}/evaluation-sets/drafts/{derived['id']}/freeze",
        json={"command_id": "v1-freeze", "draft_revision": derived["revision"]},
    )
    assert reused_command.status_code == 409
    assert reused_command.json()["error"]["code"] == "COMMAND_ID_REUSED"
    coverage = client.post(
        f"/api/workspaces/{workspace_id}/evaluation-sets/drafts/{derived['id']}/coverage-review",
        json={"command_id": "v2-coverage", "draft_revision": derived["revision"]},
    )
    assert coverage.status_code == 202
    assert default_worker().run_once().status.value == "succeeded"
    current = client.get(f"/api/workspaces/{workspace_id}/evaluation-sets/drafts/{derived['id']}").json()["draft"]
    freeze = client.post(
        f"/api/workspaces/{workspace_id}/evaluation-sets/drafts/{derived['id']}/freeze",
        json={"command_id": "v2-freeze", "draft_revision": current["revision"]},
    )
    assert freeze.status_code == 202
    assert default_worker().run_once().status.value == "succeeded"
    versions = client.get(f"/api/workspaces/{workspace_id}/evaluation-sets/versions").json()["versions"]
    assert [item["version_number"] for item in versions] == [2, 1]
    old_manifest = client.get(f"/api/workspaces/{workspace_id}/evaluation-sets/versions/{v1['id']}/manifest").json()
    assert old_manifest["version"]["overall_sha256"] == v1["overall_sha256"]
    assert client.get(f"/api/workspaces/{workspace_id}/evaluation-sets/versions/{v1['id']}/download").content == v1_download
    version_record = evaluation_repository.get_version(v1["id"])
    assert version_record is not None
    LocalStorage().write_bytes(version_record.runtime_key, b'{"tampered":true}')
    assert client.get(f"/api/workspaces/{workspace_id}/evaluation-sets/versions/{v1['id']}/manifest").status_code == 500
    assert client.get(f"/api/workspaces/{workspace_id}/evaluation-sets/versions/{v1['id']}/download").status_code == 500


def test_reusing_a_terminal_draft_create_command_returns_the_original_draft(client: TestClient):
    workspace_id, package_id, package_revision = _formal_task(client)
    created = client.post(
        f"/api/workspaces/{workspace_id}/evaluation-sets/drafts",
        json={"command_id": "terminal-draft-command"},
    )
    assert created.status_code == 201
    draft = created.json()["draft"]
    included = client.post(
        f"/api/workspaces/{workspace_id}/evaluation-sets/drafts/{draft['id']}/members",
        json={
            "command_id": "terminal-draft-include",
            "draft_revision": draft["revision"],
            "task_package_id": package_id,
            "task_package_revision": package_revision,
            "action": "include",
        },
    )
    assert included.status_code == 200
    coverage = client.post(
        f"/api/workspaces/{workspace_id}/evaluation-sets/drafts/{draft['id']}/coverage-review",
        json={"command_id": "terminal-draft-coverage", "draft_revision": included.json()["draft"]["revision"]},
    )
    assert coverage.status_code == 202
    assert default_worker().run_once().status.value == "succeeded"
    current = client.get(f"/api/workspaces/{workspace_id}/evaluation-sets/drafts/{draft['id']}").json()["draft"]
    freeze = client.post(
        f"/api/workspaces/{workspace_id}/evaluation-sets/drafts/{draft['id']}/freeze",
        json={"command_id": "terminal-draft-freeze", "draft_revision": current["revision"]},
    )
    assert freeze.status_code == 202
    assert default_worker().run_once().status.value == "succeeded"

    reused = client.post(
        f"/api/workspaces/{workspace_id}/evaluation-sets/drafts",
        json={"command_id": "terminal-draft-command"},
    )

    assert reused.status_code == 201
    assert reused.json()["draft"]["id"] == draft["id"]


def test_freeze_rejects_unconfirmed_visibility_and_tampered_package(client: TestClient):
    workspace_id, package_id, package_revision = _formal_task(client)
    discarded_draft = client.post(f"/api/workspaces/{workspace_id}/evaluation-sets/drafts", json={"command_id": "discard-draft"}).json()["draft"]
    discarded = client.post(
        f"/api/workspaces/{workspace_id}/evaluation-sets/drafts/{discarded_draft['id']}/discard",
        json={"command_id": "discard", "draft_revision": discarded_draft["revision"]},
    )
    assert discarded.status_code == 200
    rebuilt = client.post(f"/api/workspaces/{workspace_id}/evaluation-sets/drafts", json={"command_id": "rebuilt-draft"})
    assert rebuilt.status_code == 201
    assert rebuilt.json()["draft"]["id"] != discarded_draft["id"]
    draft = rebuilt.json()["draft"]
    # The task itself is complete, but making a stale task revision cannot pass the member gate.
    stale = client.post(
        f"/api/workspaces/{workspace_id}/evaluation-sets/drafts/{draft['id']}/members",
        json={"command_id": "stale-member", "draft_revision": draft["revision"], "task_package_id": package_id, "task_package_revision": package_revision - 1, "action": "include"},
    )
    assert stale.status_code == 409


def test_contract_revision_requires_teacher_impact_review_before_freeze(client: TestClient):
    workspace_id, package_id, _ = _formal_task(client)
    first_draft = client.post(f"/api/workspaces/{workspace_id}/evaluation-sets/drafts", json={"command_id": "impact-v1-draft"}).json()["draft"]
    package = client.get(f"/api/workspaces/{workspace_id}/task-packages/{package_id}").json()["task_package"]
    included = client.post(
        f"/api/workspaces/{workspace_id}/evaluation-sets/drafts/{first_draft['id']}/members",
        json={"command_id": "impact-v1-include", "draft_revision": first_draft["revision"], "task_package_id": package_id, "task_package_revision": package["revision"], "action": "include"},
    )
    assert included.status_code == 200
    current = included.json()["draft"]
    coverage = client.post(f"/api/workspaces/{workspace_id}/evaluation-sets/drafts/{current['id']}/coverage-review", json={"command_id": "impact-v1-coverage", "draft_revision": current["revision"]})
    assert coverage.status_code == 202
    assert default_worker().run_once().status.value == "succeeded"
    current = client.get(f"/api/workspaces/{workspace_id}/evaluation-sets/drafts/{current['id']}").json()["draft"]
    freeze = client.post(f"/api/workspaces/{workspace_id}/evaluation-sets/drafts/{current['id']}/freeze", json={"command_id": "impact-v1-freeze", "draft_revision": current["revision"]})
    assert freeze.status_code == 202
    assert default_worker().run_once().status.value == "succeeded"

    # The confirmed contract is revised through the same co-creation port.
    package = client.get(f"/api/workspaces/{workspace_id}/task-packages/{package_id}").json()["task_package"]
    session = client.post(
        f"/api/workspaces/{workspace_id}/task-packages/{package_id}/co-creation",
        json={"command_id": "contract-revision-start", "kind": "scenario_contract", "task_package_revision": package["revision"]},
    ).json()["session"]
    assert default_worker().run_once().status.value == "succeeded"
    for index in range(2):
        session = client.get(f"/api/workspaces/{workspace_id}/co-creation/{session['id']}").json()["session"]
        assert client.post(
            f"/api/workspaces/{workspace_id}/co-creation/{session['id']}/answers",
            json={"command_id": f"contract-revision-answer-{index}", "question_id": session["pending_question"]["id"], "answer": "新合同判断", "business_revision": session["business_revision"]},
        ).status_code == 202
        assert default_worker().run_once().status.value == "succeeded"
    session = client.get(f"/api/workspaces/{workspace_id}/co-creation/{session['id']}").json()["session"]
    assert client.post(
        f"/api/workspaces/{workspace_id}/co-creation/{session['id']}/contract-confirmation",
        json={"command_id": "contract-revision-confirm", "business_revision": session["business_revision"]},
    ).status_code == 200
    package = client.get(f"/api/workspaces/{workspace_id}/task-packages/{package_id}").json()["task_package"]

    next_draft = client.post(f"/api/workspaces/{workspace_id}/evaluation-sets/drafts", json={"command_id": "impact-v2-draft"})
    assert next_draft.status_code == 201
    derived = next_draft.json()["draft"]
    assert derived["members"][0]["review_status"] == "review_required"
    blocked = client.post(f"/api/workspaces/{workspace_id}/evaluation-sets/drafts/{derived['id']}/coverage-review", json={"command_id": "impact-v2-coverage", "draft_revision": derived["revision"]})
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "CONTRACT_REVIEW_REQUIRED"
    reviewed = client.post(
        f"/api/workspaces/{workspace_id}/evaluation-sets/drafts/{derived['id']}/impact-reviews/{package_id}",
        json={"command_id": "impact-review", "draft_revision": derived["revision"], "decision": "reviewed", "note": "老师逐题确认新合同不改变本题的可用性。"},
    )
    assert reviewed.status_code == 200
    assert reviewed.json()["draft"]["members"][0]["review_status"] == "reviewed"
    current = reviewed.json()["draft"]
    coverage = client.post(
        f"/api/workspaces/{workspace_id}/evaluation-sets/drafts/{derived['id']}/coverage-review",
        json={"command_id": "impact-v2-coverage-after-review", "draft_revision": current["revision"]},
    )
    assert coverage.status_code == 202
    assert default_worker().run_once().status.value == "succeeded"
    current = client.get(f"/api/workspaces/{workspace_id}/evaluation-sets/drafts/{derived['id']}").json()["draft"]
    freeze = client.post(
        f"/api/workspaces/{workspace_id}/evaluation-sets/drafts/{derived['id']}/freeze",
        json={"command_id": "impact-v2-freeze", "draft_revision": current["revision"]},
    )
    assert freeze.status_code == 202
    assert default_worker().run_once().status.value == "succeeded"


def test_coverage_warning_requires_explicit_risk_confirmation(client: TestClient):
    workspace_id, package_id, package_revision = _formal_task(client)

    class WarningReviewer(FakeCoverageReviewer):
        def review(self, context, snapshot):
            return AgentRunResult(CoverageReview(warnings=["只有一道题，失败模式覆盖有限。"], evidence_refs=[]))

    set_adapters(RuntimeAdapters(FakeEvidenceAnalyzer(), get_adapters().standard_cocreator, WarningReviewer()))
    draft = client.post(f"/api/workspaces/{workspace_id}/evaluation-sets/drafts", json={"command_id": "risk-draft"}).json()["draft"]
    included = client.post(
        f"/api/workspaces/{workspace_id}/evaluation-sets/drafts/{draft['id']}/members",
        json={"command_id": "risk-include", "draft_revision": draft["revision"], "task_package_id": package_id, "task_package_revision": package_revision, "action": "include"},
    ).json()["draft"]
    assert client.post(f"/api/workspaces/{workspace_id}/evaluation-sets/drafts/{draft['id']}/coverage-review", json={"command_id": "risk-coverage", "draft_revision": included["revision"]}).status_code == 202
    assert default_worker().run_once().status.value == "succeeded"
    current = client.get(f"/api/workspaces/{workspace_id}/evaluation-sets/drafts/{draft['id']}").json()["draft"]
    blocked = client.post(f"/api/workspaces/{workspace_id}/evaluation-sets/drafts/{draft['id']}/freeze", json={"command_id": "risk-freeze-blocked", "draft_revision": current["revision"]})
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "COVERAGE_RISK_CONFIRMATION_REQUIRED"
    accepted = client.post(f"/api/workspaces/{workspace_id}/evaluation-sets/drafts/{draft['id']}/freeze", json={"command_id": "risk-freeze", "draft_revision": current["revision"], "coverage_risk_confirmed": True, "risk_confirmation_note": "老师明确接受当前覆盖风险。"})
    assert accepted.status_code == 202
    assert default_worker().run_once().status.value == "succeeded"


def test_reclaimed_coverage_attempt_cannot_save_a_snapshot(client: TestClient):
    workspace_id, package_id, package_revision = _formal_task(client)
    draft = client.post(
        f"/api/workspaces/{workspace_id}/evaluation-sets/drafts",
        json={"command_id": "reclaimed-coverage-draft"},
    ).json()["draft"]
    included = client.post(
        f"/api/workspaces/{workspace_id}/evaluation-sets/drafts/{draft['id']}/members",
        json={
            "command_id": "reclaimed-coverage-include",
            "draft_revision": draft["revision"],
            "task_package_id": package_id,
            "task_package_revision": package_revision,
            "action": "include",
        },
    )
    assert included.status_code == 200
    draft = included.json()["draft"]
    review = client.post(
        f"/api/workspaces/{workspace_id}/evaluation-sets/drafts/{draft['id']}/coverage-review",
        json={"command_id": "reclaimed-coverage-review", "draft_revision": draft["revision"]},
    )
    assert review.status_code == 202
    job = operation_repository.list_for_target("working_set_draft", draft["id"])[0]
    old_worker = operation_repository.claim_next("old-coverage-worker", lease_seconds=0)
    new_worker = operation_repository.claim_next("new-coverage-worker", lease_seconds=60)
    assert old_worker is not None and new_worker is not None
    assert old_worker.id == new_worker.id == job.id
    with pytest.raises(SupersededOperation):
        evaluation_service.handle_coverage_review(old_worker)
    assert evaluation_repository.get_latest_coverage(draft["id"]) is None


def test_failed_freeze_leaves_no_version_and_can_retry_with_new_command(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    workspace_id, package_id, package_revision = _formal_task(client)
    draft = client.post(f"/api/workspaces/{workspace_id}/evaluation-sets/drafts", json={"command_id": "retry-draft"}).json()["draft"]
    included = client.post(
        f"/api/workspaces/{workspace_id}/evaluation-sets/drafts/{draft['id']}/members",
        json={"command_id": "retry-include", "draft_revision": draft["revision"], "task_package_id": package_id, "task_package_revision": package_revision, "action": "include"},
    ).json()["draft"]
    assert client.post(f"/api/workspaces/{workspace_id}/evaluation-sets/drafts/{draft['id']}/coverage-review", json={"command_id": "retry-coverage", "draft_revision": included["revision"]}).status_code == 202
    assert default_worker().run_once().status.value == "succeeded"
    current = client.get(f"/api/workspaces/{workspace_id}/evaluation-sets/drafts/{draft['id']}").json()["draft"]

    def fail_build(**_kwargs):
        raise evaluation_service.VersionPackageError("synthetic package failure")

    monkeypatch.setattr(evaluation_service, "build_package", fail_build)
    failed = client.post(f"/api/workspaces/{workspace_id}/evaluation-sets/drafts/{draft['id']}/freeze", json={"command_id": "failed-freeze", "draft_revision": current["revision"]})
    assert failed.status_code == 202
    assert default_worker().run_once().status.value == "failed"
    assert client.get(f"/api/workspaces/{workspace_id}/evaluation-sets/versions").json()["versions"] == []

    monkeypatch.setattr(evaluation_service, "build_package", __import__("app.lib.version_packages", fromlist=["build_package"]).build_package)
    retried = client.post(f"/api/workspaces/{workspace_id}/evaluation-sets/drafts/{draft['id']}/freeze", json={"command_id": "retry-freeze", "draft_revision": current["revision"]})
    assert retried.status_code == 202
    assert default_worker().run_once().status.value == "succeeded"
    assert [item["version_number"] for item in client.get(f"/api/workspaces/{workspace_id}/evaluation-sets/versions").json()["versions"]] == [1]
