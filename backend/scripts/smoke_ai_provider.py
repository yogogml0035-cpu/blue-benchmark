"""Real-data smoke: the configured provider through the COMPLETE generation
contract on the durable deep runtime, using a C1 real-sample case.

One-shot replacement of the old fixed-generic-sample/single-call smoke: a
generic connectivity ping can no longer masquerade as this smoke. It fails
loudly when the corpus, an isolated checkpoint target or the provider is
missing — never falls back to fake mode or placeholder samples.

Prints only structural facts (counts, scores, latency, event kinds); never
material bodies or model output text.

Required environment:
    SMOKE_CHECKPOINT_DSN  isolated checkpoint database (project DBs refused)
    (AI_* provider config from .env as usual)

Usage:
    cd backend && uv run python -m scripts.smoke_ai_provider \
        --corpus-root <repo-root>/.local-samples/m0
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import time
from pathlib import Path
from typing import Any

FORBIDDEN_DB_NAMES = {"blue_benchmark", "blue_benchmark_checkpoint", "postgres", "template1"}


def _fail(message: str) -> None:
    print(f"AI_SMOKE=FAIL {message}")
    raise SystemExit(1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--corpus-root",
        default=str(Path(__file__).resolve().parents[2] / ".local-samples" / "m0"),
    )
    parser.add_argument("--case", default="m0-real-f-financial-report")
    parser.add_argument("--out", default="storage/acceptance/m0-ai-smoke")
    parser.add_argument("--max-model-calls", type=int, default=14)
    parser.add_argument("--max-tool-calls", type=int, default=60)
    args = parser.parse_args()

    checkpoint_dsn = os.environ.get("SMOKE_CHECKPOINT_DSN", "")
    if not checkpoint_dsn:
        _fail("必须提供 SMOKE_CHECKPOINT_DSN（隔离检查点库）；不接受项目库或内存替代")
    from urllib.parse import urlsplit

    db_name = (urlsplit(checkpoint_dsn.replace("postgresql+psycopg://", "postgresql://")).path or "/").lstrip("/")
    if db_name in FORBIDDEN_DB_NAMES:
        _fail(f"SMOKE_CHECKPOINT_DSN 指向受保护库 {db_name}")

    os.environ["CHECKPOINT_DATABASE_URL"] = checkpoint_dsn

    # Rebuild the real case from the read-only corpus (hash-gated).
    from scripts import m0_samples

    out_dir = Path(args.out)
    m0_samples.run_extraction(Path(args.corpus_root), out_dir / "samples", "ai-smoke")
    import json

    batch = json.loads((out_dir / "samples" / "batch.json").read_text(encoding="utf-8"))
    case = next((c for c in batch["cases"] if c["client_case_id"] == args.case), None)
    if case is None:
        _fail(f"case {args.case} 不在重建批次中")

    from app.lib.ai_runtime.adapters import (
        RubricGenerationFailure,
        RubricGenerationInput,
        RunContext,
        build_locator_texts,
        production_adapters,
    )
    from app.lib.ai_runtime.deep_runtime import ListSink, RuntimeBudget
    from app.lib.ai_runtime.model import build_runtime_model, runtime_model_identity

    identity = runtime_model_identity()
    print(f"AI_SMOKE_PROVIDER={identity.provider} model={identity.model}")

    materials = RubricGenerationInput(
        task_prompt=case["task_prompt"],
        # The batch contract carries client_ref_id for upload idempotency;
        # the generation input only accepts the material content fields.
        reference_examples=[
            {"source_name": item.get("source_name"), "content_text": item["content_text"]}
            for item in case.get("reference_examples") or []
        ],
        bad_cases=case.get("bad_cases") or [],
        reference_answer=case["reference_answer"],
        memory_materials=[
            {"source_label": item.get("source_label"), "content_text": item["content_text"]}
            for item in case.get("memory_materials") or []
        ],
    )
    run_id = hashlib.sha256(f"smoke-{time.time()}".encode()).hexdigest()[:12]
    context = RunContext(
        thread_id=f"smoke-{run_id}",
        operation_id=f"smoke-op-{run_id}",
        attempt_number=1,
        question_id=f"smoke-{run_id}",
        materials_revision=1,
        materials_fingerprint=hashlib.sha256(
            json.dumps(case, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest(),
    )

    import psycopg
    from pydantic import SecretStr

    from app.lib.ai_runtime import deep_runtime
    from app.lib.settings import settings

    class _Cfg:
        checkpoint_database_url = SecretStr(checkpoint_dsn)
        langgraph_aes_key = settings.langgraph_aes_key

    with psycopg.connect(checkpoint_dsn, autocommit=True) as conn:
        saver = deep_runtime.build_saver(conn, _Cfg())
        saver.setup()

    # Fail fast on broken provider configuration before touching databases;
    # the generator below lazily builds the SAME model from the SAME config
    # and resolves its own contract (no injected identity to drift).
    build_runtime_model(streaming=True)
    # The parsed budget options are REAL run limits: they flow into the same
    # contract the generator resolves, so the smoke's budget and the recorded
    # contract identity can never diverge from what actually executed.
    budget = deep_runtime.RuntimeBudget(
        max_model_calls=args.max_model_calls,
        max_tool_calls=args.max_tool_calls,
    )
    generator = production_adapters(budget=budget).rubric_generator
    contract = generator.harness_contract
    print(
        f"AI_SMOKE_CONTRACT protocol={contract.protocol} "
        f"effort={contract.reasoning_effort or 'unspecified'} "
        f"output_strategy={contract.output_strategy} "
        f"fingerprint={contract.fingerprint[:16]} "
        f"budget=({contract.max_model_calls},{contract.max_tool_calls})"
    )
    sink = ListSink()

    started = time.monotonic()
    try:
        result = generator.generate(materials, context=context, sink=sink)
    except RubricGenerationFailure as exc:
        # stdout stays sanitized: AI_CITATION_INVALID messages embed verbatim
        # material spans (teacher-facing feedback), which must never reach a
        # console log that claims "never material bodies". Full messages live
        # in the business last_error and the run diagnostics.
        print(f"AI_SMOKE=FAIL code={exc.code} message_chars={len(exc.message)}")
        return 1
    finally:
        # The smoke thread is always cleaned up (model-free), success or not.
        try:
            with psycopg.connect(checkpoint_dsn, autocommit=True) as conn:
                cleanup_saver = deep_runtime.build_saver(conn, _Cfg())
                session = deep_runtime.CheckpointSession(conn, cleanup_saver, context.thread_id)
                session.acquire_lock()
                try:
                    deep_runtime.delete_thread_data(session)
                finally:
                    session.close()
        except Exception as exc:
            print(f"AI_SMOKE_WARN=cleanup_failed {type(exc).__name__}")
    elapsed = time.monotonic() - started

    # Contract assertions on the complete result (structural facts only).
    locator_texts = build_locator_texts(materials)
    scores = [item.pass_score for item in result.criteria]
    for item in result.criteria:
        anchor_scores = [a.score for a in item.score_anchors]
        if item.pass_score not in anchor_scores:
            _fail("建议分缺少对应锚点描述")
        if item.pass_score_basis.explained_score != item.pass_score:
            _fail("通过分依据解释分数不一致")
        for basis in (item.criterion_basis, item.pass_score_basis):
            for claim in basis.claims:
                citation = claim.citation
                if citation is not None:
                    text = locator_texts.get(citation.locator)
                    if text is None or (citation.quote.strip() and citation.quote.strip() not in text):
                        _fail("引用无法在本题材料中核实")
    kinds: dict[str, int] = {}
    for event in sink.events:
        kinds[event.kind] = kinds.get(event.kind, 0) + 1
    if kinds.get("message_delta", 0) + kinds.get("tool_started", 0) == 0:
        _fail("冒烟运行没有产生任何真实增量或工具事件")
    print(
        f"AI_SMOKE=OK criteria={len(result.criteria)} pass_scores={scores} "
        f"events={kinds} elapsed_seconds={elapsed:.1f} "
        f"contract_fingerprint={contract.fingerprint[:16]}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
