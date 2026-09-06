"""Real-API acceptance for the ai-eval-push skill using the C1 real samples.

One-shot replacement of the old EvalData-layout acceptance: the ZIP-required
directory walk, the first-800-character truncation, the placeholder answer
fallback and the script-authored fake bad cases are all removed. The batch now
comes from the hash-gated C1 rebuild of the real session corpora, runs against
an ISOLATED PostgreSQL business+checkpoint pair with the production worker and
the real provider, and is validated against the COMPLETE criterion contract.

The skill client copy in the repository keeps its placeholders; this script
binds a scratch copy only (never the repo file, never environment injection).

Required environment:
    ACCEPT_BUSINESS_DSN=postgresql+psycopg://...@127.0.0.1:5432/skill_eval_c3_accept
    ACCEPT_CHECKPOINT_DSN=postgresql://...@127.0.0.1:5432/skill_eval_c3_accept_ckpt

Usage:
    cd backend && uv run python -m scripts.accept_skill_push \
        --corpus-root /Users/hsikey/Company/skill-eval-platform/.local-samples/m0
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
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

SKILL_CLIENT = (
    Path(__file__).resolve().parents[2] / "skills" / "ai-eval-push" / "scripts" / "push_eval_cases.py"
)
FORBIDDEN_DB_NAMES = {"skill_eval", "skill_eval_checkpoint", "postgres", "template1"}


def _fail(stage: str, message: str) -> None:
    print(f"ACCEPT_SKILL=FAIL stage={stage} message={message}")
    raise SystemExit(1)


def _check_isolated_dsn(value: str, label: str) -> str:
    raw = value.replace("postgresql+psycopg://", "postgresql://")
    db_name = (urlsplit(raw).path or "/").lstrip("/").split("?")[0]
    if not db_name:
        _fail("config", f"{label} 缺少库名")
    if db_name in FORBIDDEN_DB_NAMES:
        _fail("config", f"{label} 指向受保护库 {db_name}，拒绝执行")
    return value


def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def _start_server() -> tuple[str, object]:
    import uvicorn

    from app.main import app

    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{port}"
    for _ in range(200):
        try:
            with urllib.request.urlopen(f"{base_url}/healthz", timeout=1) as resp:
                if resp.status == 200:
                    return base_url, server
        except Exception:
            time.sleep(0.1)
    _fail("server", "isolated API did not start")
    raise AssertionError


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
        timeout=180,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--corpus-root",
        default="/Users/hsikey/Company/skill-eval-platform/.local-samples/m0",
    )
    parser.add_argument("--out", default="storage/acceptance/m0-accept-skill-push")
    args = parser.parse_args()

    business_dsn = os.environ.get("ACCEPT_BUSINESS_DSN", "")
    checkpoint_dsn = os.environ.get("ACCEPT_CHECKPOINT_DSN", "")
    if not business_dsn or not checkpoint_dsn:
        _fail("config", "必须显式提供 ACCEPT_BUSINESS_DSN 与 ACCEPT_CHECKPOINT_DSN（隔离验收库）")
    _check_isolated_dsn(business_dsn, "ACCEPT_BUSINESS_DSN")
    _check_isolated_dsn(checkpoint_dsn, "ACCEPT_CHECKPOINT_DSN")

    checkpoint_plain = checkpoint_dsn.replace("postgresql+psycopg://", "postgresql://")
    business_sqla = business_dsn if "+" in business_dsn.split("://")[0] else (
        "postgresql+psycopg://" + business_dsn.split("://", 1)[1]
    )
    os.environ["DATABASE_URL"] = business_sqla
    os.environ["CHECKPOINT_DATABASE_URL"] = checkpoint_plain
    os.environ["AI_RUNTIME_MODE"] = "production"
    os.environ["DATABASE_SCHEMA_CHECK_ON_STARTUP"] = "false"
    os.environ["SESSION_COOKIE_SECURE"] = "false"

    from alembic import command
    from alembic.config import Config

    os.environ["ALEMBIC_DATABASE_URL"] = business_sqla
    alembic_cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    command.upgrade(alembic_cfg, "head")
    print("ACCEPT_SKILL_STAGE=migrated")

    import psycopg
    from pydantic import SecretStr

    from app.lib.ai_runtime import deep_runtime
    from app.lib.settings import settings

    class _Cfg:
        checkpoint_database_url = SecretStr(checkpoint_plain)
        langgraph_aes_key = settings.langgraph_aes_key

    with psycopg.connect(checkpoint_plain, autocommit=True) as conn:
        deep_runtime.build_saver(conn, _Cfg()).setup()
    print("ACCEPT_SKILL_STAGE=checkpoint_ready")

    # Real samples only: hash-gated C1 rebuild, no fabricated fallbacks.
    from scripts import m0_samples

    out_dir = Path(args.out)
    m0_samples.run_extraction(Path(args.corpus_root), out_dir / "samples", "accept-skill-push")
    batch = json.loads((out_dir / "samples" / "batch.json").read_text(encoding="utf-8"))
    if len(batch["cases"]) < 2:
        _fail("samples", "重建批次案例不足两组")
    batch["command_id"] = f"accept-skill-{int(time.time())}"
    batch_path = out_dir / "push-batch.json"
    out_dir.mkdir(parents=True, exist_ok=True)
    batch_path.write_text(json.dumps(batch, ensure_ascii=False), encoding="utf-8")
    print(f"ACCEPT_SKILL_STAGE=samples cases={len(batch['cases'])}")

    from app.features.auth import service as auth_service
    from app.features.auth.schemas import RegisterRequest
    from app.features.scenes import service as scene_service
    from app.features.scenes.schemas import SceneCreateRequest

    class _NoopResponse:
        def set_cookie(self, *a, **k):
            pass

        def delete_cookie(self, *a, **k):
            pass

    auth_service.register(
        RegisterRequest(username="admin", password="accept-skill-password-1"), _NoopResponse()
    )
    scene = scene_service.create_scene(SceneCreateRequest(name="技能推送验收场景"))
    issued = scene_service.create_or_replace_credential(scene.id, label="skill-push")
    token = issued.token
    print(f"ACCEPT_SKILL_STAGE=scene scene_id={scene.id}")

    base_url, server = _start_server()
    print(f"ACCEPT_SKILL_STAGE=server base_url={base_url}")

    validate = _run_client(["validate", "--batch-file", str(batch_path)], base_url, token)
    if validate.returncode != 0:
        print(f"ACCEPT_SKILL=FAIL stage=validate\n{validate.stderr[:400]}")
        return 1
    print("ACCEPT_SKILL_STAGE=client_validate ok")

    push = _run_client(["push", "--batch-file", str(batch_path)], base_url, token)
    if push.returncode != 0:
        print(f"ACCEPT_SKILL=FAIL stage=push\n{push.stderr[:400]}")
        return 1
    question_ids = [
        line.split("question_id=")[1].split()[0]
        for line in push.stdout.splitlines()
        if "question_id=" in line
    ]
    print(f"ACCEPT_SKILL_STAGE=pushed questions={len(question_ids)}")
    # The client must not leak the token or material bodies.
    if token in push.stdout or token in push.stderr:
        _fail("leak", "技能客户端输出泄露凭证")

    # Run the production worker (real AI) until generation settles.
    from app.features.question_library import deletion, rubric_generation
    from app.lib.operations.worker import OperationWorker

    def run_until_settled(max_minutes: float = 40.0) -> None:
        worker = OperationWorker(runtime_mode="production")
        worker.register("rubric_generation", rubric_generation.process_rubric_generation)
        worker.register("question_cleanup", deletion.process_question_cleanup)
        deadline = time.monotonic() + max_minutes * 60
        while time.monotonic() < deadline:
            busy = False
            for _ in range(50):
                if worker.run_once():
                    busy = True
                else:
                    break
            if not busy:
                statuses = []
                for question_id in question_ids:
                    statuses.append(_question_status(base_url, question_id))
                if all(s in ("pending_review", "published") for s in statuses):
                    return
                if any(s == "generation_failed" for s in statuses):
                    _fail("generation", f"生成失败：{statuses}")
            time.sleep(1.0)
        _fail("generation", "生成未在期限内完成")

    def _question_status(base: str, question_id: str) -> str:
        import http.cookiejar

        jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        login = json.dumps(
            {"identifier": "admin", "password": "accept-skill-password-1"}
        ).encode()
        req = urllib.request.Request(
            f"{base}/api/auth/login", data=login, method="POST",
            headers={"Content-Type": "application/json"},
        )
        opener.open(req, timeout=10)
        with opener.open(f"{base}/api/questions/{question_id}", timeout=10) as resp:
            return str(json.loads(resp.read().decode())["status"])

    run_until_settled()
    print("ACCEPT_SKILL_STAGE=worker_settled")

    # Read back through the admin API and verify the COMPLETE contract.
    import http.cookiejar

    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    login = json.dumps(
        {"identifier": "admin", "password": "accept-skill-password-1"}
    ).encode()
    req = urllib.request.Request(
        f"{base_url}/api/auth/login", data=login, method="POST",
        headers={"Content-Type": "application/json"},
    )
    opener.open(req, timeout=10)

    for question_id in question_ids:
        with opener.open(f"{base_url}/api/questions/{question_id}", timeout=10) as resp:
            detail: dict[str, Any] = json.loads(resp.read().decode())
        criteria = detail.get("criteria") or []
        if detail["status"] not in ("pending_review", "published"):
            _fail("generation", f"题目 {question_id} 状态异常：{detail['status']}")
        if not criteria:
            _fail("contract", f"题目 {question_id} 无维度")
        for item in criteria:
            scores = [a["score"] for a in item["score_anchors"]]
            if item["pass_score"] not in scores:
                _fail("contract", "建议分缺少锚点描述")
            if item["pass_score_basis"]["explained_score"] != item["pass_score"]:
                _fail("contract", "通过分依据解释分数不一致")
            for key in ("criterion_basis", "pass_score_basis"):
                if not item[key]["claims"]:
                    _fail("contract", f"{key} 缺少主张")
        print(
            f"ACCEPT_SKILL_STAGE=question id={question_id} status={detail['status']} "
            f"criteria={len(criteria)} revision={detail['content_revision']}"
        )

    server.should_exit = True  # type: ignore[attr-defined]
    batch_path.unlink(missing_ok=True)
    print("ACCEPT_SKILL=OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
