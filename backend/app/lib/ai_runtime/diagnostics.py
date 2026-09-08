"""Whitelisted AI runtime diagnostics.

One serialization function, one record shape. Every AI-side failure that
reaches the worker boundary is recorded here with a bounded set of
non-secret fields, through standard ``logging`` to BOTH the existing service
log (stderr) and a rotating JSON-lines file under the backend storage tree:

* local:     ``backend/storage/runtime/ai-diagnostics.jsonl``
* container: ``/app/storage/runtime/ai-diagnostics.jsonl`` (appdata volume)

The path is derived from this module's location (the same convention the
business-database default uses), NOT from the repository PROJECT_ROOT: the
container image packs the backend flat, so the repository root does not
exist there.

Never recorded: raw provider messages, materials, headers, full URLs, raw
tool payloads, private reasoning, credentials or ``str(exc)`` of arbitrary
exceptions. Unknown errors are classified as ``unknown``; an unresolvable
contract is recorded as fingerprint ``unavailable`` — never disguised as a
default identity. A failing diagnostics file must not mask the original
failure: file errors fall back to stderr only.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DIAGNOSTICS_LOGGER_NAME = "ai_runtime.diagnostics"
RELATIVE_LOG_PATH = Path("runtime") / "ai-diagnostics.jsonl"
MAX_BYTES = 5 * 1024 * 1024
BACKUP_COUNT = 1

# Whitelisted record fields — the ONLY keys this module ever serializes.
RECORD_FIELDS: tuple[str, ...] = (
    "timestamp",
    "event",
    "stage",
    "category",
    "http_status",
    "param",
    "request_id",
    "retryable",
    "contract_fingerprint",
    "provider",
    "model",
    "endpoint_fingerprint",
    "protocol",
    "reasoning_effort",
    "output_strategy",
    "harness_policy_version",
    "operation_id",
    "question_id",
    "attempt",
    "thread_id",
)

# An exception type name is a code identifier; anything that does not look
# like one is not whitelisted into the record.
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]{0,63}$")
_SAFE_PARAM = re.compile(r"^[A-Za-z0-9_.\[\]-]{1,64}$")
# Internal correlation ids (operation/question/thread) are server-generated
# UUIDs and derived ids — no secrets, but they contain digits and dashes.
_SAFE_CORRELATION_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")

# Exception class names with a stable diagnostic meaning, checked across the
# whole cause chain (LangChain wraps provider SDK errors; the wrapper alone
# would hide the real category).
_KNOWN_CATEGORY_BY_NAME = {
    "ModelInvalidRequestError": "model_invalid_request",
    "BadRequestError": "model_invalid_request",
    "ModelAuthenticationError": "authentication",
    "AuthenticationError": "authentication",
    "ModelPermissionDeniedError": "permission_denied",
    "PermissionDeniedError": "permission_denied",
    "ModelNotFoundError": "model_not_found",
    "NotFoundError": "model_not_found",
    "ModelRateLimitError": "rate_limit",
    "RateLimitError": "rate_limit",
    "ModelTimeoutError": "timeout",
    "APITimeoutError": "timeout",
    "ModelConnectionError": "connection",
    "APIConnectionError": "connection",
    "InternalServerError": "server",
    "ModelAPIError": "provider_api",
    "APIStatusError": "provider_api",
    "StructuredOutputValidationError": "structured_output_validation",
    "BudgetExceededError": "budget_exceeded",
    "ModelConfigurationError": "configuration_invalid",
    "ContractConfigurationError": "configuration_invalid",
    "DeepRuntimeError": "deep_runtime",
    "RubricGenerationFailure": "generation_failure",
}

_MAX_CAUSE_DEPTH = 8


def storage_root() -> Path:
    """Backend storage root, container-safe (see module docstring)."""

    return Path(__file__).resolve().parents[3] / "storage"


def diagnostics_log_path() -> Path:
    return storage_root() / RELATIVE_LOG_PATH


def get_diagnostics_logger() -> logging.Logger:
    """The single diagnostics logger (stderr + rotating JSONL file).

    Handlers are attached once. The file handler is best-effort: if the
    storage tree is not writable the logger still reports to stderr, because
    losing diagnostics must never change failure semantics.
    """

    logger = logging.getLogger(DIAGNOSTICS_LOGGER_NAME)
    # Alembic's fileConfig (migrations) and other logging.config users run
    # with disable_existing_loggers=True by default and silently disable
    # this logger. Operational diagnostics must survive that, so every
    # access re-enables it.
    logger.disabled = False
    if getattr(logger, "_ai_diagnostics_configured", False):
        return logger
    logger.setLevel(logging.INFO)
    logger.propagate = False
    formatter = logging.Formatter("%(message)s")

    stderr_handler = logging.StreamHandler()
    stderr_handler.setFormatter(formatter)
    logger.addHandler(stderr_handler)

    try:
        from logging.handlers import RotatingFileHandler

        path = diagnostics_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            path, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except OSError:
        # Unwritable storage: stderr diagnostics still happen; the original
        # failure semantics are untouched.
        pass
    logger._ai_diagnostics_configured = True  # type: ignore[attr-defined]
    return logger


def _safe_identifier(value: Any) -> str | None:
    text = str(value or "")
    return text if _SAFE_IDENTIFIER.match(text) else None


def _safe_correlation_id(value: Any) -> str | None:
    text = str(value or "")
    return text if _SAFE_CORRELATION_ID.match(text) else None


def _walk_causes(exc: BaseException) -> list[BaseException]:
    chain = [exc]
    seen = {id(exc)}
    current = exc
    for _ in range(_MAX_CAUSE_DEPTH):
        current = current.__cause__ or current.__context__
        if current is None or id(current) in seen:
            break
        seen.add(id(current))
        chain.append(current)
    return chain


def classify_exception(exc: BaseException) -> dict[str, Any]:
    """Whitelisted classification of an exception chain.

    Returns ``category`` (stable machine name or ``unknown``), ``http_status``
    and ``request_id`` when the provider error carries them, the offending
    ``param`` name when the server reported one (e.g. ``reasoning_effort``
    for the incident 400), and ``retryable`` from the standard LangChain
    ``ModelError`` semantics when available.

    The chain is walked DEEPEST-CAUSE-FIRST for the category: business
    wrappers (RubricGenerationFailure/DeepRuntimeError) sit on the surface
    and would otherwise hide the actionable provider classification. When
    the winner is a wrapper, its machine code is appended so the record
    stays precise (``generation_failure:AI_CITATION_INVALID``).
    """

    category = "unknown"
    http_status: int | None = None
    param: str | None = None
    request_id: str | None = None
    retryable: bool | None = None

    chain = _walk_causes(exc)
    for candidate in reversed(chain):
        name = type(candidate).__name__
        if name in _KNOWN_CATEGORY_BY_NAME:
            category = _KNOWN_CATEGORY_BY_NAME[name]
            if category in ("generation_failure", "deep_runtime"):
                code = getattr(candidate, "code", None)
                if code is not None and _SAFE_PARAM.match(str(code)):
                    category = f"{category}:{code}"
            break

    for candidate in chain:
        response = getattr(candidate, "response", None)
        status = getattr(response, "status_code", None)
        if http_status is None and isinstance(status, int):
            http_status = status
        body = getattr(candidate, "body", None)
        if param is None and isinstance(body, dict):
            error_body = body.get("error")
            if isinstance(error_body, dict):
                raw_param = error_body.get("param")
                if raw_param is not None and _SAFE_PARAM.match(str(raw_param)):
                    param = str(raw_param)
        if request_id is None:
            headers = getattr(response, "headers", None)
            if isinstance(headers, dict):
                raw_request_id = headers.get("x-request-id") or headers.get("request-id")
                if raw_request_id and _SAFE_PARAM.match(str(raw_request_id)):
                    request_id = str(raw_request_id)
        if retryable is None:
            flag = getattr(candidate, "is_retryable", None)
            if isinstance(flag, bool):
                retryable = flag

    if category == "unknown":
        # A code identifier is safe to record; anything else stays unknown.
        category = _safe_identifier(type(exc).__name__) or "unknown"
    return {
        "category": category,
        "http_status": http_status,
        "param": param,
        "request_id": request_id,
        "retryable": retryable,
    }


def build_diagnostic_record(
    *,
    event: str,
    stage: str,
    exception: BaseException | None = None,
    category: str | None = None,
    contract: Any = None,
    operation_id: str | None = None,
    question_id: str | None = None,
    attempt: int | None = None,
    thread_id: str | None = None,
) -> dict[str, Any]:
    """Serialize ONE whitelisted diagnostics record (never raises).

    ``contract`` is a ``ResolvedHarnessContract`` or None; None records the
    fingerprint as ``unavailable`` instead of inventing a default identity.
    """

    record: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": _safe_identifier(event) or "ai_failure",
        "stage": _safe_identifier(stage) or "unknown",
        "category": "unknown",
        "http_status": None,
        "param": None,
        "request_id": None,
        "retryable": None,
        "contract_fingerprint": "unavailable",
        "provider": None,
        "model": None,
        "endpoint_fingerprint": None,
        "protocol": None,
        "reasoning_effort": None,
        "output_strategy": None,
        "harness_policy_version": None,
        "operation_id": _safe_correlation_id(operation_id),
        "question_id": _safe_correlation_id(question_id),
        "attempt": attempt if isinstance(attempt, int) else None,
        "thread_id": _safe_correlation_id(thread_id),
    }
    if exception is not None:
        try:
            classified = classify_exception(exception)
        except Exception:  # noqa: BLE001 - diagnostics must never raise
            classified = {"category": "unknown", "http_status": None,
                          "param": None, "request_id": None, "retryable": None}
        record.update(classified)
    if category is not None:
        record["category"] = _safe_identifier(category) or "unknown"
    if contract is not None:
        try:
            identity = contract.diagnostics_identity()
            record["contract_fingerprint"] = identity["contract_fingerprint"]
            record["provider"] = identity["provider"]
            record["model"] = identity["model"]
            record["endpoint_fingerprint"] = identity["endpoint_fingerprint"]
            record["protocol"] = identity["protocol"]
            record["reasoning_effort"] = identity["reasoning_effort"]
            record["output_strategy"] = identity["output_strategy"]
            record["harness_policy_version"] = identity["harness_policy_version"]
        except Exception:  # noqa: BLE001
            record["contract_fingerprint"] = "unavailable"
    return {key: record[key] for key in RECORD_FIELDS}


def record_ai_failure(
    *,
    stage: str,
    exception: BaseException | None = None,
    category: str | None = None,
    contract: Any = None,
    operation_id: str | None = None,
    question_id: str | None = None,
    attempt: int | None = None,
    thread_id: str | None = None,
) -> dict[str, Any]:
    """Build, log and return ONE diagnostics record. Never raises."""

    record = build_diagnostic_record(
        event="ai_failure",
        stage=stage,
        exception=exception,
        category=category,
        contract=contract,
        operation_id=operation_id,
        question_id=question_id,
        attempt=attempt,
        thread_id=thread_id,
    )
    try:
        get_diagnostics_logger().error(json.dumps(record, ensure_ascii=False))
    except Exception:  # noqa: BLE001 - a dead logger must not mask the failure
        pass
    return record


__all__ = [
    "BACKUP_COUNT",
    "DIAGNOSTICS_LOGGER_NAME",
    "MAX_BYTES",
    "RECORD_FIELDS",
    "build_diagnostic_record",
    "classify_exception",
    "diagnostics_log_path",
    "get_diagnostics_logger",
    "record_ai_failure",
    "storage_root",
]
