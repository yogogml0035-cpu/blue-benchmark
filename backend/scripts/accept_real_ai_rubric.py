"""Real-AI acceptance: C1 real samples -> isolated PostgreSQL -> production
worker -> complete contract -> recovery -> publish -> complete deletion.

One-shot replacement of the old SQLite/single-call/two-field acceptance: this
entry FAILS LOUDLY when the real corpus, an isolated PostgreSQL target or the
real provider is unavailable — it never falls back to SQLite, fake mode,
placeholder samples or truncated materials.

Flow (both C1 case groups by default):

1. rebuild the C1 fixtures from the read-only corpus (hash-gated);
2. upload the FULL real cases through the external HTTP API;
3. run the production worker with the real provider on the deep runtime:
   the recovery case first fails under a 1-model-call budget (real
   checkpoints written), then a retry RESUMES the same thread without
   re-appending the initial input;
4. assert the complete contract: anchors contain the suggested score, bases
   classify claims, every citation quotes the question's own materials;
5. assert the persisted public event log contains real deltas/tools and ends
   with the authoritative run_completed;
6. teacher edits: save an unanchored integer (5), publish, reopen;
7. accepted deletion drives cross-store cleanup; assert ZERO residue in the
   business tables AND the checkpoint tables, sibling untouched.

Required environment (isolated, task-exclusive targets — the project
databases blue_benchmark / blue_benchmark_checkpoint are REFUSED by name):

    ACCEPT_BUSINESS_DSN=postgresql+psycopg://...@127.0.0.1:5432/blue_benchmark_c3_accept
    ACCEPT_CHECKPOINT_DSN=postgresql://...@127.0.0.1:5432/blue_benchmark_c3_accept_ckpt

Usage:
    cd backend && uv run python -m scripts.accept_real_ai_rubric \
        --corpus-root <repo-root>/.local-samples/m0
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

FORBIDDEN_DB_NAMES = {"blue_benchmark", "blue_benchmark_checkpoint", "postgres", "template1"}


def _fail(stage: str, message: str) -> None:
    print(f"ACCEPT_REAL_AI=FAIL stage={stage} message={message}")
    raise SystemExit(1)


def _check_isolated_dsn(value: str, label: str) -> None:
    from urllib.parse import urlsplit

    raw = value.replace("postgresql+psycopg://", "postgresql://")
    parts = urlsplit(raw)
    db_name = (parts.path or "/").lstrip("/").split("?")[0]
    if not db_name:
        _fail("config", f"{label} 缺少库名")
    if db_name in FORBIDDEN_DB_NAMES:
        _fail("config", f"{label} 指向受保护库 {db_name}，拒绝执行")


def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def _start_server() -> str:
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
                    return base_url
        except Exception:
            time.sleep(0.1)
    _fail("server", "isolated API did not start")
    raise AssertionError


def _http_json(url: str, *, method: str = "GET", payload: Any = None,
               headers: dict[str, str] | None = None, opener=None) -> tuple[int, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    do = opener.open if opener is not None else urllib.request.urlopen
    try:
        with do(req, timeout=120) as resp:
            body = resp.read().decode()
            return resp.status, (json.loads(body) if body else None)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode()
        try:
            return exc.code, json.loads(body)
        except Exception:
            return exc.code, {"raw": body[:200]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--corpus-root",
        default=str(Path(__file__).resolve().parents[2] / ".local-samples" / "m0"),
    )
    parser.add_argument("--out", default="storage/acceptance/m0-accept-real-ai")
    parser.add_argument(
        "--cases", default="m0-real-f-financial-report,m0-real-m-mega-press-release"
    )
    parser.add_argument("--recovery-case", default="m0-real-f-financial-report")
    parser.add_argument("--max-minutes-per-case", type=float, default=25.0)
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
    os.environ["ADMIN_USERNAME"] = "admin"
    os.environ["ADMIN_PASSWORD"] = "accept-real-ai-password-1"

    # Migrate the isolated business database (explicit step, never on startup).
    from alembic import command
    from alembic.config import Config

    os.environ["ALEMBIC_DATABASE_URL"] = business_sqla
    alembic_cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    command.upgrade(alembic_cfg, "head")
    print("ACCEPT_REAL_AI_STAGE=migrated")

    # Rebuild the C1 fixtures (hash-gated; fails loudly without the corpus).
    from scripts import m0_samples

    out_dir = Path(args.out)
    m0_samples.run_extraction(Path(args.corpus_root), out_dir / "samples", "accept-real-ai")
    batch = json.loads((out_dir / "samples" / "batch.json").read_text(encoding="utf-8"))
    wanted = [c.strip() for c in args.cases.split(",") if c.strip()]
    cases = [c for c in batch["cases"] if c["client_case_id"] in wanted]
    if len(cases) != len(wanted):
        _fail("samples", f"重建批次缺少案例：{wanted}")
    print(f"ACCEPT_REAL_AI_STAGE=samples cases={len(cases)}")

    import http.cookiejar

    import psycopg
    from pydantic import SecretStr

    from app.lib.settings import settings

    with psycopg.connect(checkpoint_plain, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT current_database()")
            ckpt_db = cur.fetchone()[0]
    if ckpt_db in FORBIDDEN_DB_NAMES:
        _fail("config", f"checkpoint 目标是受保护库 {ckpt_db}")

    class _Cfg:
        checkpoint_database_url = SecretStr(checkpoint_plain)
        langgraph_aes_key = settings.langgraph_aes_key

    from app.lib.ai_runtime import deep_runtime

    if not settings.langgraph_aes_key.get_secret_value():
        _fail("config", "LANGGRAPH_AES_KEY 未配置")
    with psycopg.connect(checkpoint_plain, autocommit=True) as conn:
        saver = deep_runtime.build_saver(conn, _Cfg())
        saver.setup()
    print(f"ACCEPT_REAL_AI_STAGE=checkpoint_ready db={ckpt_db}")

    # Scene and credential through the service layer; uploads and review
    # through the real HTTP API. The admin account is seeded by the API
    # lifespan from ADMIN_USERNAME / ADMIN_PASSWORD when the server boots.
    from app.features.scenes import service as scene_service
    from app.features.scenes.schemas import SceneCreateRequest

    scene = scene_service.create_scene(SceneCreateRequest(name="真实验收场景"))
    issued = scene_service.create_or_replace_credential(scene.id)
    print(f"ACCEPT_REAL_AI_STAGE=scene scene_id={scene.id}")

    base_url = _start_server()
    print(f"ACCEPT_REAL_AI_STAGE=server base_url={base_url}")

    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    status, _ = _http_json(
        f"{base_url}/api/auth/login",
        method="POST",
        payload={"identifier": "admin", "password": "accept-real-ai-password-1"},
        opener=opener,
    )
    if status != 200:
        _fail("login", f"管理员登录失败 status={status}")

    status, body = _http_json(
        f"{base_url}/api/external/question-batches",
        method="POST",
        payload={
            "schema_version": "1.0",
            "command_id": f"accept-real-ai-{int(time.time())}",
            "cases": cases,
        },
        headers={"Authorization": f"Bearer {issued.token}"},
    )
    if status != 201:
        _fail("upload", f"真实样本上传失败 status={status}")
    question_ids = {item["client_case_id"]: item["question_id"] for item in body["cases"]}
    print(f"ACCEPT_REAL_AI_STAGE=uploaded questions={len(question_ids)}")

    from sqlalchemy import select

    from app.lib.ai_runtime import adapters as adapter_module
    from app.lib.ai_runtime.model import build_runtime_model
    from app.lib.database import session_scope
    from app.lib.database.models import OperationJobRow, QuestionRunEventRow, QuestionRunThreadRow
    from app.lib.operations.worker import OperationWorker

    model, identity = build_runtime_model(streaming=True)
    full_adapter = adapter_module.RuntimeAdapters(
        rubric_generator=adapter_module.DeepAgentRubricGenerator(model=model, identity=identity)
    )
    # Install the real deep-agent adapters ONCE; per-phase budget overrides
    # swap only the generator, never back to the fake default.
    adapter_module.set_adapters(full_adapter)

    def build_worker() -> OperationWorker:
        from app.features.question_library import deletion, rubric_generation

        worker = OperationWorker(runtime_mode="production")
        worker.register("rubric_generation", rubric_generation.process_rubric_generation)
        worker.register("question_cleanup", deletion.process_question_cleanup)
        return worker

    def run_worker_rounds(max_rounds: int = 100, poll: float = 0.5) -> int:
        worker = build_worker()
        rounds = 0
        idle = 0
        while rounds < max_rounds:
            if worker.run_once():
                rounds += 1
                idle = 0
            else:
                idle += 1
                if idle > 2:
                    break
                time.sleep(poll)
        return rounds

    def wait_status(question_id: str, expected: set[str], timeout_minutes: float) -> dict:
        """Wait for an expected status; auto-retry unexpected failures.

        Both questions share ONE production queue, so the budget-limited
        recovery phase can also fail the sibling question's first job. An
        unexpected ``generation_failed`` is retried through the real retry
        endpoint (bounded) instead of poisoning the acceptance run.
        """
        deadline = time.monotonic() + timeout_minutes * 60
        detail: dict[str, Any] = {}
        retries = 0
        while time.monotonic() < deadline:
            run_worker_rounds(max_rounds=200)
            status_, detail = _http_json(
                f"{base_url}/api/questions/{question_id}", opener=opener
            )
            if status_ != 200:
                _fail("detail", f"题目读取失败 status={status_}")
            if detail["status"] in expected:
                return detail
            if detail["status"] == "generation_failed" and retries < 2:
                retries += 1
                print(f"ACCEPT_REAL_AI_STAGE=auto_retry question={question_id} n={retries}")
                retry_status, _body = _http_json(
                    f"{base_url}/api/questions/{question_id}/generation-retry",
                    method="POST",
                    payload={"command_id": f"accept-auto-retry-{question_id}-{retries}",
                             "content_revision": detail["content_revision"]},
                    opener=opener,
                )
                if retry_status != 200:
                    _fail("generation", f"自动重试受理失败 status={retry_status}")
            time.sleep(1.0)
        _fail("generation", f"等待超时，当前状态 {detail.get('status')} 错误 {detail.get('last_error')}")
        raise AssertionError

    def locator_texts_for(case: dict) -> dict[str, str]:
        texts: dict[str, str] = {
            "task_prompt": case["task_prompt"],
            "reference_answer": case["reference_answer"],
        }
        for i, item in enumerate(case.get("reference_examples") or []):
            texts[f"reference_examples[{i}]"] = item["content_text"]
        for i, bc in enumerate(case.get("bad_cases") or []):
            texts[f"bad_cases[{i}].content"] = bc["content_text"]
            for j, fb in enumerate(bc["teacher_feedback_texts"]):
                texts[f"bad_cases[{i}].feedback[{j}]"] = fb
            if bc.get("reason_summary"):
                texts[f"bad_cases[{i}].reason_summary"] = bc["reason_summary"]
        for i, mem in enumerate(case.get("memory_materials") or []):
            texts[f"memory_materials[{i}]"] = mem["content_text"]
        return texts

    def assert_complete_contract(case: dict, detail: dict) -> None:
        texts = locator_texts_for(case)
        criteria = detail["criteria"] or []
        if not (2 <= len(criteria) <= 8):
            _fail("contract", f"维度数量异常：{len(criteria)}")
        for item in criteria:
            scores = [a["score"] for a in item["score_anchors"]]
            if item["pass_score"] not in scores:
                _fail("contract", f"建议分 {item['pass_score']} 缺少锚点描述")
            if item["pass_score_basis"]["explained_score"] != item["pass_score"]:
                _fail("contract", "通过分依据解释的分数与建议分不一致")
            for key in ("criterion_basis", "pass_score_basis"):
                claims = item[key]["claims"]
                if not claims:
                    _fail("contract", f"{key} 缺少主张")
                for claim in claims:
                    if claim["kind"] not in ("teacher_explicit", "ai_inferred"):
                        _fail("contract", "主张分类非法")
                    if claim["kind"] == "teacher_explicit" and not claim.get("citation"):
                        _fail("contract", "老师明确要求缺少引用")
                    citation = claim.get("citation")
                    if citation:
                        text = texts.get(citation["locator"])
                        if text is None:
                            _fail("contract", f"引用定位符不属于本题材料：{citation['locator']}")
                        elif citation["quote"].strip() and citation["quote"].strip() not in text:
                            _fail("contract", "引用原文不在对应材料中")

    import subprocess
    from datetime import datetime, timezone

    import importlib.metadata as importlib_md

    try:
        git_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10
        ).stdout.strip()
    except Exception:
        git_sha = "unknown"
    evidence: dict[str, Any] = {
        "run_identity": {
            "git_sha": git_sha,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "model": {"provider": identity.provider, "model": identity.model,
                      "fingerprint": identity.fingerprint,
                      "base_url_set": bool(identity.base_url)},
            "sdk_versions": {
                "deepagents": importlib_md.version("deepagents"),
                "langgraph": importlib_md.version("langgraph"),
                "langgraph_checkpoint_postgres": importlib_md.version(
                    "langgraph-checkpoint-postgres"),
                "langchain": importlib_md.version("langchain"),
            },
            "business_db": business_sqla.rsplit("/", 1)[-1],
            "checkpoint_db": ckpt_db,
            "worker_runtime_marker": "production (asserted per settled job)",
        },
        "cases": {},
    }
    case_by_id = {c["client_case_id"]: c for c in cases}

    for case_id, question_id in question_ids.items():
        case = case_by_id[case_id]
        print(f"ACCEPT_REAL_AI_STAGE=generate case={case_id}")

        if case_id == args.recovery_case:
            # Phase 1: a real run under a 1-model-call budget writes real
            # checkpoints and fails bounded — the thread stays incomplete.
            budgeted = adapter_module.RuntimeAdapters(
                rubric_generator=adapter_module.DeepAgentRubricGenerator(
                    model=model,
                    identity=identity,
                    budget=deep_runtime.RuntimeBudget(max_model_calls=1),
                )
            )
            adapter_module.set_adapters(budgeted)
            try:
                detail = wait_status(question_id, {"generation_failed"}, args.max_minutes_per_case)
            finally:
                adapter_module.set_adapters(full_adapter)
            if detail["last_error"]["code"] != "RUNTIME_BUDGET_EXCEEDED":
                _fail("recovery", f"预算阶段错误码异常：{detail['last_error']}")

            # Phase 2: retry with the full budget must RESUME the same thread.
            status_, _body = _http_json(
                f"{base_url}/api/questions/{question_id}/generation-retry",
                method="POST",
                payload={"command_id": f"accept-retry-{case_id}",
                         "content_revision": detail["content_revision"]},
                opener=opener,
            )
            if status_ != 200:
                _fail("recovery", f"重试受理失败 status={status_}")
            detail = wait_status(question_id, {"pending_review"}, args.max_minutes_per_case)
            if not _thread_observed_resume(question_id):
                _fail("recovery", "重试未观察到从检查点恢复（thread_state_incomplete）")
        else:
            adapter_module.set_adapters(full_adapter)
            detail = wait_status(question_id, {"pending_review"}, args.max_minutes_per_case)

        assert_complete_contract(case, detail)
        _assert_real_runtime(question_id)

        # Persisted public event log: real deltas/tools + authoritative end.
        operation_id = detail["last_operation_id"]
        status_, events = _http_json(
            f"{base_url}/api/questions/{question_id}/runs/{operation_id}/events", opener=opener
        )
        if status_ != 200 or not events["events"]:
            _fail("events", f"公开事件日志缺失 status={status_}")
        kinds = [e["kind"] for e in events["events"]]
        if kinds[-1] != "run_completed":
            _fail("events", "事件日志未以 run_completed 收尾（完成必须先于业务保存不得出现）")
        if "message_delta" not in kinds and "tool_started" not in kinds:
            _fail("events", "事件日志没有任何真实增量或工具事件")

        # Teacher edits: unanchored integer saves; bases are preserved.
        criteria = json.loads(json.dumps(detail["criteria"]))
        criteria[0]["pass_score"] = 5
        status_, saved = _http_json(
            f"{base_url}/api/questions/{question_id}/criteria",
            method="PATCH",
            payload={"command_id": f"accept-patch-{case_id}",
                     "content_revision": detail["content_revision"],
                     "criteria": criteria},
            opener=opener,
        )
        if status_ != 200:
            _fail("edit", f"任意整数保存失败 status={status_}")
        if saved["criteria"][0]["pass_score"] != 5:
            _fail("edit", "保存后通过分不是 5")
        if saved["criteria"][0]["pass_score_basis"]["explained_score"] == 5:
            _fail("edit", "依据被静默改写成新分数")

        status_, published = _http_json(
            f"{base_url}/api/questions/{question_id}/publication",
            method="POST",
            payload={"command_id": f"accept-publish-{case_id}",
                     "content_revision": saved["content_revision"]},
            opener=opener,
        )
        if status_ != 200 or published["status"] != "published":
            _fail("publish", f"发布失败 status={status_}")
        status_, reopened = _http_json(
            f"{base_url}/api/questions/{question_id}/review-reopen",
            method="POST",
            payload={"command_id": f"accept-reopen-{case_id}",
                     "content_revision": published["content_revision"]},
            opener=opener,
        )
        if status_ != 200 or reopened["status"] != "pending_review":
            _fail("reopen", f"重开审改失败 status={status_}")

        evidence["cases"][case_id] = {
            "question_id": question_id,
            "criteria": len(detail["criteria"]),
            "events": len(events["events"]),
            "kinds": sorted(set(kinds)),
            "recovery": case_id == args.recovery_case,
        }
        print(
            f"ACCEPT_REAL_AI_STAGE=reviewed case={case_id} "
            f"criteria={len(detail['criteria'])} events={len(events['events'])}"
        )

    # Complete deletion of the first case with cross-store residue checks.
    first_case_id = next(iter(question_ids))
    first_question = question_ids[first_case_id]
    sibling_id = next((qid for qid in question_ids.values() if qid != first_question), None)
    status_, detail = _http_json(f"{base_url}/api/questions/{first_question}", opener=opener)
    thread_ids = _registered_threads(first_question)
    status_, accepted = _http_json(
        f"{base_url}/api/questions/{first_question}",
        method="DELETE",
        payload={"command_id": f"accept-delete-{first_case_id}",
                 "content_revision": detail["content_revision"],
                 "confirmation_title": detail["title"]},
        opener=opener,
    )
    if status_ != 202:
        _fail("delete", f"删除受理失败 status={status_}")
    deadline = time.monotonic() + 600
    gone = False
    while time.monotonic() < deadline:
        run_worker_rounds(max_rounds=100)
        status_, _body = _http_json(f"{base_url}/api/questions/{first_question}", opener=opener)
        if status_ == 404:
            gone = True
            break
        time.sleep(1.0)
    if not gone:
        _fail("delete", "删除清理未在期限内完成")

    # Zero residue in BOTH stores; sibling untouched.
    with psycopg.connect(checkpoint_plain, autocommit=True) as conn:
        for thread_id in thread_ids:
            residue = deep_runtime.thread_data_residue(conn, thread_id)
            if any(v != 0 for v in residue.values()):
                _fail("delete", f"检查点残留 thread={thread_id} residue={residue}")
    with session_scope() as session:
        leftover_events = session.execute(
            select(QuestionRunEventRow).where(QuestionRunEventRow.question_id == first_question)
        ).scalars().all()
        leftover_threads = session.execute(
            select(QuestionRunThreadRow).where(QuestionRunThreadRow.question_id == first_question)
        ).scalars().all()
        leftover_jobs = session.execute(
            select(OperationJobRow).where(
                OperationJobRow.target_type == "eval_question",
                OperationJobRow.target_id == first_question,
            )
        ).scalars().all()
    if leftover_events or leftover_threads or leftover_jobs:
        _fail("delete", "业务库仍有运行事件、线程映射或生成作业残留")
    if sibling_id is not None:
        status_, _sibling = _http_json(f"{base_url}/api/questions/{sibling_id}", opener=opener)
        if status_ != 200:
            _fail("delete", f"兄弟题被误伤 status={status_}")
        evidence["sibling_intact"] = True
    evidence["deletion"] = {"case": first_case_id, "threads_cleaned": len(thread_ids)}
    print(f"ACCEPT_REAL_AI_STAGE=deleted case={first_case_id} threads={len(thread_ids)}")

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "accept-evidence.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("ACCEPT_REAL_AI=PASS")
    return 0


def _assert_real_runtime(question_id: str) -> None:
    """The settled job must carry the production runtime marker."""
    from sqlalchemy import select

    from app.lib.database import session_scope
    from app.lib.database.models import OperationJobRow

    with session_scope() as session:
        job = session.execute(
            select(OperationJobRow).where(
                OperationJobRow.target_type == "eval_question",
                OperationJobRow.target_id == question_id,
                OperationJobRow.status == "succeeded",
            )
        ).scalars().first()
    if job is None or (job.result_json or {}).get("__worker_runtime_mode") != "production":
        _fail("runtime", f"题目 {question_id} 的生成不是 production 运行模式完成的")


def _registered_threads(question_id: str) -> list[str]:
    from app.features.question_library import run_streams

    return run_streams.list_question_threads(question_id)


def _thread_observed_resume(question_id: str) -> bool:
    """True when any persisted event of this question shows a resumed run.

    Scans ALL events of the question: a retry may run under a NEW operation
    id (retry command ids derive a fresh deterministic job), so binding the
    scan to one job row would miss the resume evidence.
    """
    from sqlalchemy import select

    from app.lib.database import session_scope
    from app.lib.database.models import QuestionRunEventRow

    with session_scope() as session:
        rows = session.execute(
            select(QuestionRunEventRow.stage).where(
                QuestionRunEventRow.question_id == question_id,
                QuestionRunEventRow.kind == "run_resumed",
            )
        ).scalars().all()
    return any(stage == "thread_state_incomplete" for stage in rows)


if __name__ == "__main__":
    sys.exit(main())
