from __future__ import annotations

from io import BytesIO
import json
from datetime import datetime, timezone
from uuid import uuid4
from zipfile import ZipFile

from fastapi.testclient import TestClient
import pytest

from app.features.case_builder import authoring_repository
from app.features.evaluation_sets import repository as evaluation_repository
from app.lib.database import session_scope
from app.lib.database.models import ScenarioContractRevisionRow
from app.lib.ai_runtime import reset_adapters
from app.lib.operations.worker import default_worker
from app.lib.storage import LocalStorage
from app.lib.version_packages import (
    QuestionRevisionPackageError,
    QuestionRevisionPackageFile,
    QuestionRevisionPackageTask,
    build_question_revision_package,
)
from app.main import app
from tests.test_evaluation_versioning import _formal_task
from tests.test_rubric_publishing import _start_and_generate


@pytest.fixture(autouse=True)
def reset_state():
    from app.lib.database import clear_business_data

    clear_business_data()
    reset_adapters()
    yield
    reset_adapters()


def _confirm_workspace_contract(workspace_id: str) -> None:
    timestamp = datetime.now(timezone.utc)
    with session_scope() as session:
        session.add(
            ScenarioContractRevisionRow(
                id=str(uuid4()),
                workspace_id=workspace_id,
                revision=1,
                status="confirmed",
                contract_json={
                    "task_boundary": "只处理已确认的业务题目。",
                    "input_contract": ["使用题目提供的资料。"],
                    "output_contract": ["输出可直接审阅的结果。"],
                    "hard_gates": ["不得编造事实。"],
                    "quality_dimensions": ["事实准确"],
                    "prohibited_errors": ["越过资料边界"],
                    "capabilities": ["事实核验"],
                    "evidence_refs": [{"source_id": "manual"}],
                },
                source_session_id=None,
                confirmed_by=None,
                confirmed_at=timestamp,
                created_at=timestamp,
            )
        )


def _published_revision(client: TestClient) -> tuple[str, str, dict]:
    workspace_id, question_draft_id, generated = _start_and_generate(client)
    confirmed = client.post(
        f"/api/workspaces/{workspace_id}/authoring/rubrics/{generated['id']}/confirmation",
        json={"command_id": "version-rubric-confirm", "rubric_revision": generated["revision"]},
    )
    assert confirmed.status_code == 200, confirmed.text
    published = client.post(
        f"/api/workspaces/{workspace_id}/authoring/rubrics/{generated['id']}/publish",
        json={
            "command_id": "version-rubric-publish",
            "rubric_revision": confirmed.json()["rubric"]["revision"],
        },
    )
    assert published.status_code == 200, published.text
    rubric = published.json()["rubric"]
    assert rubric["published_revision_id"]
    assert question_draft_id == rubric["question_draft_id"]
    return workspace_id, rubric["published_revision_id"], rubric


def test_published_question_revision_enters_v2_working_set_and_preserves_isolation():
    client = TestClient(app)
    workspace_id, revision_id, rubric = _published_revision(client)
    _confirm_workspace_contract(workspace_id)

    revisions = client.get(f"/api/workspaces/{workspace_id}/evaluation-sets/question-revisions")
    assert revisions.status_code == 200, revisions.text
    item = next(value for value in revisions.json()["revisions"] if value["id"] == revision_id)

    created = client.post(
        f"/api/workspaces/{workspace_id}/evaluation-sets/drafts",
        json={"command_id": "v2-draft-create"},
    )
    assert created.status_code == 201, created.text
    draft = created.json()["draft"]
    added = client.post(
        f"/api/workspaces/{workspace_id}/evaluation-sets/drafts/{draft['id']}/question-revisions",
        json={
            "command_id": "v2-question-add",
            "draft_revision": draft["revision"],
            "question_revision_id": revision_id,
            "question_revision_number": item["revision"],
            "question_revision_hash": item["content_sha256"],
            "action": "include",
        },
    )
    assert added.status_code == 200, added.text
    member = added.json()["draft"]["members"][0]
    assert member["task_package_id"] is None
    assert member["question_revision_id"] == revision_id
    assert member["question_revision_number"] == item["revision"]
    assert member["question_revision_hash"] == item["content_sha256"]

    stale_hash = client.post(
        f"/api/workspaces/{workspace_id}/evaluation-sets/drafts/{draft['id']}/question-revisions",
        json={
            "command_id": "v2-question-stale-hash",
            "draft_revision": added.json()["draft"]["revision"],
            "question_revision_id": revision_id,
            "question_revision_number": item["revision"],
            "question_revision_hash": "0" * 64,
            "action": "include",
        },
    )
    assert stale_hash.status_code == 409
    assert stale_hash.json()["error"]["code"] == "STALE_QUESTION_REVISION"

    repeated = client.post(
        f"/api/workspaces/{workspace_id}/evaluation-sets/drafts/{draft['id']}/question-revisions",
        json={
            "command_id": "v2-question-add",
            "draft_revision": draft["revision"],
            "question_revision_id": revision_id,
            "question_revision_number": item["revision"],
            "question_revision_hash": item["content_sha256"],
            "action": "include",
        },
    )
    assert repeated.status_code == 200
    assert repeated.json()["draft"]["revision"] == added.json()["draft"]["revision"]

    conflicting = client.post(
        f"/api/workspaces/{workspace_id}/evaluation-sets/drafts/{draft['id']}/question-revisions",
        json={
            "command_id": "v2-question-add",
            "draft_revision": draft["revision"],
            "question_revision_id": revision_id,
            "question_revision_number": item["revision"],
            "question_revision_hash": "0" * 64,
            "action": "remove",
        },
    )
    assert conflicting.status_code == 409

    current = repeated.json()["draft"]
    coverage = client.post(
        f"/api/workspaces/{workspace_id}/evaluation-sets/drafts/{draft['id']}/coverage-review",
        json={"command_id": "v2-coverage", "draft_revision": current["revision"]},
    )
    assert coverage.status_code == 202, coverage.text
    assert default_worker().run_once().status.value == "succeeded"
    current = client.get(
        f"/api/workspaces/{workspace_id}/evaluation-sets/drafts/{draft['id']}"
    ).json()["draft"]
    frozen = client.post(
        f"/api/workspaces/{workspace_id}/evaluation-sets/drafts/{draft['id']}/freeze",
        json={"command_id": "v2-freeze", "draft_revision": current["revision"]},
    )
    assert frozen.status_code == 202, frozen.text
    assert default_worker().run_once().status.value == "succeeded"

    versions = client.get(f"/api/workspaces/{workspace_id}/evaluation-sets/versions").json()["versions"]
    assert len(versions) == 1
    version = versions[0]
    version_record = evaluation_repository.get_version(version["id"])
    assert version_record is not None
    assert version_record.schema_version == "m0-evaluation-package-v2"
    manifest = client.get(
        f"/api/workspaces/{workspace_id}/evaluation-sets/versions/{version['id']}/manifest"
    )
    assert manifest.status_code == 200, manifest.text
    assert manifest.json()["manifest"]["schema_version"] == "m0-evaluation-package-v2"
    package = client.get(
        f"/api/workspaces/{workspace_id}/evaluation-sets/versions/{version['id']}/download"
    )
    assert package.status_code == 200
    with ZipFile(BytesIO(package.content)) as archive:
        runtime = json.loads(archive.read("runtime.json"))
        judge = json.loads(archive.read("judge.json"))
        provenance = json.loads(archive.read("provenance.json"))
    runtime_text = json.dumps(runtime, ensure_ascii=False)
    assert "reference_answer_text" not in runtime_text
    assert "rubric" not in runtime_text
    assert "pass_threshold" not in runtime_text
    assert judge["tasks"][0]["question_revision_id"] == revision_id
    assert judge["tasks"][0]["reference_answer_text"]
    assert judge["tasks"][0]["rubric"]["criteria"]
    assert judge["tasks"][0]["pass_threshold"] == rubric["rubric"]["pass_threshold"]
    assert provenance["tasks"][0]["question_revision_id"] == revision_id
    assert provenance["tasks"][0]["provenance"]["source_question_hash"]

    # The next working draft follows the immutable v2 manifest, not the
    # mutable rubric projection.  The member keeps the published content hash.
    next_draft = client.post(
        f"/api/workspaces/{workspace_id}/evaluation-sets/drafts",
        json={"command_id": "v2-next-draft"},
    )
    assert next_draft.status_code == 201, next_draft.text
    next_member = next_draft.json()["draft"]["members"][0]
    assert next_member["question_revision_id"] == revision_id
    assert next_member["question_revision_hash"] == item["content_sha256"]

    LocalStorage().write_bytes(version_record.runtime_key, b'{"tampered":true}')
    assert client.get(
        f"/api/workspaces/{workspace_id}/evaluation-sets/versions/{version['id']}/manifest"
    ).status_code == 500
    assert client.get(
        f"/api/workspaces/{workspace_id}/evaluation-sets/versions/{version['id']}/download"
    ).status_code == 500

    # The revision still belongs to the original authoring question and was
    # not replaced by a synthetic TaskPackage identity.
    assert authoring_repository.get_conversation_by_draft(rubric["question_draft_id"]) is not None


def _publish_authored_question_in_workspace(client: TestClient, workspace_id: str) -> tuple[str, str, dict]:
    created = client.post(
        f"/api/workspaces/{workspace_id}/authoring-conversations",
        json={
            "command_id": "mixed-authoring-create",
            "title": "新增题目",
            "task_instruction": "请根据确认资料形成一份可审阅结果。",
            "reference_answer_text": "老师确认的新增题目标准答案。",
        },
    )
    assert created.status_code == 202, created.text
    conversation_id = created.json()["conversation"]["id"]
    assert default_worker().run_once().status.value == "succeeded"
    current = client.get(
        f"/api/workspaces/{workspace_id}/authoring-conversations/{conversation_id}"
    ).json()["conversation"]
    draft = current["question_drafts"][0]
    boundary = client.post(
        f"/api/workspaces/{workspace_id}/authoring-conversations/{conversation_id}/question-boundaries",
        json={
            "command_id": "mixed-boundary-confirm",
            "conversation_revision": current["revision"],
            "action": "confirm",
            "draft_ids": [draft["id"]],
        },
    )
    assert boundary.status_code == 200, boundary.text
    assert default_worker().run_once().status.value == "succeeded"
    current = client.get(
        f"/api/workspaces/{workspace_id}/authoring-conversations/{conversation_id}"
    ).json()["conversation"]
    draft = current["question_drafts"][0]
    confirmed = client.post(
        f"/api/workspaces/{workspace_id}/authoring-conversations/{conversation_id}/question-drafts/{draft['id']}/input-answer-confirmation",
        json={"command_id": "mixed-input-confirm", "draft_revision": draft["revision"]},
    )
    assert confirmed.status_code == 200, confirmed.text
    confirmed_draft = next(
        item for item in confirmed.json()["conversation"]["question_drafts"] if item["id"] == draft["id"]
    )
    started = client.post(
        f"/api/workspaces/{workspace_id}/authoring/question-drafts/{draft['id']}/rubric",
        json={
            "command_id": "mixed-rubric-start",
            "question_revision": confirmed_draft["confirmed_revision"],
        },
    )
    assert started.status_code == 202, started.text
    assert default_worker().run_once().status.value == "succeeded"
    generated = client.get(
        f"/api/workspaces/{workspace_id}/authoring/rubrics/{started.json()['rubric']['id']}"
    ).json()["rubric"]
    confirmed_rubric = client.post(
        f"/api/workspaces/{workspace_id}/authoring/rubrics/{generated['id']}/confirmation",
        json={"command_id": "mixed-rubric-confirm", "rubric_revision": generated["revision"]},
    )
    assert confirmed_rubric.status_code == 200, confirmed_rubric.text
    published = client.post(
        f"/api/workspaces/{workspace_id}/authoring/rubrics/{generated['id']}/publish",
        json={
            "command_id": "mixed-rubric-publish",
            "rubric_revision": confirmed_rubric.json()["rubric"]["revision"],
        },
    )
    assert published.status_code == 200, published.text
    body = published.json()["rubric"]
    return body["question_draft_id"], body["published_revision_id"], body


def test_working_set_freeze_uses_v2_for_mixed_legacy_and_authored_members():
    client = TestClient(app)
    workspace_id, package_id, package_revision = _formal_task(client)
    question_draft_id, revision_id, _ = _publish_authored_question_in_workspace(client, workspace_id)
    published = client.get(f"/api/workspaces/{workspace_id}/evaluation-sets/question-revisions")
    assert published.status_code == 200
    question = next(item for item in published.json()["revisions"] if item["id"] == revision_id)

    created = client.post(
        f"/api/workspaces/{workspace_id}/evaluation-sets/drafts",
        json={"command_id": "mixed-draft-create"},
    )
    assert created.status_code == 201, created.text
    draft = created.json()["draft"]
    legacy = client.post(
        f"/api/workspaces/{workspace_id}/evaluation-sets/drafts/{draft['id']}/members",
        json={
            "command_id": "mixed-legacy-add",
            "draft_revision": draft["revision"],
            "task_package_id": package_id,
            "task_package_revision": package_revision,
            "action": "include",
        },
    )
    assert legacy.status_code == 200, legacy.text
    draft = legacy.json()["draft"]
    authored = client.post(
        f"/api/workspaces/{workspace_id}/evaluation-sets/drafts/{draft['id']}/question-revisions",
        json={
            "command_id": "mixed-authored-add",
            "draft_revision": draft["revision"],
            "question_revision_id": revision_id,
            "question_revision_number": question["revision"],
            "question_revision_hash": question["content_sha256"],
            "action": "include",
        },
    )
    assert authored.status_code == 200, authored.text
    current = authored.json()["draft"]
    assert {item["question_revision_id"] for item in current["members"]} == {None, revision_id}

    coverage = client.post(
        f"/api/workspaces/{workspace_id}/evaluation-sets/drafts/{draft['id']}/coverage-review",
        json={"command_id": "mixed-coverage", "draft_revision": current["revision"]},
    )
    assert coverage.status_code == 202, coverage.text
    assert default_worker().run_once().status.value == "succeeded"
    refreshed = client.get(
        f"/api/workspaces/{workspace_id}/evaluation-sets/drafts/{draft['id']}"
    ).json()["draft"]
    frozen = client.post(
        f"/api/workspaces/{workspace_id}/evaluation-sets/drafts/{draft['id']}/freeze",
        json={"command_id": "mixed-freeze", "draft_revision": refreshed["revision"]},
    )
    assert frozen.status_code == 202, frozen.text
    assert default_worker().run_once().status.value == "succeeded"
    version = client.get(f"/api/workspaces/{workspace_id}/evaluation-sets/versions").json()["versions"][0]
    manifest = client.get(
        f"/api/workspaces/{workspace_id}/evaluation-sets/versions/{version['id']}/manifest"
    ).json()["manifest"]
    assert manifest["schema_version"] == "m0-evaluation-package-v2"
    assert any(item.get("question_revision_id") == revision_id for item in manifest["tasks"])
    assert any(item.get("task_id") == package_id and "question_revision_id" not in item for item in manifest["tasks"])

    next_draft = client.post(
        f"/api/workspaces/{workspace_id}/evaluation-sets/drafts",
        json={"command_id": "mixed-next-draft"},
    )
    assert next_draft.status_code == 201, next_draft.text
    members = next_draft.json()["draft"]["members"]
    assert {item["question_revision_id"] for item in members} == {None, revision_id}
    assert next(item for item in members if item["question_revision_id"] == revision_id)["question_revision_hash"] == question["content_sha256"]
    assert question_draft_id


def test_v2_builder_rechecks_ready_file_hash_before_freeze(tmp_path):
    storage = LocalStorage(tmp_path / "storage")
    raw = "可供运行的输入资料。".encode("utf-8")
    staged = storage.stage_bytes("test-batch", "file-1", raw)
    storage.publish(staged.key, "evidence/file-1")
    task = QuestionRevisionPackageTask(
        task_id="question-revision-1",
        revision=1,
        title="事实题",
        brief="请根据输入资料形成结果。",
        input={
            "task_instruction": "请根据输入资料形成结果。",
            "must_include": [],
            "prohibited": [],
            "background": None,
            "materials": [{"file_id": "file-1", "role": "fact", "priority": 0, "rationale": None}],
        },
        files=(
            QuestionRevisionPackageFile(
                file_id="file-1",
                name="事实.md",
                media_type="text/markdown",
                size_bytes=len(raw),
                sha256=staged.sha256,
                storage_key="evidence/file-1",
                role="fact",
                required=True,
                visibility="runtime",
            ),
        ),
        question_revision_id="question-revision-1",
        content_sha256="1" * 64,
        judge={"reference_answer_text": "老师确认的标准答案。", "rubric": {"criteria": []}, "pass_threshold": 60},
        provenance={"source_question_hash": "2" * 64},
    )
    artifact = build_question_revision_package(
        version_id="version-1",
        workspace_id="workspace-1",
        version_number=1,
        contract_revision=1,
        contract_revision_id="contract-1",
        contract={},
        coverage={},
        tasks=[task],
        frozen_by="teacher-1",
        frozen_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        risk_confirmation={"confirmed": False, "note": None},
        storage=storage,
    )
    assert b"reference_answer_text" not in artifact.runtime_bytes
    storage.write_bytes("evidence/file-1", b"tampered")
    with pytest.raises(QuestionRevisionPackageError, match="hash"):
        build_question_revision_package(
            version_id="version-1",
            workspace_id="workspace-1",
            version_number=1,
            contract_revision=1,
            contract_revision_id="contract-1",
            contract={},
            coverage={},
            tasks=[task],
            frozen_by="teacher-1",
            frozen_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            risk_confirmation={"confirmed": False, "note": None},
            storage=storage,
        )


def test_authored_revision_from_an_old_contract_is_not_silently_added():
    client = TestClient(app)
    workspace_id, package_id, _ = _formal_task(client)
    _question_draft_id, revision_id, _ = _publish_authored_question_in_workspace(client, workspace_id)
    timestamp = datetime.now(timezone.utc)
    with session_scope() as session:
        session.add(
            ScenarioContractRevisionRow(
                id=str(uuid4()),
                workspace_id=workspace_id,
                revision=2,
                status="confirmed",
                contract_json={
                    "task_boundary": "更新后的独立题目边界。",
                    "input_contract": ["使用当前输入。"],
                    "output_contract": ["输出可审阅结果。"],
                    "hard_gates": ["不得编造。"],
                    "quality_dimensions": ["准确"],
                    "prohibited_errors": [],
                    "capabilities": ["核验"],
                    "evidence_refs": [{"source_id": "manual"}],
                },
                source_session_id=None,
                confirmed_by=None,
                confirmed_at=timestamp,
                created_at=timestamp,
            )
        )
    draft = client.post(
        f"/api/workspaces/{workspace_id}/evaluation-sets/drafts",
        json={"command_id": "contract-mismatch-draft"},
    )
    assert draft.status_code == 201, draft.text
    revisions = client.get(f"/api/workspaces/{workspace_id}/evaluation-sets/question-revisions").json()["revisions"]
    item = next(value for value in revisions if value["id"] == revision_id)
    response = client.post(
        f"/api/workspaces/{workspace_id}/evaluation-sets/drafts/{draft.json()['draft']['id']}/question-revisions",
        json={
            "command_id": "contract-mismatch-add",
            "draft_revision": draft.json()["draft"]["revision"],
            "question_revision_id": revision_id,
            "question_revision_number": item["revision"],
            "question_revision_hash": item["content_sha256"],
            "action": "include",
        },
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONTRACT_REVIEW_REQUIRED"
