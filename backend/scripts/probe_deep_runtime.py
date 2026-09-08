"""Real-provider probe for the deep-agent runtime primitives (C2 evidence).

Runs ONE bounded execution against the configured real provider using the C1
real-sample materials, on the task-exclusive PostgreSQL test database — never
the project's blue_benchmark / blue_benchmark_checkpoint databases.

Proven gates (all must pass, no stub substitution):

1. restricted assembly: model never sees ``execute``/``task``;
2. real streaming: public message deltas arrive WHILE the run is in progress;
3. real tool use: the agent reads the mounted question materials;
4. structured result via ``response_format`` (test schema, not the production
   rubric contract);
5. PostgreSQL checkpoint durability with encrypted-at-rest blobs;
6. restart recovery: fresh connection/saver/agent classifies the thread as
   complete and reads back the same result without re-running the model;
7. model-free cleanup: delete_thread_data leaves zero residue.

Evidence is redacted: versions, fingerprints, counts, lengths and timings —
never material bodies or model output text.

Usage:
    cd backend && uv run python -m scripts.probe_deep_runtime \
        --corpus-root <repo-root>/.local-samples/m0 \
        --out storage/acceptance/m0-deep-runtime-probe
"""

from __future__ import annotations

import argparse
import importlib.metadata as md
import json
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.lib.ai_runtime import deep_runtime as dr  # noqa: E402
from app.lib.ai_runtime.model import build_runtime_model  # noqa: E402
from scripts import m0_samples  # noqa: E402

TEST_DB_NAME = "blue_benchmark_c2_runtime_test"
PROBE_THREAD = "probe-deep-runtime-m0"


class ProbeCriterion(BaseModel):
    """Test-only result schema; deliberately NOT the production rubric DTO."""

    model_config = ConfigDict(extra="forbid")

    criterion: str = Field(min_length=8, max_length=500)
    pass_score: int = Field(ge=0, le=10)


class ProbeResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    material_files_read: list[str] = Field(min_length=1, max_length=20)
    summary: str = Field(min_length=10, max_length=1_000)
    probe_criteria: list[ProbeCriterion] = Field(min_length=1, max_length=8)


PROBE_SYSTEM_PROMPT = (
    "你是运行基础探针。你的任务：\n"
    "1. 用 ls 列出 /materials 下的全部文件；\n"
    "2. 用 read_file 阅读题目材料与老师反馈（文件较长时分段读取或用 grep 定位）；\n"
    "3. 基于材料起草 2-4 条探针评分维度（criterion 必须具体可执行，pass_score 为 0-10 整数），"
    "并在 summary 中用不超过 200 字说明材料核查过程；\n"
    "4. 在 material_files_read 中列出你实际读取过的文件路径。\n"
    "只使用 /materials 下的本题材料，不得虚构来源。"
)


def _test_dsn() -> str:
    import os

    override = os.environ.get("RUNTIME_CHECKPOINT_TEST_DSN")
    if override:
        return override
    from app.lib.settings import settings

    base = settings.checkpoint_database_url.get_secret_value()
    if not base:
        raise SystemExit("PROBE=FAIL CHECKPOINT_DATABASE_URL 未配置")
    parts = urlsplit(base)
    scheme = parts.scheme.replace("+psycopg", "")
    return urlunsplit((scheme, parts.netloc, f"/{TEST_DB_NAME}", "", ""))


def _probe_cfg(dsn: str) -> Any:
    from app.lib.settings import settings

    class _Cfg:
        checkpoint_database_url = SecretStr(dsn)
        langgraph_aes_key = settings.langgraph_aes_key

    if not _Cfg.langgraph_aes_key.get_secret_value():
        raise SystemExit("PROBE=FAIL LANGGRAPH_AES_KEY 未配置")
    return _Cfg()


def _load_case_materials(corpus_root: Path, fixture_dir: Path, case_id: str) -> tuple[dict[str, str], dict[str, Any]]:
    """Rebuild C1 fixtures (private, gitignored) and map one case to materials."""
    result = m0_samples.run_extraction(corpus_root, fixture_dir, "probe-deep-runtime")
    batch = json.loads((fixture_dir / "batch.json").read_text(encoding="utf-8"))
    case = next((c for c in batch["cases"] if c["client_case_id"] == case_id), None)
    if case is None:
        raise SystemExit(f"PROBE=FAIL case {case_id} 不在重建批次中")
    materials: dict[str, str] = {
        "题目.md": f"# {case['title']}\n\n{case['task_prompt']}",
        "标准答案.md": case["reference_answer"],
    }
    for i, item in enumerate(case.get("reference_examples") or [], 1):
        materials[f"参考样例-{i}-{item.get('source_name') or i}.md"] = item["content_text"]
    for i, bc in enumerate(case.get("bad_cases") or [], 1):
        parts = [f"## 被否定的稿件\n\n{bc['content_text']}", "## 老师反馈"]
        parts += [f"- {fb}" for fb in bc["teacher_feedback_texts"]]
        if bc.get("reason_summary"):
            parts.append(f"## 原因整理\n\n{bc['reason_summary']}")
        materials[f"坏案例-{i}.md"] = "\n\n".join(parts)
    for i, mem in enumerate(case.get("memory_materials") or [], 1):
        materials[f"记忆材料-{i}-{mem.get('source_label') or i}.md"] = mem["content_text"]
    meta = {
        "case_id": case_id,
        "material_files": len(materials),
        "material_chars": sum(len(v) for v in materials.values()),
        "extraction_summary": result["summary"],
    }
    return materials, meta


class TimedSink:
    """Records each public event with its arrival offset (ms) from a shared t0."""

    def __init__(self, t0: float) -> None:
        self.t0 = t0
        self.records: list[tuple[int, Any]] = []

    def emit(self, event: Any) -> None:
        self.records.append((round((time.monotonic() - self.t0) * 1000), event))

    @property
    def events(self) -> list[Any]:
        return [event for _ms, event in self.records]

    def first_ms(self, kind: str) -> int | None:
        for ms, event in self.records:
            if event.kind == kind:
                return ms
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--corpus-root",
        default=str(Path(__file__).resolve().parents[2] / ".local-samples" / "m0"),
    )
    parser.add_argument("--case", default="m0-real-m-mega-press-release")
    parser.add_argument("--out", default="storage/acceptance/m0-deep-runtime-probe")
    parser.add_argument("--max-model-calls", type=int, default=14)
    parser.add_argument("--max-tool-calls", type=int, default=60)
    parser.add_argument("--max-seconds", type=float, default=1500.0)
    args = parser.parse_args(argv)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    fixture_dir = out_dir / "samples"

    print("PROBE_STAGE=materials")
    materials, case_meta = _load_case_materials(Path(args.corpus_root), fixture_dir, args.case)
    print(f"PROBE_STAGE=materials files={case_meta['material_files']} chars={case_meta['material_chars']}")

    print("PROBE_STAGE=model")
    model, identity = build_runtime_model(streaming=True)
    print(f"PROBE_STAGE=model provider={identity.provider} fingerprint={identity.endpoint_fingerprint}")

    dsn = _test_dsn()
    cfg = _probe_cfg(dsn)

    import psycopg

    print(f"PROBE_STAGE=checkpoint db={urlsplit(dsn).path}")
    conn = psycopg.connect(dsn, autocommit=True)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT current_database()")
            actual_db = cur.fetchone()[0]
    finally:
        conn.close()
    # Last line of defense against a misconfigured override DSN: destructive
    # probe operations may only ever target the task-exclusive test database.
    if actual_db != TEST_DB_NAME:
        raise SystemExit(f"PROBE=FAIL 目标库不是独占测试库 {TEST_DB_NAME}：{actual_db}")
    session0 = dr.open_session(PROBE_THREAD, cfg)
    try:
        dr.delete_thread_data(session0)
    finally:
        session0.close()

    budget = dr.RuntimeBudget(
        max_model_calls=args.max_model_calls,
        max_tool_calls=args.max_tool_calls,
        max_total_seconds=args.max_seconds,
    )

    evidence: dict[str, Any] = {
        "versions": {
            "deepagents": md.version("deepagents"),
            "langgraph": md.version("langgraph"),
            "langgraph_checkpoint_postgres": md.version("langgraph-checkpoint-postgres"),
            "langchain": md.version("langchain"),
            "langchain_core": md.version("langchain-core"),
            "psycopg": md.version("psycopg"),
            "pycryptodome": md.version("pycryptodome"),
        },
        "model": {"provider": identity.provider, "model": identity.model,
                  "fingerprint": identity.endpoint_fingerprint, "base_url_set": bool(identity.base_url)},
        "case": {k: v for k, v in case_meta.items() if k != "extraction_summary"},
        "budget": {"max_model_calls": budget.max_model_calls,
                   "max_tool_calls": budget.max_tool_calls,
                   "max_total_seconds": budget.max_total_seconds},
    }

    # ---- Run 1: fresh thread, real provider, streaming ----
    print("PROBE_STAGE=run")
    session = dr.open_session(PROBE_THREAD, cfg)
    try:
        t0 = time.monotonic()
        sink = TimedSink(t0)
        counters = dr.BudgetCounters()
        agent = dr.build_restricted_agent(
            model, identity,
            system_prompt=PROBE_SYSTEM_PROMPT,
            budget=budget, counters=counters, sink=sink,
            checkpointer=session.saver,
            response_format=ProbeResult,
        )
        bound = sorted(dr.bound_tool_names(agent))
        # `task` must be gone entirely (no subagent middleware). `execute`
        # stays registered in the executor but is never advertised to the
        # model and is rejected at the call boundary — proven below via the
        # bind_tools spy (innermost point, after all middleware filtering).
        assert "task" not in bound, f"受限装配失败：{bound}"
        evidence["assembly"] = {"registered_tools": bound}

        bind_log: list[list[str]] = []
        original_bind = model.bind_tools

        def spy_bind(tools: Any, **kwargs: Any) -> Any:
            bind_log.append([getattr(t, "name", str(t)) for t in tools])
            return original_bind(tools, **kwargs)

        object.__setattr__(model, "bind_tools", spy_bind)

        values = dr.run_streaming(
            agent, session,
            inputs={"messages": [{"role": "user", "content": "开始探针任务：核查本题材料并产出探针维度。"}],
                    "files": dr.materials_files(materials)},
            sink=sink,
        )
        total_ms = (time.monotonic() - t0) * 1000
        first_delta_ms = sink.first_ms("message_delta")
        first_tool_ms = sink.first_ms("tool_started")
        last_delta_ms = max(
            (ms for ms, e in sink.records if e.kind == "message_delta"), default=None
        )

        structured = dr.final_structured_response(agent, session)
        assert isinstance(structured, ProbeResult), "结构化结果缺失或类型错误"
        kinds: dict[str, int] = {}
        for event in sink.events:
            kinds[event.kind] = kinds.get(event.kind, 0) + 1
        delta_chars = sum(len(e.text or "") for e in sink.events if e.kind == "message_delta")
        evidence["run"] = {
            "total_ms": round(total_ms),
            "first_delta_ms": first_delta_ms,
            "last_delta_ms": last_delta_ms,
            "first_tool_ms": first_tool_ms,
            "events_by_kind": kinds,
            "streamed_public_chars": delta_chars,
            "model_calls": counters.model_calls,
            "tool_calls": counters.tool_calls,
            "structured_criteria": len(structured.probe_criteria),
            "structured_summary_chars": len(structured.summary),
            "files_read_reported": len(structured.material_files_read),
            "workspace_files": sorted(dr.final_files(agent, session).keys()),
        }
        print(f"PROBE_STAGE=run done total_ms={round(total_ms)} "
              f"first_delta_ms={first_delta_ms} first_tool_ms={first_tool_ms} "
              f"model_calls={counters.model_calls} tool_calls={counters.tool_calls}")

        # Streaming liveness gate: deltas and tool events arrived DURING the
        # run, and deltas kept arriving after the first tool call (not one
        # final burst after everything finished).
        assert kinds.get("message_delta", 0) > 0, "运行期间没有收到公开消息增量"
        assert first_delta_ms is not None and first_delta_ms < total_ms * 0.9, (
            f"增量未在运行中到达（first={first_delta_ms} total={round(total_ms)}）"
        )
        assert kinds.get("tool_started", 0) > 0, "运行期间没有真实工具调用"
        assert first_tool_ms is not None and last_delta_ms is not None and last_delta_ms > first_tool_ms, (
            "工具调用之后没有继续收到模型增量，流式活性存疑"
        )
        # Hard tool-restriction gate at the model-bind boundary.
        assert bind_log, "模型调用未绑定工具，无法证明排除生效"
        for names in bind_log:
            assert "execute" not in names and "task" not in names, (
                f"被禁工具仍暴露给模型：{names}"
            )
        evidence["assembly"]["model_bound_tools_first_call"] = sorted(bind_log[0])

        # Encrypted-at-rest gate.
        marker = next(iter(materials.values()))[:24]
        with session.conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM checkpoints WHERE thread_id = %s", (PROBE_THREAD,))
            checkpoints = cur.fetchone()[0]
            cur.execute(
                "SELECT blob, type FROM checkpoint_blobs WHERE thread_id = %s", (PROBE_THREAD,)
            )
            rows = cur.fetchall()
        leaked = sum(1 for blob, _t in rows if marker.encode() in bytes(blob or b""))
        assert checkpoints > 0 and rows and leaked == 0, "检查点缺失或明文入库"
        evidence["checkpoint"] = {
            "rows": checkpoints, "blob_rows": len(rows), "plaintext_marker_leaks": leaked,
            "cipher_types": sorted({t for _b, t in rows if "+aes" in str(t)})[:3],
        }
    finally:
        session.close()

    # ---- Run 2: restart recovery, no model call allowed ----
    print("PROBE_STAGE=recover")
    t1 = time.monotonic()
    session2 = dr.open_session(PROBE_THREAD, cfg)
    try:
        counters2 = dr.BudgetCounters()
        sink2 = dr.ListSink()

        # Recovery must not touch the provider: any model call raises
        # StopIteration from the empty script (loud failure, zero cost).
        from langchain_core.language_models.fake_chat_models import GenericFakeChatModel

        class _NoCallModel(GenericFakeChatModel):
            def bind_tools(self, tools: Any, **kwargs: Any) -> "_NoCallModel":
                return self

        agent2 = dr.build_restricted_agent(
            _NoCallModel(messages=iter([])), identity,
            system_prompt=PROBE_SYSTEM_PROMPT,
            budget=budget, counters=counters2, sink=sink2,
            checkpointer=session2.saver,
            response_format=ProbeResult,
        )
        state_kind = dr.classify_thread_state(agent2, session2.thread_config())
        assert state_kind == "complete", f"重启后线程状态应为 complete，实际 {state_kind}"
        recovered = dr.final_structured_response(agent2, session2)
        assert isinstance(recovered, ProbeResult)
        assert len(recovered.probe_criteria) == evidence["run"]["structured_criteria"]
        files2 = dr.final_files(agent2, session2)
        assert files2, "恢复后状态文件为空"
        assert counters2.model_calls == 0 and counters2.tool_calls == 0
        evidence["recovery"] = {
            "classify": state_kind,
            "recover_ms": round((time.monotonic() - t1) * 1000),
            "model_calls": counters2.model_calls,
            "state_files": sorted(files2.keys()),
        }
        print(f"PROBE_STAGE=recover classify={state_kind} files={len(files2)}")

        # ---- Cleanup gate (model-free) ----
        print("PROBE_STAGE=cleanup")
        residue = dr.delete_thread_data(session2)
        assert all(v == 0 for v in residue.values()), f"清理残留：{residue}"
        evidence["cleanup"] = {"residue": residue}
        print("PROBE_STAGE=cleanup residue=0")
    finally:
        session2.close()

    (out_dir / "probe-evidence.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"PROBE=OK evidence={out_dir / 'probe-evidence.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
