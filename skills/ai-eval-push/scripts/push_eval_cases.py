#!/usr/bin/env python3
"""Deterministic client for pushing evaluation cases to the platform.

This script is the mechanical half of the ``ai-eval-push`` skill. The agent
organizes candidate questions and teacher confirmation; this script only:

  * reads the API base URL and scene credential from the environment,
  * strictly validates a batch payload against the six-material contract,
  * applies the same privacy backstop the server enforces,
  * generates or reuses a stable ``command_id``,
  * performs the HTTP call and normalizes the result.

It never prints material bodies or the credential token. Python 3.10+ standard
library only — no third-party dependencies.

Commands:
  connection                  Verify the credential and show the bound scene.
  validate --batch-file F     Validate a local batch draft; do not upload.
  push --batch-file F         Validate then upload (idempotent on replay).
            [--command-id ID] Pin an explicit command id (default: derived
                              deterministically from the payload).
            [--dry-run]       Validate and show the derived command id only.

Environment:
  AI_EVAL_BASE_URL      e.g. http://127.0.0.1:8000
  AI_EVAL_ACCESS_TOKEN  scene credential token (sep_...)
  AI_EVAL_CONFIG        optional path to a JSON file {"base_url", "access_token"}
                        kept OUTSIDE the repository.

Exit codes: 0 success, 1 validation/upload failure, 2 usage/config error.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

SCHEMA_VERSION = "1.0"
MAX_CASES = 50
MAX_MATERIAL_ITEMS = 50

# Field length limits mirror the backend contract (question_library/schemas.py).
LIMITS = {
    "client_case_id": (1, 128),
    "title": (1, 200),
    "task_prompt": (1, 100_000),
    "reference_answer": (1, 200_000),
    "content_text": (1, 200_000),
    "client_ref_id": (1, 128),
    "source_name": (0, 200),
    "source_label": (0, 200),
    "reason_summary": (0, 5_000),
    "feedback_text": (1, 5_000),
}


# ---------------------------------------------------------------------------
# Privacy backstop (mirrors backend rubric_rules; deterministic scan only).
# ---------------------------------------------------------------------------

_PRIVATE_TERMS: tuple[tuple[str, str], ...] = (
    ("api_key", "credential"),
    ("apikey", "credential"),
    ("api key", "credential"),
    ("access_token", "credential"),
    ("access token", "credential"),
    ("access key", "credential"),
    ("secret_key", "credential"),
    ("secret key", "credential"),
    ("private_key", "credential"),
    ("private key", "credential"),
    ("-----begin", "credential"),
    ("bearer ", "credential"),
    ("password", "credential"),
    ("passwd", "credential"),
    ("密码", "credential"),
    ("file://", "host path"),
    ("/users/", "host path"),
    ("/home/", "host path"),
    ("~/", "host path"),
    ("系统提示词", "system content"),
    ("系统指令", "system content"),
    ("system prompt", "system content"),
    ("<|im_start|>", "system content"),
    ("私有推理", "internal runtime info"),
)

_INVISIBLE = re.compile(
    "[\u200b\u200c\u200d\u2060\u2061\u2062\u2063\u2064\ufeff"
    "\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069\u00ad]"
)
_DRIVE_OR_UNC = re.compile(r"(?:[A-Za-z]:[\\/]|\\\\\S)", re.ASCII)
_HOME_PATH = re.compile(r"(?:^|[\s\"'`])(/Users/|/home/|~/|C:\\)", re.IGNORECASE)
_SECRET_VALUES = (
    re.compile(r"sk-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"sep_[A-Za-z0-9_\-]{16,}"),
    re.compile(r"AKIA[0-9A-Z]{12,}"),
    re.compile(r"LTAI[0-9A-Za-z]{12,}"),
    re.compile(r"ssh-(?:rsa|ed25519|dss)\s+[A-Za-z0-9+/=]{32,}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9\-]{10,}"),
)


def _canonical_for_scan(text: str) -> str:
    folded = unicodedata.normalize("NFKC", text)
    folded = _INVISIBLE.sub("", folded)
    return folded.casefold()


def scan_private(text: str, field_label: str) -> str | None:
    """Return an error message if the text leaks secrets/paths/system content."""

    if not isinstance(text, str):
        return f"{field_label}: must be a string"
    canonical = _canonical_for_scan(text)
    for term, category in _PRIVATE_TERMS:
        if term in canonical:
            return f"{field_label}: rejected ({category} detected)"
    if _DRIVE_OR_UNC.search(text) or _HOME_PATH.search(text):
        return f"{field_label}: rejected (host path detected)"
    for pattern in _SECRET_VALUES:
        if pattern.search(text):
            return f"{field_label}: rejected (credential value detected)"
    return None


# ---------------------------------------------------------------------------
# Payload validation (mirrors the backend six-material contract).
# ---------------------------------------------------------------------------


def _check_len(value: Any, key: str, label: str, errors: list[str], *, required: bool) -> str | None:
    lo, hi = LIMITS[key]
    if value is None:
        if required:
            errors.append(f"{label}: required")
        return None
    if not isinstance(value, str):
        errors.append(f"{label}: must be a string")
        return None
    if len(value) > hi:
        errors.append(f"{label}: longer than {hi} characters")
        return None
    stripped = value.strip()
    if lo > 0 and len(stripped) < lo:
        errors.append(f"{label}: must not be blank")
        return None
    return stripped


def _scan_field(value: Any, label: str, errors: list[str]) -> None:
    if isinstance(value, str):
        message = scan_private(value, label)
        if message:
            errors.append(message)


def _reject_unknown(item: dict, allowed: set[str], where: str, errors: list[str]) -> None:
    extra = sorted(set(item.keys()) - allowed)
    if extra:
        errors.append(f"{where}: unexpected field(s) {', '.join(extra)}")


_ALLOWED_BATCH = {"schema_version", "command_id", "cases"}
_ALLOWED_CASE = {
    "client_case_id",
    "title",
    "task_prompt",
    "reference_examples",
    "bad_cases",
    "reference_answer",
    "memory_materials",
}
_ALLOWED_EXAMPLE = {"client_ref_id", "source_name", "content_text"}
_ALLOWED_BAD_CASE = {"content_text", "teacher_feedback_texts", "reason_summary"}
_ALLOWED_MEMORY = {"client_ref_id", "source_label", "content_text"}


def _validate_ref_example(item: Any, where: str, errors: list[str]) -> None:
    if not isinstance(item, dict):
        errors.append(f"{where}: must be an object")
        return
    _reject_unknown(item, _ALLOWED_EXAMPLE, where, errors)
    cid = _check_len(item.get("client_ref_id"), "client_ref_id", f"{where}.client_ref_id", errors, required=True)
    if cid is not None:
        _scan_field(cid, f"{where}.client_ref_id", errors)
    source_name = item.get("source_name")
    if source_name is not None:
        _check_len(source_name, "source_name", f"{where}.source_name", errors, required=False)
        _scan_field(source_name, f"{where}.source_name", errors)
    content = _check_len(item.get("content_text"), "content_text", f"{where}.content_text", errors, required=True)
    if content is not None:
        _scan_field(content, f"{where}.content_text", errors)


def _validate_memory(item: Any, where: str, errors: list[str]) -> None:
    if not isinstance(item, dict):
        errors.append(f"{where}: must be an object")
        return
    _reject_unknown(item, _ALLOWED_MEMORY, where, errors)
    cid = _check_len(item.get("client_ref_id"), "client_ref_id", f"{where}.client_ref_id", errors, required=True)
    if cid is not None:
        _scan_field(cid, f"{where}.client_ref_id", errors)
    label = item.get("source_label")
    if label is not None:
        _check_len(label, "source_label", f"{where}.source_label", errors, required=False)
        _scan_field(label, f"{where}.source_label", errors)
    content = _check_len(item.get("content_text"), "content_text", f"{where}.content_text", errors, required=True)
    if content is not None:
        _scan_field(content, f"{where}.content_text", errors)


def _validate_bad_case(item: Any, where: str, errors: list[str]) -> None:
    if not isinstance(item, dict):
        errors.append(f"{where}: must be an object")
        return
    _reject_unknown(item, _ALLOWED_BAD_CASE, where, errors)
    content = _check_len(item.get("content_text"), "content_text", f"{where}.content_text", errors, required=True)
    if content is not None:
        _scan_field(content, f"{where}.content_text", errors)
    feedbacks = item.get("teacher_feedback_texts")
    if not isinstance(feedbacks, list) or not (1 <= len(feedbacks) <= 20):
        errors.append(f"{where}.teacher_feedback_texts: must contain 1..20 items")
    else:
        for i, fb in enumerate(feedbacks):
            text = _check_len(fb, "feedback_text", f"{where}.teacher_feedback_texts[{i}]", errors, required=True)
            if text is not None:
                _scan_field(text, f"{where}.teacher_feedback_texts[{i}]", errors)
    reason = item.get("reason_summary")
    if reason is not None:
        _check_len(reason, "reason_summary", f"{where}.reason_summary", errors, required=False)
        if isinstance(reason, str) and not reason.strip():
            errors.append(f"{where}.reason_summary: must not be blank")
        _scan_field(reason, f"{where}.reason_summary", errors)


def _check_id_unique(items: list[Any], id_field: str, where: str, errors: list[str]) -> None:
    seen: set[str] = set()
    for item in items:
        if isinstance(item, dict):
            value = item.get(id_field)
            if isinstance(value, str):
                if value in seen:
                    errors.append(f"{where}: duplicate {id_field}")
                seen.add(value)


def validate_case(case: Any, index: int) -> list[str]:
    errors: list[str] = []
    where = f"cases[{index}]"
    if not isinstance(case, dict):
        return [f"{where}: must be an object"]
    _reject_unknown(case, _ALLOWED_CASE, where, errors)

    for field, key, required in (
        ("client_case_id", "client_case_id", True),
        ("title", "title", True),
        ("task_prompt", "task_prompt", True),
        ("reference_answer", "reference_answer", True),
    ):
        value = _check_len(case.get(field), key, f"{where}.{field}", errors, required=required)
        if value is not None:
            _scan_field(value, f"{where}.{field}", errors)

    examples = case.get("reference_examples", [])
    bad_cases = case.get("bad_cases", [])
    memories = case.get("memory_materials", [])

    if not isinstance(examples, list) or len(examples) > MAX_MATERIAL_ITEMS:
        errors.append(f"{where}.reference_examples: must be a list of at most {MAX_MATERIAL_ITEMS}")
        examples = []
    if not isinstance(bad_cases, list) or len(bad_cases) > MAX_MATERIAL_ITEMS:
        errors.append(f"{where}.bad_cases: must be a list of at most {MAX_MATERIAL_ITEMS}")
        bad_cases = []
    if not isinstance(memories, list) or len(memories) > MAX_MATERIAL_ITEMS:
        errors.append(f"{where}.memory_materials: must be a list of at most {MAX_MATERIAL_ITEMS}")
        memories = []

    for i, item in enumerate(examples):
        _validate_ref_example(item, f"{where}.reference_examples[{i}]", errors)
    for i, item in enumerate(bad_cases):
        _validate_bad_case(item, f"{where}.bad_cases[{i}]", errors)
    for i, item in enumerate(memories):
        _validate_memory(item, f"{where}.memory_materials[{i}]", errors)

    _check_id_unique(examples, "client_ref_id", f"{where}.reference_examples", errors)
    _check_id_unique(memories, "client_ref_id", f"{where}.memory_materials", errors)
    return errors


def validate_batch(batch: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(batch, dict):
        return ["batch: must be a JSON object"]
    _reject_unknown(batch, _ALLOWED_BATCH, "batch", errors)
    if batch.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version: must be '{SCHEMA_VERSION}'")
    command_id = batch.get("command_id")
    if command_id is not None:
        if not isinstance(command_id, str) or not (1 <= len(command_id) <= 255):
            errors.append("command_id: must be a string of 1..255 characters")
    cases = batch.get("cases")
    if not isinstance(cases, list):
        errors.append("cases: must be a list")
        return errors
    if len(cases) > MAX_CASES:
        errors.append(f"cases: at most {MAX_CASES} per batch")
    seen: set[str] = set()
    for index, case in enumerate(cases):
        case_errors = validate_case(case, index)
        errors.extend(case_errors)
        if isinstance(case, dict):
            cid = case.get("client_case_id")
            if isinstance(cid, str):
                if cid in seen:
                    errors.append(f"cases: duplicate client_case_id '{cid[:32]}...'")
                seen.add(cid)
    return errors


def derive_command_id(batch: dict) -> str:
    """Stable per-payload command id; a changed payload yields a new command."""

    canonical = json.dumps(batch, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    normalized = unicodedata.normalize("NFC", canonical)
    return "skill-" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:32]


# ---------------------------------------------------------------------------
# Configuration and HTTP.
# ---------------------------------------------------------------------------


def load_config() -> tuple[str, str]:
    base_url = os.environ.get("AI_EVAL_BASE_URL", "").strip()
    token = os.environ.get("AI_EVAL_ACCESS_TOKEN", "").strip()
    config_path = os.environ.get("AI_EVAL_CONFIG", "").strip()
    if config_path and (not base_url or not token):
        path = os.path.expanduser(config_path)
        if not os.path.isabs(path):
            _usage_error("AI_EVAL_CONFIG must be an absolute path outside the repository")
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            _usage_error(f"cannot read AI_EVAL_CONFIG: {type(exc).__name__}")
        if not isinstance(data, dict):
            _usage_error("AI_EVAL_CONFIG must be a JSON object with base_url and access_token")
        file_url = data.get("base_url")
        file_token = data.get("access_token")
        base_url = base_url or (str(file_url).strip() if isinstance(file_url, str) else "")
        token = token or (str(file_token).strip() if isinstance(file_token, str) else "")
    if not base_url:
        _usage_error("AI_EVAL_BASE_URL is not set (e.g. http://127.0.0.1:8000)")
    if not token:
        _usage_error("AI_EVAL_ACCESS_TOKEN is not set (scene credential token)")
    scheme = urllib.parse.urlsplit(base_url).scheme
    if scheme not in ("http", "https"):
        _usage_error(f"AI_EVAL_BASE_URL must use http or https (got '{scheme or 'no scheme'}')")
    return base_url.rstrip("/"), token


def _usage_error(message: str) -> None:
    print(f"config-error: {message}", file=sys.stderr)
    sys.exit(2)


def http_request(method: str, url: str, token: str, body: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Authorization", f"Bearer {token}")
    request.add_header("Content-Type", "application/json")
    request.add_header("Accept", "application/json")
    opener = urllib.request.build_opener(_NoLeakRedirectHandler())
    try:
        with opener.open(request, timeout=60) as response:
            raw = response.read().decode("utf-8", errors="replace")
            return response.status, _safe_json_object(raw)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        return exc.code, _safe_json_object(raw) or {
            "error": {"code": "HTTP_ERROR", "message": f"HTTP {exc.code}"}
        }
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        reason = getattr(exc, "reason", None) or type(exc).__name__
        print(f"network-error: {reason}", file=sys.stderr)
        sys.exit(1)


class _NoLeakRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Never carry the Authorization header across hosts on a redirect."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        new_request = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new_request is not None:
            origin_host = urllib.parse.urlsplit(req.full_url).netloc
            target_host = urllib.parse.urlsplit(newurl).netloc
            if target_host != origin_host:
                new_request.remove_header("Authorization")
        return new_request


def _safe_json_object(raw: str) -> dict:
    """Parse a JSON object defensively; anything else becomes an empty mapping."""

    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _error_summary(payload: dict) -> str:
    error = payload.get("error") if isinstance(payload, dict) else None
    if not isinstance(error, dict):
        return "[UNKNOWN] request failed"
    code = str(error.get("code", "UNKNOWN"))
    message = str(error.get("message", ""))
    summary = f"[{code}] {message}"
    details = error.get("details")
    case_problems = details.get("cases") if isinstance(details, dict) else None
    if isinstance(case_problems, list):
        for item in case_problems:
            if not isinstance(item, dict):
                continue
            cid = str(item.get("client_case_id", "?"))
            problems = item.get("problems", [])
            if not isinstance(problems, list):
                continue
            for problem in problems:
                if isinstance(problem, dict):
                    summary += f"\n  - {cid}: [{problem.get('code')}] {problem.get('message')}"
    return summary


# Only these fields from the connection endpoint are safe to display.
_CONNECTION_FIELDS = ("status", "scene_id", "scene_name", "credential_id", "label", "last_used_at")


# ---------------------------------------------------------------------------
# Commands.
# ---------------------------------------------------------------------------


def _load_batch_file(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        _usage_error(f"cannot read batch file: {type(exc).__name__}")


def cmd_connection(_args: argparse.Namespace) -> int:
    base_url, token = load_config()
    status, payload = http_request("GET", f"{base_url}/api/external/connection", token)
    if status != 200:
        print(f"connection-failed: {_error_summary(payload)}", file=sys.stderr)
        return 1
    # Echo only the known-safe fields; never reflect an untrusted body verbatim.
    safe = {key: payload.get(key) for key in _CONNECTION_FIELDS if key in payload}
    print(json.dumps(safe, ensure_ascii=False, indent=2))
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    batch = _load_batch_file(args.batch_file)
    errors = validate_batch(batch)
    if errors:
        print(f"invalid: {len(errors)} problem(s)", file=sys.stderr)
        for message in errors:
            print(f"  - {message}", file=sys.stderr)
        return 1
    print(f"valid: {len(batch.get('cases', []))} case(s)")
    return 0


def cmd_push(args: argparse.Namespace) -> int:
    base_url, token = load_config()
    batch = _load_batch_file(args.batch_file)

    errors = validate_batch(batch)
    if errors:
        print(f"invalid: {len(errors)} problem(s); nothing was uploaded", file=sys.stderr)
        for message in errors:
            print(f"  - {message}", file=sys.stderr)
        return 1

    command_id = args.command_id or batch.get("command_id") or derive_command_id(batch)
    if not isinstance(command_id, str) or not (1 <= len(command_id) <= 255):
        print("invalid: command_id must be a string of 1..255 characters", file=sys.stderr)
        return 1
    payload = {
        "schema_version": SCHEMA_VERSION,
        "command_id": command_id,
        "cases": batch.get("cases", []),
    }

    if args.dry_run:
        print(f"dry-run: would upload {len(payload['cases'])} case(s)")
        print(f"dry-run: command_id={command_id}")
        return 0

    status, response = http_request(
        "POST", f"{base_url}/api/external/question-batches", token, payload
    )
    if status != 201:
        print(f"upload-failed: {_error_summary(response)}", file=sys.stderr)
        print("hint: no question was created; fix the batch and rerun.", file=sys.stderr)
        return 1

    cases = response.get("cases", [])
    print(f"uploaded: {len(cases)} case(s) into scene {response.get('scene_id')}")
    for item in cases:
        print(
            f"  - {item.get('client_case_id')}: question_id={item.get('question_id')} "
            f"status={item.get('status')}"
        )
    print("note: rubric generation is queued server-side; this skill does not poll it.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="push_eval_cases",
        description="Validate and push evaluation cases to the platform (no secrets printed).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_connection = sub.add_parser("connection", help="Verify the credential and bound scene.")
    p_connection.set_defaults(func=cmd_connection)

    p_validate = sub.add_parser("validate", help="Validate a local batch draft; no upload.")
    p_validate.add_argument("--batch-file", required=True)
    p_validate.set_defaults(func=cmd_validate)

    p_push = sub.add_parser("push", help="Validate then upload a batch.")
    p_push.add_argument("--batch-file", required=True)
    p_push.add_argument("--command-id", default=None)
    p_push.add_argument("--dry-run", action="store_true")
    p_push.set_defaults(func=cmd_push)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
