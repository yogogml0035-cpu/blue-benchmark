"""Real-API acceptance for the ai-eval-push skill using EvalData.

Simulates a local agent that has finished real work (the EvalData conversation)
and now distills evaluation questions from the materials it actually read:
the Markdown export, the raw JSONL, and the ZIP contents. It builds a
multi-question batch, uploads it through the skill's deterministic client
against a real HTTP API, runs the production worker (real AI) for rubric
generation, then reads the questions back through the admin API.

Output is limited to stage markers, counts, ids and statuses — never material
bodies, memory text, or credentials.

Usage:
    cd backend && uv run python -m scripts.accept_skill_push_evaldata \
        --evaldata-dir /Users/hsikey/BenchMark/EvalData
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

SKILL_CLIENT = (
    Path(__file__).resolve().parents[2] / "skills" / "ai-eval-push" / "scripts" / "push_eval_cases.py"
)
MAX_EXCERPT = 800


def _excerpt(text: str, limit: int = MAX_EXCERPT) -> str:
    text = text.strip()
    return text[:limit]


def _configure_environment() -> Path:
    root = Path(tempfile.mkdtemp(prefix="accept-skill-evaldata-"))
    os.environ["DATABASE_URL"] = f"sqlite:///{root / 'business.db'}"
    os.environ["AI_RUNTIME_MODE"] = "production"
    os.environ["DATABASE_SCHEMA_CHECK_ON_STARTUP"] = "false"
    return root


def _start_server() -> tuple[str, object]:
    import uvicorn

    from app.main import app

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            with urllib.request.urlopen(f"{base_url}/healthz", timeout=1) as resp:
                if resp.status == 200:
                    return base_url, server
        except Exception:
            time.sleep(0.1)
    raise RuntimeError("server did not start")


def _extract_evaldata(evaldata_dir: Path) -> dict:
    """Read the MD export, JSONL turns and ZIP docs the agent 'actually read'."""

    md_files = sorted(evaldata_dir.glob("*.md"))
    jsonl_files = sorted(evaldata_dir.glob("*.jsonl"))
    zip_files = sorted(evaldata_dir.glob("*.zip"))
    if not (md_files and jsonl_files and zip_files):
        raise SystemExit("evaldata-dir must contain one .md, one .jsonl and one .zip")

    result = {"user_feedbacks": [], "final_answer": None, "zip_docs": []}

    # JSONL: real user feedback turns and the teacher's final approved answer.
    with open(jsonl_files[0], encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") != "user":
                continue
            content = event.get("message", {}).get("content")
            blocks = content if isinstance(content, list) else []
            for block in blocks:
                if isinstance(block, dict) and block.get("type") == "text":
                    text = block.get("text", "").strip()
                    if not text or text.startswith("Base directory"):
                        continue
                    if "终版媒体供稿" in text and result["final_answer"] is None:
                        result["final_answer"] = _excerpt(text)
                    elif len(text) > 40 and "[Request interrupted" not in text:
                        result["user_feedbacks"].append(_excerpt(text))

    # ZIP: reference documents actually read by the agent.
    with zipfile.ZipFile(zip_files[0]) as archive:
        for name in archive.namelist():
            if name.endswith(".md") and "完整导出" not in name:
                body = archive.read(name).decode("utf-8", errors="replace")
                result["zip_docs"].append({"name": name, "text": _excerpt(body)})

    # MD export: confirm readable (source of truth for the conversation).
    result["md_size"] = md_files[0].stat().st_size
    return result


def _build_batch(extracted: dict) -> dict:
    """Organize two questions from the extracted materials.

    Deliberately excludes host paths and tool metadata: only the teacher-visible
    business text is used. Memory fragments are raw, relevant, non-secret.
    """

    feedbacks = extracted["user_feedbacks"]
    zip_docs = extracted["zip_docs"]
    final_answer = extracted["final_answer"] or "老师认可的终版供稿。"

    case_1 = {
        "client_case_id": "evaldata-case-1",
        "title": "财报媒体供稿成稿",
        "task_prompt": "请把理想汽车二季度财报要点改写成一篇可立即发布的媒体供稿，突出交付、营收与毛利率，并形成清晰叙事主线。",
        "reference_examples": [
            {
                "client_ref_id": "ref-final-draft",
                "source_name": "终版媒体供稿",
                "content_text": final_answer,
            }
        ],
        "bad_cases": [],
        "reference_answer": final_answer,
        "memory_materials": [
            {
                "client_ref_id": "mem-style",
                "source_label": "业务记忆",
                "content_text": "媒体供稿先给结论再给数据支撑，避免只罗列数字。",
            }
        ],
    }
    if feedbacks:
        case_1["bad_cases"].append(
            {
                "content_text": "初稿只罗列财报数字，缺少叙事主线。",
                "teacher_feedback_texts": [feedbacks[0]],
                "reason_summary": "缺少可发布的叙事结构。",
            }
        )

    case_2 = {
        "client_case_id": "evaldata-case-2",
        "title": "素材讲稿要点整理",
        "task_prompt": "请把提供的讲稿素材整理成结构清晰的要点提纲，保留关键事实。",
        "reference_examples": [
            {
                "client_ref_id": "ref-zip-doc",
                "source_name": (zip_docs[0]["name"] if zip_docs else "讲稿素材"),
                "content_text": (zip_docs[0]["text"] if zip_docs else "讲稿素材正文。"),
            }
        ],
        "bad_cases": [],
        "reference_answer": (zip_docs[0]["text"] if zip_docs else "整理后的要点提纲。"),
        "memory_materials": [],
    }

    return {"schema_version": "1.0", "cases": [case_1, case_2]}


def _run_client(args: list[str], base_url: str, token: str) -> subprocess.CompletedProcess:
    # Bind a scratch copy of the skill client and run it; the repository copy
    # must keep its placeholders, so never bind it in place.
    source = SKILL_CLIENT.read_text(encoding="utf-8")
    bound = source.replace('BASE_URL = "***"', f'BASE_URL = "{base_url}"').replace(
        'ACCESS_TOKEN = "sep_***"', f'ACCESS_TOKEN = "{token}"'
    )
    if bound == source:
        raise RuntimeError("failed to bind scratch copy of the skill client")
    scratch = Path(tempfile.mkdtemp(prefix="accept-skill-client-")) / "push_eval_cases.py"
    scratch.write_text(bound, encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(scratch), *args],
        capture_output=True,
        text=True,
        timeout=120,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evaldata-dir", default="/Users/hsikey/BenchMark/EvalData")
    args = parser.parse_args()
    evaldata_dir = Path(args.evaldata_dir)

    _configure_environment()
    # Apply migrations to the scratch DB before the app's schema check runs.
    from alembic import command
    from alembic.config import Config

    os.environ["ALEMBIC_DATABASE_URL"] = os.environ["DATABASE_URL"]
    alembic_cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    command.upgrade(alembic_cfg, "head")

    from app.features.auth import service as auth_service
    from app.features.auth.schemas import RegisterRequest
    from app.features.scenes import service as scene_service
    from app.features.scenes.schemas import SceneCreateRequest

    class _NoopResponse:
        def set_cookie(self, *a, **k):
            pass

        def delete_cookie(self, *a, **k):
            pass

    print("ACCEPT_SKILL_STAGE=extract")
    extracted = _extract_evaldata(evaldata_dir)
    print(
        f"ACCEPT_SKILL_STAGE=extract md_bytes={extracted['md_size']} "
        f"feedbacks={len(extracted['user_feedbacks'])} zip_docs={len(extracted['zip_docs'])} "
        f"final_answer={'yes' if extracted['final_answer'] else 'no'}"
    )

    auth_service.register(
        RegisterRequest(username="admin", password="admin-password-1"), _NoopResponse()
    )
    scene = scene_service.create_scene(SceneCreateRequest(name="EvalData场景"))
    issued = scene_service.create_or_replace_credential(scene.id, label="evaldata")
    token = issued.token
    print(f"ACCEPT_SKILL_STAGE=scene scene_id={scene.id} credential_id={issued.credential_id}")

    base_url, server = _start_server()
    print(f"ACCEPT_SKILL_STAGE=server base_url={base_url}")

    batch = _build_batch(extracted)
    batch_path = Path(tempfile.gettempdir()) / f"evaldata-batch-{os.getpid()}.json"
    batch_path.write_text(json.dumps(batch, ensure_ascii=False), encoding="utf-8")

    validate = _run_client(["validate", "--batch-file", str(batch_path)], base_url, token)
    if validate.returncode != 0:
        print(f"ACCEPT_SKILL=FAIL stage=validate\n{validate.stderr}")
        return 1
    print("ACCEPT_SKILL_STAGE=client_validate ok")

    push = _run_client(["push", "--batch-file", str(batch_path)], base_url, token)
    if push.returncode != 0:
        print(f"ACCEPT_SKILL=FAIL stage=push\n{push.stderr}")
        return 1
    question_ids = [
        line.split("question_id=")[1].split()[0]
        for line in push.stdout.splitlines()
        if "question_id=" in line
    ]
    print(f"ACCEPT_SKILL_STAGE=pushed questions={len(question_ids)}")
    # The client must not leak the token or material bodies.
    if token in push.stdout or token in push.stderr:
        print("ACCEPT_SKILL=FAIL stage=leak what=token")
        return 1

    # Run the production worker (real AI) until generation settles.
    from app.lib.operations.worker import production_worker

    with production_worker() as worker:
        rounds = 0
        while worker.run_once():
            rounds += 1
            if rounds > 50:
                print("ACCEPT_SKILL=FAIL stage=worker message=not-idle")
                return 1
    print(f"ACCEPT_SKILL_STAGE=worker rounds={rounds}")

    # Read back through the admin API and verify per-question consistency.
    import http.cookiejar

    cookie_jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))
    login = json.dumps({"identifier": "admin", "password": "admin-password-1"}).encode()
    req = urllib.request.Request(
        f"{base_url}/api/auth/login", data=login, method="POST",
        headers={"Content-Type": "application/json"},
    )
    opener.open(req, timeout=10)

    statuses = []
    for question_id in question_ids:
        with opener.open(f"{base_url}/api/questions/{question_id}", timeout=10) as resp:
            detail = json.loads(resp.read().decode())
        criteria = detail.get("criteria") or []
        statuses.append(detail["status"])
        print(
            f"ACCEPT_SKILL_STAGE=question id={question_id} status={detail['status']} "
            f"criteria={len(criteria)} revision={detail['content_revision']}"
        )

    if not all(status in ("pending_review", "published") for status in statuses):
        print(f"ACCEPT_SKILL=FAIL stage=generation statuses={statuses}")
        return 1

    server.should_exit = True
    batch_path.unlink(missing_ok=True)
    print("ACCEPT_SKILL=OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
