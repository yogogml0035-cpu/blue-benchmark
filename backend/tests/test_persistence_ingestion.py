from io import BytesIO
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import stat
import subprocess
import sys
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import pytest
from fastapi.testclient import TestClient

from app.features.auth import repository as auth_repository
from app.features.case_builder import ingestion_repository
from app.features.case_builder import repository as case_repository
from app.features.workspaces import repository as workspace_repository
from app.lib.operations import attempts as attempt_repository
from app.lib.operations import repository as operation_repository
from app.lib.operations.repository import OPERATION_KINDS
from app.lib.operations.worker import (
    OperationWorker,
    ProjectionPendingOperation,
    default_worker,
    fake_worker,
)
from app.lib.settings import settings
from app.lib.storage import LocalStorage, StorageError, sha256_bytes
from app.main import app


@pytest.fixture(autouse=True)
def reset_database():
    auth_repository.reset()
    workspace_repository.reset()
    case_repository.reset()


@pytest.fixture
def client():
    return TestClient(app)


def _setup(client: TestClient) -> str:
    response = client.post(
        "/api/auth/register",
        json={"username": "ingestion-teacher", "email": "ingestion@example.com", "password": "password123"},
    )
    assert response.status_code == 201
    response = client.post("/api/workspaces", json={"name": "持久化场景"})
    assert response.status_code == 201
    return response.json()["workspace"]["id"]


def test_storage_uses_server_keys_and_hashes_content(tmp_path):
    storage = LocalStorage(tmp_path)
    stored = storage.stage_bytes("batch", "file", b"hello")

    assert stored.key == "staging/batch/file"
    assert stored.sha256 == sha256_bytes(b"hello")
    assert storage.read_bytes(stored.key) == b"hello"
    storage.publish(stored.key, "evidence/batch/file")
    assert storage.is_ready("evidence/batch/file")
    assert storage.exists("evidence/batch/file")
    storage.delete("evidence/batch/file")
    assert not storage.exists("evidence/batch/file")
    with pytest.raises(StorageError):
        storage.read_bytes("staging/../outside")
    with pytest.raises(StorageError):
        storage.read_bytes("/etc/passwd")


def test_upload_batch_returns_202_and_read_only_polling(client: TestClient):
    workspace_id = _setup(client)
    response = client.post(
        f"/api/workspaces/{workspace_id}/upload-batches",
        data={"title": "完整任务包", "task_description": "整理真实新闻稿任务"},
        files=[
            ("files", ("brief.md", BytesIO("事实材料\n尾部判断".encode()), "text/markdown")),
            ("files", ("events.jsonl", BytesIO(b'{"event": 1}\n'), "application/x-ndjson")),
        ],
    )
    assert response.status_code == 202
    body = response.json()
    assert body["batch"]["status"] == "analyzing"
    assert len(body["batch"]["files"]) == 2
    assert all("storage_key" not in item for item in body["batch"]["files"])
    batch_id = body["batch"]["id"]
    jobs_before = operation_repository.list_for_target("upload_batch", batch_id)
    assert len(jobs_before) == 1
    assert body["studio"]["next_action"]["kind"] == "wait_for_processing"

    polled = client.get(f"/api/workspaces/{workspace_id}/upload-batches/{batch_id}")
    assert polled.status_code == 200
    assert len(operation_repository.list_for_target("upload_batch", batch_id)) == 1
    assert polled.json()["studio"]["active_operation"]["status"] == "queued"

    completed = default_worker().run_once()
    assert completed is not None
    assert completed.status.value == "succeeded"
    ready = client.get(f"/api/workspaces/{workspace_id}/upload-batches/{batch_id}").json()
    assert ready["batch"]["status"] == "ready_for_confirmation"
    assert ready["studio"]["next_action"]["kind"] == "confirm_file_roles"
    file_id = ready["batch"]["files"][0]["id"]
    disposition = client.patch(
        f"/api/workspaces/{workspace_id}/upload-batches/{batch_id}/files/{file_id}/disposition",
        json={
            "role": "runtime",
            "required": True,
            "ignored": False,
            "visibility": "runtime",
            "batch_revision": 0,
        },
    )
    assert disposition.status_code == 200
    assert disposition.json()["batch"]["revision"] == 1
    assert disposition.json()["batch"]["files"][0]["visibility"] == "runtime"
    stale = client.patch(
        f"/api/workspaces/{workspace_id}/upload-batches/{batch_id}/files/{file_id}/disposition",
        json={"role": "judge", "batch_revision": 0},
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "STALE_BATCH"


def test_upload_command_id_is_idempotent(client: TestClient):
    workspace_id = _setup(client)
    payload = {"title": "同一命令", "command_id": "upload-command-1"}
    first = client.post(
        f"/api/workspaces/{workspace_id}/upload-batches",
        data=payload,
        files={"files": ("first.md", BytesIO(b"first"), "text/markdown")},
    )
    second = client.post(
        f"/api/workspaces/{workspace_id}/upload-batches",
        data={**payload, "title": "不能覆盖原批次"},
        files={"files": ("second.md", BytesIO(b"second"), "text/markdown")},
    )
    assert first.status_code == second.status_code == 202
    assert first.json()["batch"]["id"] == second.json()["batch"]["id"]
    assert [item["original_name"] for item in second.json()["batch"]["files"]] == ["first.md"]
    assert len(operation_repository.list_for_target("upload_batch", first.json()["batch"]["id"])) == 1


def test_upload_failure_removes_storage_and_database_rows(client: TestClient, monkeypatch):
    workspace_id = _setup(client)
    storage = LocalStorage(settings.storage_root)
    before = {item.name for item in (storage.root / "evidence").rglob("*") if item.is_file()}

    def fail_operation(**_kwargs):
        raise RuntimeError("operation store unavailable")

    monkeypatch.setattr(operation_repository, "create_or_get", fail_operation)
    error_client = TestClient(app, raise_server_exceptions=False)
    error_client.cookies.update(client.cookies)
    response = error_client.post(
        f"/api/workspaces/{workspace_id}/upload-batches",
        data={"title": "事务回滚"},
        files={"files": ("rollback.md", BytesIO(b"should be removed"), "text/markdown")},
    )
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert ingestion_repository.latest_batch(workspace_id) is None
    after = {item.name for item in (storage.root / "evidence").rglob("*") if item.is_file()}
    assert after == before


def test_studio_projection_has_canonical_route_and_retry_command(client: TestClient):
    workspace_id = _setup(client)
    upload = client.post(
        f"/api/workspaces/{workspace_id}/upload-batches",
        data={"title": "失败可重试"},
        files={"files": ("brief.md", BytesIO(b"brief"), "text/markdown")},
    )
    assert upload.status_code == 202
    batch = upload.json()["batch"]
    failed = OperationWorker(worker_id="unsupported-worker").run_once()
    assert failed is not None
    assert failed.status.value == "failed"
    studio = client.get(
        f"/api/workspaces/{workspace_id}/upload-batches/studio",
        params={"batch_id": batch["id"]},
    )
    assert studio.status_code == 200
    assert studio.json()["next_action"]["kind"] == "retry_processing"
    retry = client.post(
        f"/api/workspaces/{workspace_id}/upload-batches/{batch['id']}/retry",
        json={"command_id": "retry-command-1", "batch_revision": batch["revision"]},
    )
    assert retry.status_code == 202
    assert retry.json()["studio"]["active_operation"]["status"] == "queued"
    assert default_worker().run_once().status.value == "succeeded"


def test_business_records_survive_a_fresh_python_process(client: TestClient):
    workspace_id = _setup(client)
    upload = client.post(
        f"/api/workspaces/{workspace_id}/upload-batches",
        data={"title": "重启批次"},
        files={"files": ("brief.md", BytesIO("重启后仍可读".encode()), "text/markdown")},
    )
    assert upload.status_code == 202
    batch_id = upload.json()["batch"]["id"]
    completed = default_worker().run_once()
    assert completed is not None and completed.status.value == "succeeded"
    job_id = completed.id
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from app.features.workspaces import repository; "
                f"item = repository.get('{workspace_id}'); "
                "from app.features.case_builder import ingestion_repository; "
                f"batch = ingestion_repository.get_batch('{batch_id}'); "
                "from app.lib.operations import attempts; "
                f"runs = attempts.list_for_job('{job_id}'); "
                "print(f'{item.name if item else \"missing\"}:{batch.title if batch else \"missing\"}:{len(runs)}')"
            ),
        ],
        cwd=Path(__file__).resolve().parents[1],
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == "持久化场景:重启批次:1"


def test_zip_members_are_expanded_and_unsupported_members_are_visible(client: TestClient):
    workspace_id = _setup(client)
    archive_buffer = BytesIO()
    with ZipFile(archive_buffer, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("runtime/brief.md", "一份任务说明")
        archive.writestr("notes.exe", b"not supported")
    response = client.post(
        f"/api/workspaces/{workspace_id}/upload-batches",
        data={"title": "压缩任务包"},
        files={"files": ("evidence.zip", archive_buffer.getvalue(), "application/zip")},
    )
    assert response.status_code == 202
    files = response.json()["batch"]["files"]
    assert {item["original_name"] for item in files} == {"runtime/brief.md", "notes.exe"}
    assert next(item for item in files if item["original_name"] == "notes.exe")["parse_state"] == "unsupported"
    assert response.json()["studio"]["blocking_issues"]


def test_zip_path_traversal_is_rejected(client: TestClient):
    workspace_id = _setup(client)
    archive_buffer = BytesIO()
    with ZipFile(archive_buffer, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("../outside.md", "不应被解包")
    response = client.post(
        f"/api/workspaces/{workspace_id}/upload-batches",
        data={"title": "不安全压缩包"},
        files={"files": ("unsafe.zip", archive_buffer.getvalue(), "application/zip")},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "UNSAFE_ARCHIVE_ENTRY"


def test_zip_directory_paths_are_validated_before_being_skipped(client: TestClient):
    workspace_id = _setup(client)
    archive_buffer = BytesIO()
    with ZipFile(archive_buffer, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("../", "")
    response = client.post(
        f"/api/workspaces/{workspace_id}/upload-batches",
        data={"title": "不安全目录"},
        files={"files": ("unsafe-dir.zip", archive_buffer.getvalue(), "application/zip")},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "UNSAFE_ARCHIVE_ENTRY"


def test_invalid_zip_and_nested_zip_are_rejected(client: TestClient):
    workspace_id = _setup(client)
    invalid = client.post(
        f"/api/workspaces/{workspace_id}/upload-batches",
        data={"title": "损坏压缩包"},
        files={"files": ("broken.zip", b"not a zip", "application/zip")},
    )
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "INVALID_ARCHIVE"

    def zip_with(name: str, content: bytes) -> bytes:
        buffer = BytesIO()
        with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
            archive.writestr(name, content)
        return buffer.getvalue()

    nested = zip_with(
        "middle.zip",
        zip_with("inner.zip", zip_with("deep.md", b"deep")),
    )
    response = client.post(
        f"/api/workspaces/{workspace_id}/upload-batches",
        data={"title": "嵌套压缩包"},
        files={"files": ("outer.zip", nested, "application/zip")},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "ARCHIVE_NESTING_TOO_DEEP"


def test_compression_ratio_and_file_limit_are_enforced(client: TestClient):
    workspace_id = _setup(client)
    bomb_buffer = BytesIO()
    with ZipFile(bomb_buffer, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("repeated.txt", b"0" * 20_000)
    bomb = client.post(
        f"/api/workspaces/{workspace_id}/upload-batches",
        data={"title": "异常压缩比"},
        files={"files": ("ratio.zip", bomb_buffer.getvalue(), "application/zip")},
    )
    assert bomb.status_code == 413
    assert bomb.json()["error"]["code"] == "ARCHIVE_COMPRESSION_RATIO"

    archive_buffer = BytesIO()
    with ZipFile(archive_buffer, "w", compression=ZIP_DEFLATED) as archive:
        for index in range(51):
            archive.writestr(f"file-{index}.md", "内容")
    too_many = client.post(
        f"/api/workspaces/{workspace_id}/upload-batches",
        data={"title": "文件过多"},
        files={"files": ("many.zip", archive_buffer.getvalue(), "application/zip")},
    )
    assert too_many.status_code == 413
    assert too_many.json()["error"]["code"] == "ARCHIVE_TOO_MANY_FILES"


def test_zip_symlink_is_rejected(client: TestClient):
    workspace_id = _setup(client)
    archive_buffer = BytesIO()
    with ZipFile(archive_buffer, "w", compression=ZIP_DEFLATED) as archive:
        info = ZipInfo("link.md")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(info, "target.md")
    response = client.post(
        f"/api/workspaces/{workspace_id}/upload-batches",
        data={"title": "符号链接压缩包"},
        files={"files": ("symlink.zip", archive_buffer.getvalue(), "application/zip")},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "UNSAFE_ARCHIVE_ENTRY"


def test_operation_command_is_idempotent_and_expired_lease_is_reclaimable():
    job = operation_repository.create_or_get(
        kind="batch_analysis",
        target_type="upload_batch",
        target_id="batch-1",
        command_id="command-1",
    )
    retry = operation_repository.create_or_get(
        kind="batch_analysis",
        target_type="upload_batch",
        target_id="batch-1",
        command_id="command-1",
    )
    assert retry.id == job.id

    claimed = operation_repository.claim_next("worker-a", lease_seconds=0)
    assert claimed is not None
    assert claimed.attempts == 1
    reclaimed = operation_repository.claim_next("worker-b", lease_seconds=60)
    assert reclaimed is not None
    assert reclaimed.id == job.id
    assert reclaimed.attempts == 2

    finished = operation_repository.complete(reclaimed.id, "worker-b", {"ok": True})
    assert finished.status.value == "succeeded"
    assert operation_repository.claim_next("worker-c") is None


def test_operation_command_id_cannot_be_reused_for_another_kind():
    operation_repository.create_or_get(
        kind="coverage_review",
        target_type="working_set_draft",
        target_id="draft-1",
        command_id="same-command",
        business_revision=2,
    )

    with pytest.raises(operation_repository.OperationCommandConflict):
        operation_repository.create_or_get(
            kind="freeze_package",
            target_type="working_set_draft",
            target_id="draft-1",
            command_id="same-command",
            business_revision=2,
        )


def test_late_batch_analysis_attempt_cannot_replace_a_new_attempt(client: TestClient):
    from app.features.case_builder.cocreation_schemas import BatchAnalysis, TaskGroupProposal
    from app.features.case_builder import cocreation_repository

    workspace_id = _setup(client)
    response = client.post(
        f"/api/workspaces/{workspace_id}/upload-batches",
        data={"title": "旧分析结果"},
        files={"files": ("evidence.md", BytesIO(b"evidence"), "text/markdown")},
    )
    assert response.status_code == 202
    batch = response.json()["batch"]
    file_id = batch["files"][0]["id"]
    old_attempt = operation_repository.claim_next("old-worker", lease_seconds=0)
    new_attempt = operation_repository.claim_next("new-worker", lease_seconds=60)
    assert old_attempt is not None and new_attempt is not None
    assert old_attempt.id == new_attempt.id
    analysis = BatchAnalysis(
        groups=[
            TaskGroupProposal(
                proposal_key="proposal-1",
                title="任务",
                summary="摘要",
                evidence_file_ids=[file_id],
            )
        ]
    )

    with pytest.raises(cocreation_repository.RepositoryConflict, match="attempt is stale"):
        cocreation_repository.replace_proposals(
            batch["id"],
            analysis,
            expected_revision=batch["revision"],
            operation_job_id=old_attempt.id,
            operation_attempt=old_attempt.attempts,
        )

    committed = cocreation_repository.replace_proposals(
        batch["id"],
        analysis,
        expected_revision=batch["revision"],
        operation_job_id=new_attempt.id,
        operation_attempt=new_attempt.attempts,
    )
    assert len(committed) == 1
    with pytest.raises(cocreation_repository.RepositoryConflict, match="no longer accepts"):
        cocreation_repository.replace_proposals(
            batch["id"],
            analysis,
            expected_revision=batch["revision"],
            operation_job_id=new_attempt.id,
            operation_attempt=new_attempt.attempts,
        )


def test_fake_worker_supports_all_operation_kinds():
    created = [
        operation_repository.create_or_get(
            kind=kind,
            target_type="target",
            target_id=f"target-{index}",
            command_id=f"command-{index}",
        )
        for index, kind in enumerate(OPERATION_KINDS)
    ]
    worker = fake_worker()
    finished = [worker.run_once() for _ in created]
    assert [item.status.value for item in finished if item] == ["succeeded"] * len(created)


@pytest.mark.parametrize("kind", OPERATION_KINDS)
def test_operation_command_idempotency_applies_to_every_supported_kind(kind: str):
    first = operation_repository.create_or_get(
        kind=kind,
        target_type="target",
        target_id=f"target-{kind}",
        command_id=f"command-{kind}",
    )
    second = operation_repository.create_or_get(
        kind=kind,
        target_type="target",
        target_id=f"target-{kind}",
        command_id=f"command-{kind}",
    )
    assert second.id == first.id


def test_retryable_operation_exhausts_its_attempt_budget():
    job = operation_repository.create_or_get(
        kind="batch_analysis",
        target_type="batch",
        target_id="retry-budget",
        command_id="retry-budget-command",
        max_attempts=2,
    )
    first_claim = operation_repository.claim_next("retry-worker-1")
    assert first_claim is not None and first_claim.id == job.id
    first_failure = operation_repository.fail(
        job.id,
        "retry-worker-1",
        {"code": "TEMPORARY", "message": "retry"},
        retryable=True,
    )
    assert first_failure.status.value == "queued"
    second_claim = operation_repository.claim_next("retry-worker-2")
    assert second_claim is not None and second_claim.attempts == 2
    final_failure = operation_repository.fail(
        job.id,
        "retry-worker-2",
        {"code": "TEMPORARY", "message": "retry again"},
        retryable=True,
    )
    assert final_failure.status.value == "failed"
    assert operation_repository.claim_next("retry-worker-3") is None


def test_attempt_records_keep_base_and_produced_checkpoint_pointers():
    job = operation_repository.create_or_get(
        kind="cocreation_resume",
        target_type="session",
        target_id="session-1",
        command_id="command-1",
    )
    attempt = attempt_repository.create(
        operation_job_id=job.id,
        target_type=job.target_type,
        target_id=job.target_id,
        attempt_number=1,
        base_checkpoint_id="accepted-1",
    )
    produced = attempt_repository.mark_produced(
        attempt.id,
        produced_checkpoint_id="produced-1",
        result_hash="a" * 64,
    )
    assert produced.base_checkpoint_id == "accepted-1"
    assert produced.produced_checkpoint_id == "produced-1"
    assert produced.result_hash == "a" * 64


def test_projection_pending_is_a_distinct_recoverable_operation_state():
    job = operation_repository.create_or_get(
        kind="cocreation_reproject",
        target_type="session",
        target_id="session-2",
        command_id="command-2",
        accepted_checkpoint_id="accepted-2",
    )
    worker = OperationWorker(worker_id="projection-worker")
    worker.register(
        "cocreation_reproject",
        lambda _: (_ for _ in ()).throw(
            ProjectionPendingOperation(
                produced_checkpoint_id="produced-2",
                result_hash="b" * 64,
            )
        ),
    )
    result = worker.run_once()
    assert result is not None
    assert result.status.value == "projection_pending"
    attempt = attempt_repository.list_for_job(job.id)[0]
    assert attempt.status == "projection_pending"
    assert attempt.base_checkpoint_id == "accepted-2"
    assert attempt.produced_checkpoint_id == "produced-2"


def test_operation_commit_cas_supersedes_late_business_results():
    job = operation_repository.create_or_get(
        kind="coverage_review",
        target_type="draft",
        target_id="draft-1",
        command_id="command-cas",
        business_revision=2,
        accepted_checkpoint_id="accepted-cas",
    )
    claimed = operation_repository.claim_next("cas-worker")
    assert claimed is not None and claimed.id == job.id
    result = operation_repository.complete_if_current(
        job.id,
        "cas-worker",
        current_revision=3,
        current_accepted_checkpoint_id="accepted-cas",
        result={"should_not_commit": True},
    )
    assert result.status.value == "superseded"
    assert result.result is None


def test_concurrent_claims_assign_one_job_to_one_worker():
    operation_repository.create_or_get(
        kind="batch_analysis",
        target_type="batch",
        target_id="concurrent-batch",
        command_id="concurrent-command",
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        claimed = list(executor.map(operation_repository.claim_next, ["worker-1", "worker-2"]))
    assert sum(item is not None for item in claimed) == 1
