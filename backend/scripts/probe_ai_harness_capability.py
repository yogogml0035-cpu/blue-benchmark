"""C1 capability probe: the FULL production rubric contract over native Responses.

Verifies — against the real gateway, with the real corpus, on a task-exclusive
PostgreSQL checkpoint database — that the current model can complete the
complete ``RubricGenerationResult`` contract while keeping
``AI_REASONING_EFFORT``, using the Responses protocol with:

* a real material tool round-trip (``ls``/``read_file`` on ``/materials``);
* native structured output (``text.format`` JSON schema);
* public streaming deltas during the run;
* client-held history (``store=false``, no ``previous_response_id``) with
  encrypted reasoning round-trips (``include=["reasoning.encrypted_content"]``);
* hard process interruption after a tool round, then resume from the encrypted
  checkpoint with ``inputs=None`` — no duplicated initial input;
* a completed-thread re-read with ZERO model calls;
* model-free cleanup with zero checkpoint residue.

The probe reuses the production ``DeepAgentRubricGenerator`` through its model
injection entrypoint; it never modifies ``backend/app``. The candidate model
construction below is deliberately LOCAL to this probe (a candidate protocol
under test, not a production contract); the C2 cutover replaces it with the
unified production assembly.

Safety contract:

* default is dry-run: a redacted config/resource precheck, no model requests;
* ``--execute`` requires an explicit isolated checkpoint DSN; the project
  databases (``blue_benchmark``, ``blue_benchmark_checkpoint``) and system
  databases are refused by name AND by a live ``current_database()`` check;
* evidence is redacted: versions, fingerprints, hashes, counts, timings and
  safe error categories — never material bodies, model output text,
  credentials or encrypted reasoning;
* budgets are bounded and identical across the interrupt/resume processes.

Usage:
    cd backend && uv run python -m scripts.probe_ai_harness_capability
    C1_CHECKPOINT_DSN=postgresql://user@127.0.0.1:5432/blue_benchmark_c1_capability \
    cd backend && uv run python -m scripts.probe_ai_harness_capability --execute
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata as md
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

PROTECTED_DB_NAMES = frozenset({
    "blue_benchmark", "blue_benchmark_checkpoint",
    "postgres", "template1", "template0",
})
# Additional guard: the C1 probe may never run against a database whose name
# does not carry the dedicated capability-probe marker.
REQUIRED_DB_MARKER = "c1_capability"

DEFAULT_THREAD = "c1-capability-probe"
# Distinct exit code the interrupted run child uses to signal "I died exactly
# at the planned interruption point after a durable tool-round checkpoint".
INTERRUPT_EXIT_CODE = 42

# Markers that must never appear in a PUBLIC event field: raw encrypted
# reasoning blocks or credential material. Protocol parameter NAMES (e.g.
# "reasoning.effort") are whitelisted configuration facts and belong in the
# evidence report; private reasoning CONTENT never does.
PUBLIC_EVENT_FORBIDDEN = ("encrypted_content", "sk-", "bearer ", "api_key")


def _secret_values() -> tuple[str, ...]:
    """Actual secret values that must never appear in persisted evidence."""
    from app.lib.settings import settings

    values = []
    for secret in (settings.ai_api_key, settings.langgraph_aes_key,
                   settings.checkpoint_database_url):
        raw = secret.get_secret_value() if hasattr(secret, "get_secret_value") else str(secret)
        if raw:
            values.append(raw)
    return tuple(values)


class ProbeError(RuntimeError):
    """A probe failure with a safe, whitelisted category and message."""

    def __init__(self, stage: str, category: str, message: str) -> None:
        super().__init__(message)
        self.stage = stage
        self.category = category
        self.message = message


def _fail(stage: str, category: str, message: str) -> None:
    print(f"PROBE=FAIL stage={stage} category={category} message={message}")
    raise SystemExit(1)


def _public_event_violation(fields: list[str | None]) -> str | None:
    for value in fields:
        if not value:
            continue
        lowered = value.lower()
        for marker in PUBLIC_EVENT_FORBIDDEN:
            if marker in lowered:
                return marker
    return None


def _evidence_secret_violation(blob: str) -> str | None:
    for secret in _secret_values():
        if secret and secret in blob:
            return "configured_secret_value"
    return None


# ---------------------------------------------------------------------------
# Configuration and isolation gates
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ProbeConfig:
    checkpoint_dsn: str
    corpus_root: Path
    case_id: str
    out_dir: Path
    thread_id: str
    max_model_calls: int
    max_tool_calls: int
    max_seconds: float
    max_attempts: int

    @property
    def db_name(self) -> str:
        raw = self.checkpoint_dsn.replace("postgresql+psycopg://", "postgresql://")
        return (urlsplit(raw).path or "/").lstrip("/").split("?")[0]


def resolve_config(args: argparse.Namespace) -> ProbeConfig:
    dsn = args.checkpoint_dsn or os.environ.get("C1_CHECKPOINT_DSN", "")
    if not dsn:
        raise ProbeError(
            "config", "checkpoint_dsn_missing",
            "--execute 需要显式隔离检查点 DSN（--checkpoint-dsn 或 C1_CHECKPOINT_DSN）；"
            "不提供项目库默认值。",
        )
    config = ProbeConfig(
        checkpoint_dsn=dsn.replace("postgresql+psycopg://", "postgresql://"),
        corpus_root=Path(args.corpus_root),
        case_id=args.case,
        out_dir=Path(args.out),
        thread_id=args.thread,
        max_model_calls=args.max_model_calls,
        max_tool_calls=args.max_tool_calls,
        max_seconds=args.max_seconds,
        max_attempts=args.max_attempts,
    )
    if config.db_name in PROTECTED_DB_NAMES:
        raise ProbeError(
            "config", "protected_database",
            f"检查点目标 {config.db_name} 是受保护库，拒绝执行。",
        )
    if REQUIRED_DB_MARKER not in config.db_name:
        raise ProbeError(
            "config", "database_marker_missing",
            f"检查点目标 {config.db_name} 不是 C1 能力探针独占库"
            f"（库名必须包含 {REQUIRED_DB_MARKER}），拒绝执行。",
        )
    return config


def verify_live_database(config: ProbeConfig) -> str:
    """Connect and prove the live target really is the isolated database."""
    import psycopg

    try:
        with psycopg.connect(config.checkpoint_dsn, autocommit=True,
                             connect_timeout=10) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT current_database()")
                row = cur.fetchone()
    except ProbeError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ProbeError(
            "database", "connection_failed",
            f"隔离检查点库连接失败：{type(exc).__name__}",
        ) from exc
    actual = str(row[0]) if row else ""
    if actual != config.db_name or actual in PROTECTED_DB_NAMES:
        raise ProbeError(
            "database", "protected_database",
            f"实际连接的库 {actual!r} 与声明的隔离库不一致或受保护，拒绝执行。",
        )
    return actual


# ---------------------------------------------------------------------------
# Materials (hash-gated rebuild from the read-only corpus)
# ---------------------------------------------------------------------------

def load_case(config: ProbeConfig) -> tuple[Any, dict[str, Any]]:
    from scripts import m0_samples

    fixture_dir = config.out_dir / "samples"
    try:
        extraction = m0_samples.run_extraction(config.corpus_root, fixture_dir, "c1-capability")
    except Exception as exc:  # noqa: BLE001
        raise ProbeError(
            "materials", "corpus_unavailable",
            f"语料重建失败（{type(exc).__name__}）；C1 能力门必须使用真实样本。",
        ) from exc
    batch = json.loads((fixture_dir / "batch.json").read_text(encoding="utf-8"))
    case = next(
        (c for c in batch["cases"] if c["client_case_id"] == config.case_id), None
    )
    if case is None:
        raise ProbeError(
            "materials", "case_missing",
            f"case {config.case_id} 不在重建批次中。",
        )

    from app.lib.ai_runtime.adapters import RubricGenerationInput

    materials = RubricGenerationInput(
        task_prompt=case["task_prompt"],
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
    case_hash = hashlib.sha256(
        json.dumps(case, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()
    meta = {
        "case_id": config.case_id,
        "case_sha256": case_hash,
        "material_files": len(case.get("reference_examples") or [])
        + len(case.get("bad_cases") or [])
        + len(case.get("memory_materials") or []) + 2,
        "material_chars": sum(
            len(v) for v in materials.model_dump(mode="json").values() if isinstance(v, str)
        ),
        "sources_verified": extraction.get("sources_verified"),
    }
    return materials, meta


# ---------------------------------------------------------------------------
# Candidate model construction (LOCAL to C1; deleted by the C2 cutover)
# ---------------------------------------------------------------------------

def build_candidate_model(config_source: Any = None) -> tuple[Any, Any, dict[str, Any]]:
    """Native ChatOpenAI on the Responses protocol with encrypted reasoning.

    Explicit candidate combination under test — the production factory still
    forces Chat Completions until C2. No ``_generate`` override, no streaming
    parser, no message conversion is copied here: only HTTP configuration the
    current endpoint is known to require (telemetry header stripping, timeout,
    retry ceiling) is injected through the native client.
    """
    import httpx
    from langchain_openai import ChatOpenAI

    from app.lib.ai_runtime.model import (
        ModelConfigurationError,
        normalize_base_url,
        runtime_model_identity,
    )
    from app.lib.settings import Settings, settings

    cfg = config_source if config_source is not None else settings
    if not isinstance(cfg, Settings):
        raise ProbeError("model", "config_invalid", "探针只接受完整 Settings 配置快照。")
    try:
        identity = runtime_model_identity(cfg)
    except ModelConfigurationError as exc:
        raise ProbeError("model", "configuration_invalid", str(exc)) from exc
    if identity.provider != "openai":
        raise ProbeError(
            "model", "provider_unsupported",
            "C1 能力门只验证 OpenAI Responses 组合，当前配置不是 openai。",
        )
    effort = str(cfg.ai_reasoning_effort or "").strip().lower()
    if not effort:
        raise ProbeError(
            "model", "effort_missing",
            "AI_REASONING_EFFORT 为空：能力门的目标组合必须保留思考强度。",
        )

    def strip_provider_blocked_headers(request: httpx.Request) -> None:
        for header in list(request.headers):
            if header.lower().startswith("x-stainless-"):
                request.headers.pop(header, None)
        request.headers.pop("user-agent", None)

    model = ChatOpenAI(
        model=identity.model,
        api_key=cfg.ai_api_key.get_secret_value(),
        base_url=normalize_base_url(cfg.ai_base_url) or "https://api.openai.com/v1",
        streaming=True,
        max_retries=int(cfg.ai_model_retries),
        request_timeout=float(cfg.ai_request_timeout_seconds),
        use_responses_api=True,
        reasoning={"effort": effort},
        store=False,
        use_previous_response_id=False,
        include=["reasoning.encrypted_content"],
        http_client=httpx.Client(
            event_hooks={"request": [strip_provider_blocked_headers]},
        ),
    )
    model_summary = {
        "provider": identity.provider,
        "model": identity.model,
        "endpoint_fingerprint": identity.fingerprint,
        "protocol": "responses",
        "reasoning_effort": effort,
        "store": False,
        "use_previous_response_id": False,
        "include": ["reasoning.encrypted_content"],
    }
    return model, identity, model_summary


def _checkpoint_settings(config: ProbeConfig) -> Any:
    from pydantic import SecretStr

    from app.lib.settings import settings

    if not settings.langgraph_aes_key.get_secret_value():
        raise ProbeError("config", "checkpoint_key_missing", "LANGGRAPH_AES_KEY 未配置。")

    class _Cfg:
        checkpoint_database_url = SecretStr(config.checkpoint_dsn)
        langgraph_aes_key = settings.langgraph_aes_key

    return _Cfg()


# ---------------------------------------------------------------------------
# Sinks
# ---------------------------------------------------------------------------

class EvidenceSink:
    """Records redacted public-event facts: kinds, timings, counts.

    Text content is never stored — only its length — and every field passes
    the sensitive-marker gate before it is recorded.
    """

    def __init__(self, t0: float) -> None:
        self.t0 = t0
        self.kind_counts: dict[str, int] = {}
        self.stage_names: list[str] = []
        self.tool_events: list[tuple[str, str]] = []
        self.public_text_chars = 0
        self.first_delta_ms: int | None = None
        self.last_delta_ms: int | None = None
        self.first_tool_ms: int | None = None
        self.request_summaries: list[dict[str, Any]] = []

    def emit(self, event: Any) -> None:
        ms = round((time.monotonic() - self.t0) * 1000)
        leak = _public_event_violation([
            getattr(event, "stage", None), getattr(event, "text", None),
            getattr(event, "tool", None), getattr(event, "detail", None),
        ])
        if leak is not None:
            raise ProbeError(
                "stream", "public_stream_leak",
                f"公开事件包含敏感标记 {leak!r}，立即终止。",
            )
        kind = event.kind
        self.kind_counts[kind] = self.kind_counts.get(kind, 0) + 1
        stage_name = getattr(event, "stage", None)
        if stage_name:
            self.stage_names.append(str(stage_name))
        if kind == "message_delta":
            self.public_text_chars += len(event.text or "")
            if self.first_delta_ms is None:
                self.first_delta_ms = ms
            self.last_delta_ms = ms
        elif kind == "tool_started":
            if self.first_tool_ms is None:
                self.first_tool_ms = ms
            self.tool_events.append((str(event.tool or "?"), "started"))
        elif kind == "tool_finished":
            self.tool_events.append((str(event.tool or "?"), "finished"))
        elif kind == "tool_failed":
            self.tool_events.append((str(event.tool or "?"), "failed"))

    def summary(self, total_ms: int) -> dict[str, Any]:
        return {
            "total_ms": total_ms,
            "events_by_kind": dict(self.kind_counts),
            "tool_events": [f"{name}:{phase}" for name, phase in self.tool_events],
            "public_text_chars": self.public_text_chars,
            "first_delta_ms": self.first_delta_ms,
            "last_delta_ms": self.last_delta_ms,
            "first_tool_ms": self.first_tool_ms,
            "request_summaries": self.request_summaries,
        }


class InterruptingSink:
    """Wraps EvidenceSink and hard-exits at the planned interruption point.

    The interruption fires on the FIRST ``model_call_started`` stage event
    after at least one material tool round-trip has finished. With
    ``durability="sync"`` the tool-node superstep checkpoint is durable before
    the next model call starts, so ``os._exit`` here simulates a worker crash
    with a persisted tool round and NO completed graph. Exiting via
    ``os._exit`` skips finally/atexit teardown: the advisory lock dies with
    the connection, exactly like a real crash. ``exit_fn`` is injectable for
    offline tests only; production runs use the default hard exit.
    """

    def __init__(self, inner: EvidenceSink, exit_fn: Any = None) -> None:
        self.inner = inner
        self.exit_fn = exit_fn if exit_fn is not None else os._exit
        self.tool_round_trips = 0
        self.interrupted = False

    def emit(self, event: Any) -> None:
        self.inner.emit(event)
        if event.kind == "tool_finished":
            self.tool_round_trips += 1
        if (
            not self.interrupted
            and event.kind == "stage"
            and event.stage == "model_call_started"
            and self.tool_round_trips >= 1
        ):
            self.interrupted = True
            print(
                f"PROBE_STAGE=interrupt tool_round_trips={self.tool_round_trips} "
                f"exit={INTERRUPT_EXIT_CODE}",
                flush=True,
            )
            self.exit_fn(INTERRUPT_EXIT_CODE)


# ---------------------------------------------------------------------------
# Request capture (redacted structural summary only)
# ---------------------------------------------------------------------------

def _request_summary(request: Any) -> dict[str, Any]:
    try:
        payload = json.loads(request.content)
    except Exception:  # noqa: BLE001
        return {"parse_error": True}
    text_block = payload.get("text") or {}
    text_format = text_block.get("format") or {}
    return {
        "path": request.url.path,
        "stream": payload.get("stream"),
        "reasoning_effort": (payload.get("reasoning") or {}).get("effort"),
        "store": payload.get("store"),
        "include": payload.get("include"),
        "previous_response_id": payload.get("previous_response_id"),
        "tool_count": len(payload.get("tools") or []),
        "tool_names": sorted(t.get("name", "?") for t in payload.get("tools") or []),
        "tool_choice": payload.get("tool_choice"),
        "text_format_type": text_format.get("type"),
        "input_kinds": sorted({str(i.get("type")) for i in payload.get("input") or []}),
    }


def install_request_capture(model: Any, sink: EvidenceSink) -> None:
    client = getattr(model, "http_client", None)
    hooks = getattr(client, "event_hooks", None)
    if not isinstance(hooks, dict):
        raise ProbeError(
            "model", "capture_unavailable",
            "候选模型没有可注入的 httpx 客户端，无法采集请求摘要。",
        )

    def capture(request: Any) -> None:
        sink.request_summaries.append(_request_summary(request))

    hooks.setdefault("request", []).append(capture)


# ---------------------------------------------------------------------------
# Generation stages (each runs the PRODUCTION generator)
# ---------------------------------------------------------------------------

def _run_context(config: ProbeConfig, case_hash: str) -> Any:
    from app.lib.ai_runtime.adapters import RunContext

    return RunContext(
        thread_id=config.thread_id,
        operation_id=f"c1-op-{config.thread_id}",
        attempt_number=1,
        question_id=f"c1-{config.case_id}",
        materials_revision=1,
        materials_fingerprint=case_hash,
    )


def _budget(config: ProbeConfig) -> Any:
    from app.lib.ai_runtime.deep_runtime import RuntimeBudget

    return RuntimeBudget(
        max_model_calls=config.max_model_calls,
        max_tool_calls=config.max_tool_calls,
        max_total_seconds=config.max_seconds,
    )


def _generator(config: ProbeConfig, model: Any, identity: Any) -> Any:
    from app.lib.ai_runtime.adapters import DeepAgentRubricGenerator
    from app.lib.ai_runtime.deep_runtime import open_session

    checkpoint_cfg = _checkpoint_settings(config)

    def session_factory(context: Any) -> Any:
        return open_session(context.thread_id, checkpoint_cfg)

    return DeepAgentRubricGenerator(
        model=model,
        identity=identity,
        session_factory=session_factory,
        budget=_budget(config),
    )


def _result_summary(result: Any) -> dict[str, Any]:
    criteria = list(result.criteria)
    citations = 0
    teacher_claims = 0
    for item in criteria:
        for basis in (item.criterion_basis, item.pass_score_basis):
            for claim in basis.claims:
                if claim.citation is not None:
                    citations += 1
                if claim.kind == "teacher_explicit":
                    teacher_claims += 1
    return {
        "criteria": len(criteria),
        "anchors_total": sum(len(i.score_anchors) for i in criteria),
        "pass_scores": sorted(i.pass_score for i in criteria),
        "citations": citations,
        "teacher_explicit_claims": teacher_claims,
        "result_chars": len(result.model_dump_json()),
    }


def stage_full_run(config: ProbeConfig) -> dict[str, Any]:
    """L01: one uninterrupted real generation through the production adapter."""
    materials, case_meta = load_case(config)
    model, identity, model_summary = build_candidate_model()
    sink = EvidenceSink(time.monotonic())
    install_request_capture(model, sink)
    generator = _generator(config, model, identity)
    context = _run_context(config, case_meta["case_sha256"])

    t0 = time.monotonic()
    try:
        result = generator.generate(materials, context=context, sink=sink)
    except ProbeError:
        raise
    except Exception as exc:  # noqa: BLE001
        print(f"PROBE_STAGE=error stage=full_run {_describe_stage_error(exc)}", flush=True)
        raise ProbeError(
            "full_run", _error_category(exc),
            f"真实生成失败：{type(exc).__name__}",
        ) from exc
    total_ms = round((time.monotonic() - t0) * 1000)

    summary = sink.summary(total_ms)
    _assert_l01(config, summary, sink)
    return {
        "case": case_meta,
        "model": model_summary,
        "run": summary,
        "result": _result_summary(result),
    }


def _assert_l01(config: ProbeConfig, summary: dict[str, Any], sink: EvidenceSink) -> None:
    kinds = summary["events_by_kind"]
    if kinds.get("tool_finished", 0) < 1:
        raise ProbeError(
            "full_run", "no_tool_round_trip",
            "运行中没有发生真实材料工具读取与结果回送。",
        )
    if kinds.get("message_delta", 0) < 1 or summary["first_delta_ms"] is None:
        raise ProbeError(
            "full_run", "no_public_stream",
            "运行期间没有收到公开消息增量。",
        )
    if (
        summary["first_tool_ms"] is None
        or summary["last_delta_ms"] is None
        or summary["last_delta_ms"] <= summary["first_tool_ms"]
    ):
        raise ProbeError(
            "full_run", "stream_liveness",
            "工具轮之后没有继续收到公开增量，流式活性不成立。",
        )
    if not sink.request_summaries:
        raise ProbeError(
            "full_run", "no_request_captured",
            "没有捕获到任何 HTTP 请求摘要，无法证明协议组合。",
        )
    first = sink.request_summaries[0]
    if not str(first.get("path", "")).endswith("/responses"):
        raise ProbeError(
            "full_run", "protocol_mismatch",
            f"首个请求路径不是 /responses：{first.get('path')}",
        )
    if first.get("reasoning_effort") != _expected_effort():
        raise ProbeError(
            "full_run", "effort_mismatch",
            f"请求思考强度 {first.get('reasoning_effort')!r} 与目标 {_expected_effort()!r} 不一致。",
        )
    if first.get("store") is not False or first.get("include") != ["reasoning.encrypted_content"]:
        raise ProbeError(
            "full_run", "history_policy_mismatch",
            "请求没有使用客户端历史策略（store=false + encrypted reasoning include）。",
        )
    if first.get("previous_response_id") is not None:
        raise ProbeError(
            "full_run", "server_session_dependency",
            "请求依赖服务端会话（previous_response_id），违反能力门约束。",
        )
    if first.get("text_format_type") != "json_schema":
        raise ProbeError(
            "full_run", "schema_strategy_mismatch",
            f"结构化输出不是原生 JSON Schema：{first.get('text_format_type')!r}",
        )
    tool_names = first.get("tool_names") or []
    if not tool_names or "read_file" not in tool_names:
        raise ProbeError(
            "full_run", "tools_missing",
            f"请求工具集合缺少材料文件工具：{tool_names}",
        )
    if "execute" in tool_names or "task" in tool_names:
        raise ProbeError(
            "full_run", "restricted_tools_leaked",
            f"被禁工具出现在模型请求中：{tool_names}",
        )
    for summary_item in sink.request_summaries:
        if not str(summary_item.get("path", "")).endswith("/responses"):
            raise ProbeError(
                "full_run", "protocol_mismatch",
                f"后续请求偏离 Responses 协议：{summary_item.get('path')}",
            )


def _expected_effort() -> str:
    from app.lib.settings import settings

    return str(settings.ai_reasoning_effort or "").strip().lower()


def _error_category(exc: BaseException) -> str:
    """Whitelisted, non-secret error category for the evidence report."""
    from app.lib.ai_runtime.adapters import RubricGenerationFailure
    from app.lib.ai_runtime.deep_runtime import BudgetExceededError, DeepRuntimeError

    if isinstance(exc, BudgetExceededError):
        return "budget_exceeded"
    if isinstance(exc, (RubricGenerationFailure, DeepRuntimeError)):
        return f"generation_failure:{exc.code}"
    name = type(exc).__name__
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if status is not None:
        return f"http_{status}"
    mapping = {
        "ModelInvalidRequestError": "model_invalid_request",
        "AuthenticationError": "authentication",
        "PermissionDeniedError": "permission_denied",
        "NotFoundError": "not_found",
        "RateLimitError": "rate_limit",
        "APIConnectionError": "connection",
        "APITimeoutError": "timeout",
        "InternalServerError": "server",
        "BudgetExceededError": "budget_exceeded",
        "DeepRuntimeError": "deep_runtime",
        "RubricGenerationFailure": "generation_failure",
    }
    return mapping.get(name, "unknown")


# Categories that represent TRANSIENT provider/content outcomes: the production
# Worker treats these as retryable job attempts that resume from the same
# checkpoint (e.g. the model sampled a final structured output that violates a
# cross-field pydantic validator the wire JSON Schema cannot express —
# StructuredOutputValidationError surfaces as AI_CALL_FAILED). The probe
# re-attempts a stage within its bound exactly like the Worker's attempt
# budget; contract/capability violations are NEVER retried.
_TRANSIENT_CATEGORIES = frozenset({
    "generation_failure:AI_CALL_FAILED",
    "generation_failure:AI_OUTPUT_EMPTY",
    "generation_failure:AI_OUTPUT_INVALID",
    "generation_failure:AI_CITATION_INVALID",
    "http_429", "http_500", "http_502", "http_503", "http_504",
    "rate_limit", "connection", "timeout", "server",
})


def _is_transient(category: str) -> bool:
    return category in _TRANSIENT_CATEGORIES


def _run_stage_bounded(
    stage: str,
    fn: Any,
    *,
    max_attempts: int,
    between_attempts: Any = None,
) -> tuple[dict[str, Any], int]:
    """Run one stage with a bounded number of attempts.

    Mirrors the production attempt budget: a transient provider/content
    failure re-runs the SAME stage on the SAME thread and contract (the
    checkpoint makes this a continuation, never a restart with duplicated
    input). Non-transient failures — capability/contract violations — fail
    immediately. Returns ``(payload, attempts_used)``.
    """
    attempts = 0
    while True:
        attempts += 1
        try:
            return fn(), attempts
        except ProbeError as exc:
            if not _is_transient(exc.category) or attempts >= max_attempts:
                raise
            print(
                f"PROBE_STAGE=transient_retry stage={stage} attempt={attempts} "
                f"category={exc.category}",
                flush=True,
            )
            if between_attempts is not None:
                between_attempts()


def _describe_stage_error(exc: BaseException) -> str:
    """Console-only diagnostic: safe code/message plus the cause's TYPE.

    ``RubricGenerationFailure``/``DeepRuntimeError`` messages are
    safe-to-display by contract; the raw provider cause is never printed —
    only its exception class and (when present) HTTP status. The persisted
    evidence keeps only the whitelisted category.
    """
    from app.lib.ai_runtime.adapters import RubricGenerationFailure
    from app.lib.ai_runtime.deep_runtime import DeepRuntimeError

    parts = [f"type={type(exc).__name__}"]
    if isinstance(exc, (RubricGenerationFailure, DeepRuntimeError)):
        parts.append(f"code={exc.code}")
        parts.append(f"retryable={exc.retryable}")
        parts.append(f"message={str(exc.message)[:400]}")
    cause = exc.__cause__
    if cause is not None:
        status = getattr(getattr(cause, "response", None), "status_code", None)
        parts.append(f"cause={type(cause).__name__}" + (f"({status})" if status else ""))
    return " ".join(parts)


def stage_interrupted_run(config: ProbeConfig) -> dict[str, Any]:
    """Run child: real generation, hard-killed after a durable tool round."""
    materials, case_meta = load_case(config)
    model, identity, _summary = build_candidate_model()
    sink = EvidenceSink(time.monotonic())
    interrupting = InterruptingSink(sink)
    generator = _generator(config, model, identity)
    context = _run_context(config, case_meta["case_sha256"])
    print(f"PROBE_STAGE=run_child thread={config.thread_id}", flush=True)
    try:
        generator.generate(materials, context=context, sink=interrupting)
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        _fail("run_child", _error_category(exc), f"中断前运行失败：{type(exc).__name__}")
    # Completing without hitting the interruption point means the model never
    # produced a resumable mid-run checkpoint — the recovery evidence would be
    # fake, so this is a loud failure, not a pass.
    _fail(
        "run_child", "interruption_missed",
        "运行在未触发计划中断点的情况下完成，无法证明工具轮后恢复。",
    )
    raise AssertionError("unreachable")


def stage_resume(config: ProbeConfig) -> dict[str, Any]:
    """Resume child: same thread/contract/budget, ``inputs=None`` continuation."""
    from app.lib.ai_runtime import deep_runtime as dr

    materials, case_meta = load_case(config)
    model, identity, model_summary = build_candidate_model()
    sink = EvidenceSink(time.monotonic())
    install_request_capture(model, sink)
    generator = _generator(config, model, identity)
    context = _run_context(config, case_meta["case_sha256"])

    t0 = time.monotonic()
    try:
        result = generator.generate(materials, context=context, sink=sink)
    except ProbeError:
        raise
    except Exception as exc:  # noqa: BLE001
        print(f"PROBE_STAGE=error stage=resume {_describe_stage_error(exc)}", flush=True)
        raise ProbeError(
            "resume", _error_category(exc),
            f"恢复运行失败：{type(exc).__name__}",
        ) from exc
    total_ms = round((time.monotonic() - t0) * 1000)

    if "thread_state_incomplete" not in sink.stage_names:
        raise ProbeError(
            "resume", "not_resumed",
            f"恢复阶段没有走 incomplete 续跑路径，实际阶段：{sink.stage_names[:8]}",
        )

    # Structural checkpoint inspection: exactly ONE initial input, tool
    # history present, no duplicate resubmission.
    checkpoint_cfg = _checkpoint_settings(config)
    session = dr.open_session(config.thread_id, checkpoint_cfg)
    try:
        counters = dr.BudgetCounters()
        inspector = dr.build_restricted_agent(
            _no_call_model(), identity,
            system_prompt="inspector",
            budget=_budget(config), counters=counters, sink=dr.ListSink(),
            checkpointer=session.saver,
        )
        state = inspector.get_state(session.thread_config())
        messages = list((getattr(state, "values", None) or {}).get("messages") or [])
    finally:
        session.close()

    initial_inputs = sum(
        1 for m in messages
        if getattr(m, "type", None) == "human"
        and "请核查本题材料并起草完整评分维度候选集" in str(getattr(m, "content", ""))
    )
    tool_messages = sum(1 for m in messages if getattr(m, "type", None) == "tool")
    if initial_inputs != 1:
        raise ProbeError(
            "resume", "duplicate_initial_input",
            f"恢复后初始输入出现 {initial_inputs} 次（必须恰好 1 次）。",
        )
    if tool_messages < 1:
        raise ProbeError(
            "resume", "tool_history_missing",
            "恢复后的检查点里没有工具消息历史。",
        )

    summary = sink.summary(total_ms)
    resumed_requests = summary["request_summaries"]
    if resumed_requests:
        first = resumed_requests[0]
        if not str(first.get("path", "")).endswith("/responses"):
            raise ProbeError(
                "resume", "protocol_mismatch",
                f"恢复请求偏离 Responses 协议：{first.get('path')}",
            )
        if first.get("reasoning_effort") != _expected_effort():
            raise ProbeError(
                "resume", "effort_mismatch",
                "恢复请求的思考强度与中断前不一致。",
            )
        kinds = {str(i) for i in first.get("input_kinds") or []}
        if "function_call_output" not in kinds:
            raise ProbeError(
                "resume", "tool_history_not_round_tripped",
                f"恢复后的首个请求没有携带工具结果历史：{sorted(kinds)}",
            )
    return {
        "case": case_meta,
        "model": model_summary,
        "resume": summary,
        "checkpoint": {
            "message_count": len(messages),
            "initial_input_count": initial_inputs,
            "tool_message_count": tool_messages,
        },
        "result": _result_summary(result),
    }


def _no_call_model() -> Any:
    from langchain_core.language_models.fake_chat_models import GenericFakeChatModel

    class _NoCallModel(GenericFakeChatModel):
        def bind_tools(self, tools: Any, **kwargs: Any) -> "_NoCallModel":
            return self

    return _NoCallModel(messages=iter([]))


def stage_reread(config: ProbeConfig) -> dict[str, Any]:
    """Completed-thread re-read: ZERO model calls, result re-validated."""
    from app.lib.ai_runtime import deep_runtime as dr

    materials, case_meta = load_case(config)
    _model, identity, _summary = build_candidate_model()
    sink = EvidenceSink(time.monotonic())
    # Reread must not touch the provider: a no-call fake model would raise
    # StopIteration loudly if the generator tried any model call. The identity
    # stays the real one so the restricted profile registration matches.
    generator = _generator(config, _no_call_model(), identity)
    context = _run_context(config, case_meta["case_sha256"])

    try:
        result = generator.generate(materials, context=context, sink=sink)
    except ProbeError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ProbeError(
            "reread", _error_category(exc),
            f"完成态重读失败（若为空迭代器 StopIteration 说明发生了模型调用）：{type(exc).__name__}",
        ) from exc

    if "thread_state_complete" not in sink.stage_names:
        raise ProbeError(
            "reread", "not_complete",
            f"重读阶段线程不是 complete 状态：{sink.stage_names[:8]}",
        )
    if sink.kind_counts.get("message_delta", 0) or any(
        stage == "model_call_started" for stage in sink.stage_names
    ):
        raise ProbeError(
            "reread", "model_called_on_reread",
            "完成态重读期间发生了模型调用。",
        )
    return {
        "case": {"case_id": case_meta["case_id"], "case_sha256": case_meta["case_sha256"]},
        "reread": sink.summary(0),
        "result": _result_summary(result),
    }


def stage_cleanup(config: ProbeConfig) -> dict[str, Any]:
    """Model-free cleanup of the probe thread; verify zero residue."""
    from app.lib.ai_runtime import deep_runtime as dr

    checkpoint_cfg = _checkpoint_settings(config)
    session = dr.open_session(config.thread_id, checkpoint_cfg)
    try:
        residue = dr.delete_thread_data(session)
    finally:
        session.close()
    if any(value != 0 for value in residue.values()):
        raise ProbeError(
            "cleanup", "residue",
            f"清理后仍有残留：{residue}",
        )
    return {"residue": residue}


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def _stage_child_args(config: ProbeConfig, stage: str) -> list[str]:
    return [
        sys.executable, "-m", "scripts.probe_ai_harness_capability",
        "--execute", "--stage", stage,
        "--checkpoint-dsn", config.checkpoint_dsn,
        "--corpus-root", str(config.corpus_root),
        "--case", config.case_id,
        "--out", str(config.out_dir),
        "--thread", config.thread_id,
        "--max-model-calls", str(config.max_model_calls),
        "--max-tool-calls", str(config.max_tool_calls),
        "--max-seconds", str(config.max_seconds),
    ]


def _spawn_stage(config: ProbeConfig, stage: str, expect_code: int = 0) -> int:
    print(f"PROBE_STAGE=spawn:{stage}", flush=True)
    completed = subprocess.run(
        _stage_child_args(config, stage),
        cwd=str(BACKEND_ROOT),
        timeout=int(config.max_seconds) + 300,
    )
    if completed.returncode != expect_code:
        _fail(
            stage, "stage_exit",
            f"{stage} 子进程退出码 {completed.returncode}（期望 {expect_code}）。",
        )
    return completed.returncode


def _evidence_base(config: ProbeConfig) -> dict[str, Any]:
    try:
        git_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True,
            timeout=10, cwd=str(BACKEND_ROOT),
        ).stdout.strip()
    except Exception:  # noqa: BLE001
        git_sha = "unknown"
    return {
        "probe": "c1-capability",
        "run_identity": {
            "git_sha": git_sha,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "sdk_versions": {
                "deepagents": md.version("deepagents"),
                "langchain": md.version("langchain"),
                "langchain_core": md.version("langchain-core"),
                "langchain_openai": md.version("langchain-openai"),
                "langgraph": md.version("langgraph"),
                "langgraph_checkpoint_postgres": md.version("langgraph-checkpoint-postgres"),
                "openai": md.version("openai"),
                "psycopg": md.version("psycopg"),
            },
            "checkpoint_db": config.db_name,
            "thread_id": config.thread_id,
        },
        "budget": {
            "max_model_calls": config.max_model_calls,
            "max_tool_calls": config.max_tool_calls,
            "max_total_seconds": config.max_seconds,
            "max_stage_attempts": config.max_attempts,
        },
    }


def run_dry(config_source: Any) -> dict[str, Any]:
    """Redacted precheck only: configuration, corpus, protected-name guard.

    Never connects to a database, never issues a model request.
    """
    from app.lib.ai_runtime.model import (
        ModelConfigurationError,
        runtime_model_identity,
    )

    report: dict[str, Any] = {"mode": "dry-run"}
    try:
        identity = runtime_model_identity(config_source, require_credentials=False)
        report["model"] = {
            "provider": identity.provider,
            "model": identity.model,
            "endpoint_fingerprint": identity.fingerprint,
            "base_url_set": bool(identity.base_url),
            "reasoning_effort": str(config_source.ai_reasoning_effort or "").strip().lower(),
        }
    except ModelConfigurationError as exc:
        report["model"] = {"error": str(exc)}
    try:
        from scripts import m0_samples

        fixture_dir = config_source._c1_dry_fixture_dir  # type: ignore[attr-defined]
        extraction = m0_samples.run_extraction(
            config_source._c1_corpus_root,  # type: ignore[attr-defined]
            fixture_dir, "c1-capability-dry",
        )
        report["corpus"] = {
            "sources_verified": extraction.get("sources_verified"),
            "batch_cases": extraction.get("batch_cases"),
            "fixture_dir": str(fixture_dir),
        }
    except Exception as exc:  # noqa: BLE001
        report["corpus"] = {"error": f"{type(exc).__name__}: {exc}"}
    report["protected_db_guard"] = sorted(PROTECTED_DB_NAMES)
    report["database"] = "dry-run 不连接任何数据库"
    report["network"] = "dry-run 不发起任何模型请求"
    return report


def run_execute(config: ProbeConfig) -> int:
    config.out_dir.mkdir(parents=True, exist_ok=True)
    verify_live_database(config)
    evidence = _evidence_base(config)

    # Fresh thread for every capability run: the whole sequence (full run,
    # interrupted run, resume, reread, cleanup) owns its checkpoint state.
    pre_clean = stage_cleanup(config)
    evidence["pre_cleanup"] = pre_clean

    print("PROBE_STAGE=full_run", flush=True)
    try:
        # A transient content/provider failure re-runs the full generation on
        # a CLEANED thread (bounded, like the Worker's attempt budget); the
        # attempt count is part of the honest evidence.
        full_run, full_run_attempts = _run_stage_bounded(
            "full_run",
            lambda: stage_full_run(config),
            max_attempts=config.max_attempts,
            between_attempts=lambda: stage_cleanup(config),
        )
        evidence["full_run"] = full_run
        evidence["full_run_attempts"] = full_run_attempts
    except ProbeError as exc:
        _write_evidence(config, evidence, verdict=f"FAIL:{exc.stage}:{exc.category}")
        _fail(exc.stage, exc.category, exc.message)
    # The full run completed the graph on this thread; clean before the
    # interrupt/resume sequence so the recovery evidence is unambiguous.
    evidence["post_full_run_cleanup"] = stage_cleanup(config)

    print("PROBE_STAGE=interrupt_resume", flush=True)
    try:
        _spawn_stage(config, "run-child", expect_code=INTERRUPT_EXIT_CODE)
        # Resume re-attempts continue from the SAME checkpoint with the same
        # contract and budget — exactly the production retryable-attempt path.
        resume, resume_attempts = _run_stage_bounded(
            "resume", lambda: stage_resume(config), max_attempts=config.max_attempts,
        )
        evidence["resume"] = resume
        evidence["resume_attempts"] = resume_attempts
        evidence["interrupt"] = {"child_exit_code": INTERRUPT_EXIT_CODE}
        evidence["reread"] = stage_reread(config)
        evidence["cleanup"] = stage_cleanup(config)
    except subprocess.TimeoutExpired:
        _write_evidence(config, evidence, verdict="FAIL:run-child:timeout")
        _fail("run-child", "timeout", "中断子进程超时。")
    except ProbeError as exc:
        _write_evidence(config, evidence, verdict=f"FAIL:{exc.stage}:{exc.category}")
        _fail(exc.stage, exc.category, exc.message)

    evidence_path = _write_evidence(config, evidence, verdict="PASS")
    print(f"PROBE=PASS evidence={evidence_path}")
    return 0


def _write_evidence(config: ProbeConfig, evidence: dict[str, Any], *, verdict: str) -> Path:
    evidence["verdict"] = verdict
    blob = json.dumps(evidence, ensure_ascii=False, indent=2)
    violation = _evidence_secret_violation(blob)
    if violation is not None:
        # Never persist evidence that failed the redaction gate.
        _fail("evidence", "redaction_violation", f"证据包含敏感值 {violation!r}，拒绝写入。")
    path = config.out_dir / "c1-capability-evidence.json"
    path.write_text(blob, encoding="utf-8")
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "环境合同：\n"
            "  C1_CHECKPOINT_DSN  隔离检查点库 DSN（库名必须包含 c1_capability，\n"
            "                     项目库 blue_benchmark / blue_benchmark_checkpoint 被拒绝）\n"
            "  AI_*               模型配置读取本地 gitignored .env（不在报告中输出）\n"
            "默认 dry-run 只做脱敏预检；--execute 才会调用真实模型。\n"
            "内部 --stage 参数供编排子进程使用，不接受手工调用。"
        ),
    )
    parser.add_argument("--execute", action="store_true",
                        help="真实执行能力门（需要实施批准与隔离 DSN）")
    parser.add_argument(
        "--stage",
        choices=["run-child", "full-run", "resume", "reread", "cleanup"],
        default=None,
        help="单独执行一个阶段（编排/诊断用；完整能力门请不带 --stage 运行）",
    )
    parser.add_argument("--checkpoint-dsn", default=None)
    parser.add_argument(
        "--corpus-root",
        default=str(BACKEND_ROOT.parent / ".local-samples" / "m0"),
    )
    parser.add_argument("--case", default="m0-real-m-mega-press-release")
    parser.add_argument("--out", default="storage/acceptance/c1-capability")
    parser.add_argument("--thread", default=DEFAULT_THREAD)
    parser.add_argument("--max-model-calls", type=int, default=24)
    parser.add_argument("--max-tool-calls", type=int, default=120)
    parser.add_argument("--max-seconds", type=float, default=1800.0)
    parser.add_argument(
        "--max-attempts", type=int, default=3,
        help="单阶段对瞬时 Provider/内容失败的有限重试上限（同一线程与合同，"
             "镜像生产 Worker attempt 语义；合同/能力违规永不重试）",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if not args.execute:
        from app.lib.settings import settings

        dry_holder = SimpleSettings(settings, Path(args.corpus_root), Path(args.out) / "samples-dry")
        report = run_dry(dry_holder)
        blob = json.dumps(report, ensure_ascii=False, indent=2)
        violation = _evidence_secret_violation(blob)
        if violation is not None:
            _fail("dry-run", "redaction_violation", f"预检输出包含敏感值 {violation!r}。")
        print(blob)
        print("PROBE=DRY_RUN_OK（未发起任何模型请求；--execute 才会真实运行）")
        return 0

    try:
        config = resolve_config(args)
    except ProbeError as exc:
        _fail(exc.stage, exc.category, exc.message)
        raise AssertionError("unreachable") from exc
    if args.stage is not None:
        stage_functions = {
            "run-child": stage_interrupted_run,
            "full-run": stage_full_run,
            "resume": stage_resume,
            "reread": stage_reread,
            "cleanup": stage_cleanup,
        }
        try:
            payload = stage_functions[args.stage](config)
        except ProbeError as exc:
            _fail(exc.stage, exc.category, exc.message)
            raise AssertionError("unreachable") from exc
        print(json.dumps({f"stage_{args.stage}": payload}, ensure_ascii=False, indent=2))
        return 0
    try:
        return run_execute(config)
    except ProbeError as exc:
        _fail(exc.stage, exc.category, exc.message)
        raise AssertionError("unreachable") from exc


class SimpleSettings:
    """Dry-run holder: real Settings plus corpus paths, nothing mutated."""

    def __init__(self, settings_obj: Any, corpus_root: Path, fixture_dir: Path) -> None:
        self._settings = settings_obj
        self._c1_corpus_root = corpus_root
        self._c1_dry_fixture_dir = fixture_dir

    def __getattr__(self, name: str) -> Any:
        return getattr(self._settings, name)


if __name__ == "__main__":
    sys.exit(main())
