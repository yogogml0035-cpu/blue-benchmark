"""Run the explicit real-provider M0 E2E flow against a running local stack.

This runner is opt-in: it never changes AI mode, never prints response bodies,
and expects the caller to provide a real API/Worker environment separately.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import sys
import time
from uuid import uuid4
from zipfile import ZipFile

import httpx

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.lib.operations import repository as operation_repository


PASSWORD = "m0-real-ai-e2e-pass-123"
EXPECTED_PACKAGE_FILES = {"manifest.json", "runtime.json", "judge.json", "provenance.json"}


class RunnerFailure(RuntimeError):
    def __init__(self, stage: str, detail: str = "") -> None:
        super().__init__(stage)
        self.stage = stage
        self.detail = detail


def marker(stage: str, **values: object) -> None:
    suffix = " ".join(f"{key}={value}" for key, value in values.items())
    print(f"M0_REAL_AI_E2E_STAGE={stage}" + (f" {suffix}" if suffix else ""), flush=True)


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the explicit real-provider M0 E2E flow.")
    parser.add_argument("--samples-dir", type=Path, required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout-seconds", type=float, default=900.0)
    parser.add_argument("--max-questions", type=int, default=24)
    return parser.parse_args()


def _discover_samples(root: Path) -> tuple[Path, Path, Path]:
    if not root.is_dir():
        raise RunnerFailure("sample_directory")
    files = sorted(item for item in root.iterdir() if item.is_file())
    jsonl = [item for item in files if item.suffix.casefold() == ".jsonl"]
    archives = [item for item in files if item.suffix.casefold() == ".zip"]
    markdown = [item for item in files if item.suffix.casefold() == ".md"]
    if len(files) != 3 or not (len(jsonl) == len(archives) == len(markdown) == 1):
        raise RunnerFailure("sample_file_set")
    return jsonl[0], archives[0], markdown[0]


def _error_code(response: httpx.Response) -> str | None:
    try:
        body = response.json()
    except ValueError:
        return None
    return (body.get("error") or {}).get("code") if isinstance(body, dict) else None


def _request(
    client: httpx.Client,
    method: str,
    path: str,
    expected: int,
    stage: str,
    **kwargs: object,
) -> dict:
    try:
        response = client.request(method, path, **kwargs)
    except Exception as exc:  # noqa: BLE001 - the runner must stay secret-safe.
        raise RunnerFailure(stage, type(exc).__name__) from exc
    if response.status_code != expected:
        raise RunnerFailure(stage, f"status={response.status_code} code={_error_code(response) or 'none'}")
    try:
        value = response.json() if response.content else {}
    except ValueError as exc:
        raise RunnerFailure(stage, "invalid_json") from exc
    if not isinstance(value, dict):
        raise RunnerFailure(stage, "invalid_response_shape")
    return value


def _poll_batch(client: httpx.Client, workspace_id: str, batch_id: str, timeout: float) -> dict:
    deadline = time.monotonic() + timeout
    previous = None
    while time.monotonic() < deadline:
        batch = _request(
            client,
            "GET",
            f"/api/workspaces/{workspace_id}/upload-batches/{batch_id}",
            200,
            "batch_poll",
        )["batch"]
        status = batch["status"]
        if status != previous:
            marker("batch_status", status=status)
            previous = status
        if status == "ready_for_confirmation":
            return batch
        if status == "failed":
            raise RunnerFailure("batch_analysis", "worker_failed")
        time.sleep(2)
    raise RunnerFailure("batch_timeout")


def _poll_session(client: httpx.Client, workspace_id: str, session_id: str, stage: str, timeout: float) -> dict:
    deadline = time.monotonic() + timeout
    previous = None
    while time.monotonic() < deadline:
        session = _request(
            client,
            "GET",
            f"/api/workspaces/{workspace_id}/co-creation/{session_id}",
            200,
            f"{stage}_poll",
        )["session"]
        status = session["status"]
        if status != previous:
            marker(f"{stage}_status", status=status)
            previous = status
        if status in {"waiting_for_teacher", "ready_for_confirmation"}:
            return session
        if status in {"failed", "continuity_reset", "projection_pending"}:
            raise RunnerFailure(stage, status)
        time.sleep(2)
    raise RunnerFailure(f"{stage}_timeout")


def _verify_package(client: httpx.Client, workspace_id: str, version: dict) -> None:
    manifest = _request(
        client,
        "GET",
        f"/api/workspaces/{workspace_id}/evaluation-sets/versions/{version['id']}/manifest",
        200,
        "manifest",
    )["manifest"]
    response = client.get(f"/api/workspaces/{workspace_id}/evaluation-sets/versions/{version['id']}/download")
    if response.status_code != 200:
        raise RunnerFailure("download", f"status={response.status_code} code={_error_code(response) or 'none'}")
    if response.headers.get("x-evaluation-version-sha256") != version["overall_sha256"]:
        raise RunnerFailure("download_hash")
    expected = sha256(
        json.dumps(
            {key: value for key, value in manifest.items() if key != "overall_sha256"},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    if manifest.get("overall_sha256") != expected:
        raise RunnerFailure("manifest_hash")
    with ZipFile(BytesIO(response.content)) as archive:
        names = archive.namelist()
        if len(names) != 4 or set(names) != EXPECTED_PACKAGE_FILES:
            raise RunnerFailure("package_entries")
        if json.loads(archive.read("manifest.json")) != manifest:
            raise RunnerFailure("manifest_identity")
        partitions = manifest.get("partitions")
        if not isinstance(partitions, dict) or set(partitions) != {"runtime", "judge", "provenance"}:
            raise RunnerFailure("partition_metadata")
        for partition_name in ("runtime", "judge", "provenance"):
            entry = partitions.get(partition_name)
            if not isinstance(entry, dict) or set(entry) != {"file", "sha256", "bytes"}:
                raise RunnerFailure("partition_metadata")
            partition_bytes = archive.read(entry["file"])
            if len(partition_bytes) != entry["bytes"] or sha256(partition_bytes).hexdigest() != entry["sha256"]:
                raise RunnerFailure(f"{partition_name}_hash")
        runtime = json.loads(archive.read("runtime.json"))
        if set(runtime) != {"schema_version", "tasks"}:
            raise RunnerFailure("runtime_allowlist")
        if len(runtime.get("tasks", [])) < 1:
            raise RunnerFailure("runtime_tasks")
        for task in runtime["tasks"]:
            if set(task) != {"task_id", "title", "brief", "input", "input_files"}:
                raise RunnerFailure("runtime_allowlist")
            for file in task["input_files"]:
                if set(file) != {"file_id", "name", "media_type", "sha256", "content"}:
                    raise RunnerFailure("runtime_allowlist")
        runtime_text = json.dumps(runtime, ensure_ascii=False).casefold()
        for term in (
            "reference_results",
            "minimum_quality_line",
            "hard_gates",
            "accepted_reasons",
            "rejected_reasons",
            "private_reasoning",
            "api_key",
            "provenance",
            "bad_samples",
        ):
            if term in runtime_text:
                raise RunnerFailure("runtime_leakage", term)


def _verify_production_worker(
    batch_id: str,
    conversation_id: str,
    rubric_id: str,
) -> None:
    targets = [("upload_batch", batch_id), ("authoring_conversation", conversation_id), ("rubric_draft", rubric_id)]
    jobs = [job for target_type, target_id in targets for job in operation_repository.list_for_target(target_type, target_id)]
    if not jobs:
        raise RunnerFailure("worker_attestation", "no_operations")
    if any(job.status.value != "succeeded" for job in jobs):
        raise RunnerFailure("worker_attestation", "unfinished_operation")
    modes = {(job.result or {}).get("__worker_runtime_mode") for job in jobs}
    if modes != {"production"}:
        raise RunnerFailure("worker_attestation", "non_production_worker")


def _poll_authoring(
    client: httpx.Client,
    workspace_id: str,
    conversation_id: str,
    timeout: float,
    stage: str,
) -> dict:
    deadline = time.monotonic() + timeout
    previous = None
    while time.monotonic() < deadline:
        conversation = _request(
            client,
            "GET",
            f"/api/workspaces/{workspace_id}/authoring-conversations/{conversation_id}",
            200,
            f"{stage}_poll",
        )["conversation"]
        state = (conversation.get("status"), conversation.get("next_action"))
        if state != previous:
            marker(f"{stage}_status", status=state[0], next_action=state[1])
            previous = state
        if conversation.get("status") in {"failed", "projection_pending", "continuity_reset"}:
            raise RunnerFailure(stage, str(conversation.get("status")))
        if conversation.get("next_action") != "wait_for_processing":
            return conversation
        time.sleep(2)
    raise RunnerFailure(f"{stage}_timeout")


def _poll_rubric(
    client: httpx.Client,
    workspace_id: str,
    rubric_id: str,
    timeout: float,
) -> dict:
    deadline = time.monotonic() + timeout
    previous = None
    while time.monotonic() < deadline:
        rubric = _request(
            client,
            "GET",
            f"/api/workspaces/{workspace_id}/authoring/rubrics/{rubric_id}",
            200,
            "rubric_poll",
        )["rubric"]
        status = rubric.get("status")
        if status != previous:
            marker("rubric_status", status=status)
            previous = status
        if status == "review_ready":
            return rubric
        if status in {"failed", "projection_pending", "stale"}:
            raise RunnerFailure("rubric", str(status))
        time.sleep(2)
    raise RunnerFailure("rubric_timeout")


def run(args: argparse.Namespace) -> None:
    jsonl_path, archive_path, markdown_path = _discover_samples(args.samples_dir)
    with ZipFile(archive_path) as archive:
        if len(archive.namelist()) != 3 or not all(name.casefold().endswith(".md") for name in archive.namelist()):
            raise RunnerFailure("zip_member_set")
    base_url = args.base_url.rstrip("/")
    run_nonce = uuid4().hex[:10]
    with httpx.Client(base_url=base_url, timeout=httpx.Timeout(180.0, connect=10.0)) as client:
        suffix = uuid4().hex[:10]
        username = f"real-ai-{suffix}"
        _request(
            client,
            "POST",
            "/api/auth/register",
            201,
            "register",
            json={"username": username, "email": f"{username}@example.com", "password": PASSWORD},
        )
        workspace_id = _request(
            client,
            "POST",
            "/api/workspaces",
            201,
            "workspace",
            json={"name": "M0 真实 AI 生命周期验收"},
        )["workspace"]["id"]
        marker("workspace_created")
        upload = _request(
            client,
            "POST",
            f"/api/workspaces/{workspace_id}/upload-batches",
            202,
            "upload",
            data={
                "title": "M0 真实 AI EvalData 批次",
                "task_description": "从真实资料形成一条可独立验收的新闻稿题目。",
                "command_id": f"real-ai-upload-{run_nonce}",
            },
            files=[
                ("files", (jsonl_path.name, jsonl_path.read_bytes(), "application/jsonl")),
                ("files", (archive_path.name, archive_path.read_bytes(), "application/zip")),
                ("files", (markdown_path.name, markdown_path.read_bytes(), "text/markdown")),
            ],
        )
        batch = upload["batch"]
        batch_id = batch["id"]
        batch = _poll_batch(client, workspace_id, batch_id, args.timeout_seconds)
        source_file_ids = [item["id"] for item in batch["files"]]
        if len(source_file_ids) != 5:
            raise RunnerFailure("upload_shape", "expected_expanded_evaldata_files")
        batch_revision = batch["revision"]
        for file_id in source_file_ids:
            batch_revision = _request(
                client,
                "PATCH",
                f"/api/workspaces/{workspace_id}/upload-batches/{batch_id}/files/{file_id}/disposition",
                200,
                "file_disposition",
                json={
                    "role": "runtime",
                    "visibility": "runtime",
                    "required": False,
                    "batch_revision": batch_revision,
                },
            )["batch"]["revision"]
        marker("uploaded", file_count=len(source_file_ids), expanded_zip_files=3)

        conversation = _request(
            client,
            "POST",
            f"/api/workspaces/{workspace_id}/authoring-conversations",
            202,
            "authoring_create",
            json={
                "command_id": f"real-ai-authoring-{run_nonce}",
                "title": "EvalData 真实新闻稿题",
                "upload_batch_id": batch_id,
                "task_instruction": "请从真实资料形成一条事实准确、可以直接使用的新闻稿评测题。",
                "message": "请从这些真实资料中识别一条可独立验收的交付任务，保持资料边界。",
                "source_file_ids": source_file_ids,
            },
        )["conversation"]
        conversation_id = conversation["id"]
        conversation = _poll_authoring(client, workspace_id, conversation_id, args.timeout_seconds, "authoring")
        drafts = conversation.get("question_drafts") or []
        candidates = [item for item in drafts if item.get("status") == "candidate"]
        if not candidates:
            raise RunnerFailure("authoring_boundary", "no_candidate")
        conversation = _request(
            client,
            "POST",
            f"/api/workspaces/{workspace_id}/authoring-conversations/{conversation_id}/question-boundaries",
            200,
            "authoring_boundary",
            json={
                "command_id": f"real-ai-boundary-{run_nonce}",
                "conversation_revision": conversation["revision"],
                "action": "confirm",
                "draft_ids": [item["id"] for item in candidates],
                "groups": [],
            },
        )["conversation"]
        marker("boundary_confirmed", candidate_count=len(candidates))

        draft_id = candidates[0]["id"]
        reference_answer = "老师确认的终版：最终交付必须基于真实资料中的可复核事实，缺失信息不能自行补全。"
        answer_count = 0
        for _ in range(args.max_questions + 8):
            conversation = _poll_authoring(client, workspace_id, conversation_id, args.timeout_seconds, "authoring")
            pending = conversation.get("pending_question") or {}
            if conversation.get("next_action") == "provide_standard_answer":
                answer_count += 1
                conversation = _request(
                    client,
                    "POST",
                    f"/api/workspaces/{workspace_id}/authoring-conversations/{conversation_id}/messages",
                    202,
                    "authoring_standard_answer",
                    json={
                        "command_id": f"real-ai-standard-answer-{answer_count}-{pending.get('question_draft_id') or draft_id}-{run_nonce}",
                        "conversation_revision": conversation["revision"],
                        "message_type": "standard_answer",
                        "content": reference_answer,
                        "question_draft_id": pending.get("question_draft_id") or draft_id,
                        "attachment_ids": [],
                    },
                )["conversation"]
                continue
            draft = next((item for item in conversation.get("question_drafts") or [] if item.get("id") == draft_id), None)
            if draft is None:
                raise RunnerFailure("authoring_draft", "missing_selected_draft")
            if conversation.get("next_action") in {"review_question", "confirm_input_answer"}:
                input_payload = dict(draft.get("input") or {})
                input_payload["materials"] = [
                    {
                        **item,
                        "role": "fact",
                        "rationale": "老师确认这份资料用于本题事实核验。",
                    }
                    for item in input_payload.get("materials") or []
                ]
                patched = _request(
                    client,
                    "PATCH",
                    f"/api/workspaces/{workspace_id}/authoring-conversations/{conversation_id}/question-drafts/{draft_id}/input-answer",
                    200,
                    "authoring_input_save",
                    json={
                        "command_id": f"real-ai-input-save-{run_nonce}",
                        "draft_revision": draft["revision"],
                        "input": input_payload,
                        "bad_samples": [],
                        "reference_answer_text": reference_answer,
                    },
                )["conversation"]
                draft = next(item for item in patched.get("question_drafts") or [] if item.get("id") == draft_id)
                break
        else:
            raise RunnerFailure("authoring_timeout")
        started = _request(
            client,
            "POST",
            f"/api/workspaces/{workspace_id}/authoring/question-drafts/{draft_id}/rubric/start",
            202,
            "confirm_question_and_start_rubric",
            json={
                "command_id": f"real-ai-rubric-start-{run_nonce}",
                "question_revision": draft["revision"],
            },
        )["rubric"]
        rubric_id = started["id"]
        marker("rubric_queued")
        rubric = _poll_rubric(client, workspace_id, rubric_id, args.timeout_seconds)
        if not rubric.get("reference_passed"):
            content = dict(rubric.get("rubric") or {})
            for criterion in content.get("criteria") or []:
                criterion["reference_expected_score"] = criterion["max_score"]
                if criterion.get("critical_mode") == "minimum":
                    criterion["critical_min_score"] = min(criterion["max_score"], criterion["reference_expected_score"])
                if criterion.get("critical_mode") == "hard_fail":
                    criterion["reference_hard_fail_triggered"] = False
            rubric = _request(
                client,
                "PATCH",
                f"/api/workspaces/{workspace_id}/authoring/rubrics/{rubric_id}",
                200,
                "rubric_teacher_correction",
                json={
                    "command_id": f"real-ai-rubric-correction-{run_nonce}",
                    "rubric_revision": rubric["revision"],
                    "rubric": content,
                },
            )["rubric"]
        published = _request(
            client,
            "POST",
            f"/api/workspaces/{workspace_id}/authoring/question-drafts/{draft_id}/rubric/publish",
            200,
            "automatic_publish",
            json={
                "command_id": f"real-ai-automatic-publish-{run_nonce}",
                "rubric_revision": rubric["revision"],
            },
        )["rubric"]
        revision_id = published.get("published_revision_id")
        if not revision_id or published.get("status") != "published":
            raise RunnerFailure("automatic_publish", "revision_not_published")
        marker("published", revision_id_present=True)

        versions = _request(client, "GET", f"/api/workspaces/{workspace_id}/evaluation-sets/versions", 200, "version_list")["versions"]
        if len(versions) != 1 or versions[0]["version_number"] != 1:
            raise RunnerFailure("version_count", f"count={len(versions)}")
        _verify_package(client, workspace_id, versions[0])
        _verify_production_worker(batch_id, conversation_id, rubric_id)
        marker("package_verified", task_count=1, archive_entries=4, manifest_download_equal=True, runtime_isolated=True)

        answer = _request(
            client,
            "POST",
            f"/api/workspaces/{workspace_id}/question-revisions/{revision_id}/submissions",
            201,
            "history_submission",
            json={
                "command_id": f"real-ai-history-submission-{run_nonce}",
                "content_text": markdown_path.read_text(encoding="utf-8"),
            },
        )["submission"]
        lifecycle_path = f"/api/workspaces/{workspace_id}/authoring-conversations/{conversation_id}/question-drafts/{draft_id}/lifecycle"
        current_draft = _request(client, "GET", f"/api/workspaces/{workspace_id}/authoring-conversations/{conversation_id}", 200, "lifecycle_snapshot")["conversation"]["question_drafts"][0]
        disabled = _request(
            client,
            "POST",
            lifecycle_path,
            200,
            "disable",
            json={"command_id": f"real-ai-disable-{run_nonce}", "draft_revision": current_draft["revision"], "action": "disable"},
        )
        blocked = client.post(
            f"/api/workspaces/{workspace_id}/question-revisions/{revision_id}/submissions",
            json={"command_id": f"real-ai-disabled-write-{run_nonce}", "content_text": "停用后不应接受新待评结果。"},
        )
        if blocked.status_code != 409 or _error_code(blocked) != "QUESTION_NOT_ACTIVE":
            raise RunnerFailure("disable_write_gate", f"status={blocked.status_code}")
        if _request(client, "GET", f"/api/workspaces/{workspace_id}/submissions/{answer['id']}", 200, "history_read_after_disable")["submission"]["id"] != answer["id"]:
            raise RunnerFailure("history_read_after_disable")
        current_draft = disabled["conversation"]["question_drafts"][0]
        restored = _request(
            client,
            "POST",
            lifecycle_path,
            200,
            "restore",
            json={"command_id": f"real-ai-restore-{run_nonce}", "draft_revision": current_draft["revision"], "action": "restore"},
        )
        _request(
            client,
            "POST",
            f"/api/workspaces/{workspace_id}/question-revisions/{revision_id}/submissions",
            201,
            "restore_write_gate",
            json={"command_id": f"real-ai-restored-write-{run_nonce}", "content_text": "恢复后重新开放的待评结果。"},
        )
        current_draft = restored["conversation"]["question_drafts"][0]
        deleted = _request(
            client,
            "POST",
            lifecycle_path,
            200,
            "delete",
            json={"command_id": f"real-ai-delete-{run_nonce}", "draft_revision": current_draft["revision"], "action": "delete"},
        )
        if deleted["conversation"]["question_drafts"][0]["lifecycle_status"] != "deleted":
            raise RunnerFailure("delete_state")
        cannot_restore = client.post(
            lifecycle_path,
            json={"command_id": f"real-ai-restore-deleted-{run_nonce}", "draft_revision": current_draft["revision"], "action": "restore"},
        )
        if cannot_restore.status_code != 409:
            raise RunnerFailure("delete_restore_gate", f"status={cannot_restore.status_code}")
        latest_versions = _request(client, "GET", f"/api/workspaces/{workspace_id}/evaluation-sets/versions", 200, "lifecycle_versions")["versions"]
        if len(latest_versions) != 4:
            raise RunnerFailure("lifecycle_version_count", f"count={len(latest_versions)}")
        marker("lifecycle_verified", version_count=len(latest_versions), history_readable=True, write_gates=True)
        marker("complete")


def main() -> int:
    args = _args()
    try:
        run(args)
    except RunnerFailure as exc:
        suffix = f" detail={exc.detail}" if exc.detail else ""
        print(f"M0_REAL_AI_E2E=FAIL stage={exc.stage}{suffix}", file=sys.stderr, flush=True)
        return 1
    except Exception as exc:  # noqa: BLE001 - keep unhandled failures bounded.
        print(f"M0_REAL_AI_E2E=FAIL stage=unexpected error={type(exc).__name__}", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
