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


def _finish_cocreation(
    client: httpx.Client,
    workspace_id: str,
    package: dict,
    kind: str,
    prefix: str,
    timeout: float,
    max_questions: int,
    run_nonce: str,
) -> dict:
    package_id = package["id"]
    current = _request(
        client,
        "GET",
        f"/api/workspaces/{workspace_id}/task-packages/{package_id}",
        200,
        f"{prefix}_package",
    )["task_package"]
    started = _request(
        client,
        "POST",
        f"/api/workspaces/{workspace_id}/task-packages/{package_id}/co-creation",
        202,
        f"{prefix}_start",
        json={
            "command_id": f"{prefix}-start-{run_nonce}",
            "kind": kind,
            "task_package_revision": current["revision"],
        },
    )
    session_id = started["session"]["id"]
    questions = 0
    while True:
        session = _poll_session(client, workspace_id, session_id, prefix, timeout)
        if session["status"] == "ready_for_confirmation":
            break
        question = session.get("pending_question")
        if not isinstance(question, dict) or not question.get("id"):
            raise RunnerFailure(f"{prefix}_question", "missing_question")
        questions += 1
        if questions > max_questions:
            raise RunnerFailure(f"{prefix}_question_limit")
        answer = _request(
            client,
            "POST",
            f"/api/workspaces/{workspace_id}/co-creation/{session_id}/answers",
            202,
            f"{prefix}_answer",
            json={
                "command_id": f"{prefix}-answer-{questions}-{run_nonce}",
                "question_id": question["id"],
                "answer": "老师确认：以真实任务目标为边界，关键事实必须可回查，结果达到可直接使用的最低质量线。",
                "business_revision": session["business_revision"],
            },
        )
        if not answer.get("session"):
            raise RunnerFailure(f"{prefix}_answer", "missing_session")
        saved = _request(
            client,
            "GET",
            f"/api/workspaces/{workspace_id}/co-creation/{session_id}",
            200,
            f"{prefix}_answer_saved",
        )["session"]
        turns = saved.get("turns") or []
        if not turns or not turns[-1].get("answer"):
            raise RunnerFailure(f"{prefix}_answer_saved", "answer_missing")
        if questions == 1:
            duplicate = _request(
                client,
                "POST",
                f"/api/workspaces/{workspace_id}/co-creation/{session_id}/answers",
                202,
                f"{prefix}_answer_idempotency",
                json={
                    "command_id": f"{prefix}-answer-{questions}-{run_nonce}",
                    "question_id": question["id"],
                    "answer": "老师确认：以真实任务目标为边界，关键事实必须可回查，结果达到可直接使用的最低质量线。",
                    "business_revision": session["business_revision"],
                },
            )
            duplicate_turns = (duplicate.get("session") or {}).get("turns") or []
            if len(duplicate_turns) != len(turns):
                raise RunnerFailure(f"{prefix}_answer_idempotency", "duplicate_turn")
            marker(f"{prefix}_answer_idempotency", turn_count=len(turns))
        marker(f"{prefix}_answer_saved", questions=questions, turn_count=len(turns))
    confirmation_path = "contract-confirmation" if kind == "scenario_contract" else "judgment-confirmation"
    confirmed = _request(
        client,
        "POST",
        f"/api/workspaces/{workspace_id}/co-creation/{session_id}/{confirmation_path}",
        200,
        f"{prefix}_confirm",
        json={"command_id": f"{prefix}-confirm-{run_nonce}", "business_revision": session["business_revision"]},
    )["session"]
    if confirmed["status"] != "confirmed":
        raise RunnerFailure(f"{prefix}_confirm", confirmed["status"])
    marker(f"{prefix}_complete", questions=questions)
    return confirmed


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
        if len(runtime.get("tasks", [])) != 2:
            raise RunnerFailure("runtime_tasks")
        for task in runtime["tasks"]:
            if set(task) != {"task_id", "title", "brief", "input_files"}:
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
        ):
            if term in runtime_text:
                raise RunnerFailure("runtime_leakage", term)


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
            json={"name": "M0 真实 AI 验收"},
        )["workspace"]["id"]
        marker("workspace_created")
        upload = _request(
            client,
            "POST",
            f"/api/workspaces/{workspace_id}/upload-batches",
            202,
            "upload",
            data={
                "title": "M0 真实 AI 验收批次",
                "task_description": "形成主观新闻稿评测题",
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
        files = {item["original_name"]: item["id"] for item in batch["files"]}
        jsonl_id = files.get(jsonl_path.name)
        markdown_id = files.get(markdown_path.name)
        zip_ids = [file_id for file_id in files.values() if file_id not in {jsonl_id, markdown_id}]
        if not jsonl_id or not markdown_id or len(zip_ids) != 3:
            raise RunnerFailure("upload_shape")
        marker("uploaded", file_count=len(files), expanded_zip_files=len(zip_ids))
        batch = _poll_batch(client, workspace_id, batch_id, args.timeout_seconds)
        revision = batch["revision"]
        conversation_ids: list[str] = []
        runtime_ids: list[str] = []
        for name, file_id in files.items():
            if file_id == jsonl_id:
                role, visibility, required = "provenance", "provenance", False
            elif file_id == markdown_id:
                role, visibility, required = "brief", "runtime", True
            elif "对话上下文" in name or "conversation" in name.casefold():
                role, visibility, required = "provenance", "provenance", False
                conversation_ids.append(file_id)
            else:
                role, visibility, required = "runtime", "runtime", True
                runtime_ids.append(file_id)
            revision = _request(
                client,
                "PATCH",
                f"/api/workspaces/{workspace_id}/upload-batches/{batch_id}/files/{file_id}/disposition",
                200,
                "file_disposition",
                json={"role": role, "visibility": visibility, "required": required, "batch_revision": revision},
            )["batch"]["revision"]
        if len(conversation_ids) != 1 or len(runtime_ids) != 2:
            raise RunnerFailure("sample_role_classification")
        marker("roles_confirmed", file_count=len(files))
        groups = [
            {
                "title": "理想汽车供稿任务",
                "summary": "对话上下文和原始事件流共同描述一个真实任务。",
                "evidence_file_ids": [markdown_id, jsonl_id],
                "attempts": [
                    {"attempt_key": "financial-draft-1", "label": "原始对话上下文", "evidence_file_ids": [markdown_id, jsonl_id]},
                    {"attempt_key": "financial-draft-2", "label": "事件流修订证据", "evidence_file_ids": [markdown_id, jsonl_id]},
                ],
            },
            {
                "title": "MEGA 新闻稿任务",
                "summary": "讲稿、拍摄指引和对话导出共同描述一个真实任务。",
                "evidence_file_ids": [*runtime_ids, *conversation_ids],
                "attempts": [
                    {"attempt_key": "mega-revision-2", "label": "更新材料与多轮反馈", "evidence_file_ids": [*runtime_ids, *conversation_ids]},
                ],
            },
        ]
        grouped = _request(
            client,
            "POST",
            f"/api/workspaces/{workspace_id}/upload-batches/{batch_id}/task-groups/confirmation",
            200,
            "task_grouping",
            json={"command_id": f"real-ai-grouping-{run_nonce}", "batch_revision": revision, "groups": groups},
        )
        packages = grouped["task_packages"]
        if len(packages) != 2 or sorted(len(item["attempts"]) for item in packages) != [1, 2]:
            raise RunnerFailure("task_grouping_shape")
        repeated = _request(
            client,
            "POST",
            f"/api/workspaces/{workspace_id}/upload-batches/{batch_id}/task-groups/confirmation",
            200,
            "task_grouping_idempotency",
            json={"command_id": f"real-ai-grouping-{run_nonce}", "batch_revision": revision, "groups": groups},
        )
        if [item["id"] for item in repeated["task_packages"]] != [item["id"] for item in packages]:
            raise RunnerFailure("task_grouping_idempotency")
        marker("tasks_confirmed", task_count=2, attempt_count=sum(len(item["attempts"]) for item in packages))
        by_title = {item["title"]: item for item in packages}
        _finish_cocreation(
            client,
            workspace_id,
            by_title["理想汽车供稿任务"],
            "scenario_contract",
            "contract",
            args.timeout_seconds,
            args.max_questions,
            run_nonce,
        )
        packages = _request(client, "GET", f"/api/workspaces/{workspace_id}/task-packages", 200, "contract_propagation")["task_packages"]
        packages = [item for item in packages if item.get("status") == "confirmed"]
        if len(packages) != 2 or any(not item.get("has_contract") for item in packages):
            raise RunnerFailure("contract_propagation")
        by_title = {item["title"]: item for item in packages}
        _finish_cocreation(
            client,
            workspace_id,
            by_title["理想汽车供稿任务"],
            "task_judgment",
            "supply-judgment",
            args.timeout_seconds,
            args.max_questions,
            run_nonce,
        )
        _finish_cocreation(
            client,
            workspace_id,
            by_title["MEGA 新闻稿任务"],
            "task_judgment",
            "mega-judgment",
            args.timeout_seconds,
            args.max_questions,
            run_nonce,
        )
        marker("cocreation_confirmed", task_count=2)
        packages = _request(client, "GET", f"/api/workspaces/{workspace_id}/task-packages", 200, "packages_refresh")["task_packages"]
        draft = _request(client, "POST", f"/api/workspaces/{workspace_id}/evaluation-sets/drafts", 201, "draft_create", json={"command_id": f"real-ai-draft-{run_nonce}"})["draft"]
        for index, package in enumerate(packages):
            current = _request(client, "GET", f"/api/workspaces/{workspace_id}/task-packages/{package['id']}", 200, "package_refresh")["task_package"]
            draft = _request(client, "POST", f"/api/workspaces/{workspace_id}/evaluation-sets/drafts/{draft['id']}/members", 200, "draft_include", json={"command_id": f"real-ai-include-{index}-{run_nonce}", "draft_revision": draft["revision"], "task_package_id": current["id"], "task_package_revision": current["revision"], "action": "include"})["draft"]
        _request(client, "POST", f"/api/workspaces/{workspace_id}/evaluation-sets/drafts/{draft['id']}/coverage-review", 202, "coverage_enqueue", json={"command_id": f"real-ai-coverage-{run_nonce}", "draft_revision": draft["revision"]})
        deadline = time.monotonic() + args.timeout_seconds
        previous = None
        while time.monotonic() < deadline:
            draft = _request(client, "GET", f"/api/workspaces/{workspace_id}/evaluation-sets/drafts/{draft['id']}", 200, "draft_poll")["draft"]
            action = draft["next_action"]
            if action != previous:
                marker("draft_action", action=action)
                previous = action
            if action in {"freeze", "confirm_coverage_risk"}:
                break
            if action == "retry_processing":
                raise RunnerFailure("coverage_review")
            time.sleep(2)
        else:
            raise RunnerFailure("draft_timeout")
        if draft["next_action"] == "confirm_coverage_risk":
            draft = _request(client, "POST", f"/api/workspaces/{workspace_id}/evaluation-sets/drafts/{draft['id']}/coverage-confirmation", 200, "coverage_confirmation", json={"command_id": f"real-ai-risk-confirm-{run_nonce}", "draft_revision": draft["revision"], "confirmed": True, "note": "老师明确接受当前 M0 覆盖风险，后续继续补充反例。"})["draft"]
        if draft["next_action"] != "freeze":
            raise RunnerFailure("freeze_ready")
        _request(client, "POST", f"/api/workspaces/{workspace_id}/evaluation-sets/drafts/{draft['id']}/freeze", 202, "freeze_enqueue", json={"command_id": f"real-ai-freeze-{run_nonce}", "draft_revision": draft["revision"]})
        marker("freeze_queued")
        deadline = time.monotonic() + args.timeout_seconds
        while time.monotonic() < deadline:
            versions = _request(client, "GET", f"/api/workspaces/{workspace_id}/evaluation-sets/versions", 200, "version_poll")
            if versions["versions"]:
                break
            time.sleep(2)
        else:
            raise RunnerFailure("freeze_timeout")
        if len(versions["versions"]) != 1 or versions["versions"][0]["version_number"] != 1:
            raise RunnerFailure("version_count")
        _verify_package(client, workspace_id, versions["versions"][0])
        marker("package_verified", task_count=2, archive_entries=4, manifest_download_equal=True, runtime_isolated=True)
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
