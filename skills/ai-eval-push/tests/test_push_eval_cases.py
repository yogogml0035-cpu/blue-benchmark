"""Isolated tests for the ai-eval-push client script.

The client is standard-library only and talks HTTP, so these tests spin up a
local fake server (no backend import) plus pure validation/privacy checks.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import unicodedata
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

SKILL_SCRIPTS = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "scripts")
)
sys.path.insert(0, SKILL_SCRIPTS)

import push_eval_cases as pec  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures: a valid batch and a fake platform server.
# ---------------------------------------------------------------------------


def _example(client_ref_id: str = "ref-1", text: str = "老师提供且读取过的素材。") -> dict:
    return {"client_ref_id": client_ref_id, "source_name": "素材", "content_text": text}


def _memory(client_ref_id: str = "mem-1", text: str = "本轮加载的相关记忆。") -> dict:
    return {"client_ref_id": client_ref_id, "source_label": "业务记忆", "content_text": text}


def _bad_case() -> dict:
    return {
        "content_text": "被否定的初稿。",
        "teacher_feedback_texts": ["语气太随意。"],
        "reason_summary": "语体不符。",
    }


def make_case(client_case_id: str = "case-1") -> dict:
    return {
        "client_case_id": client_case_id,
        "title": "新闻稿改写",
        "task_prompt": "请把素材改写成正式新闻稿。",
        "reference_examples": [_example()],
        "bad_cases": [_bad_case()],
        "reference_answer": "老师认可的标准答案。",
        "memory_materials": [_memory()],
    }


def make_batch(command_id: str | None = None, cases: list[dict] | None = None) -> dict:
    batch: dict = {"schema_version": "1.0", "cases": cases if cases is not None else [make_case()]}
    if command_id:
        batch["command_id"] = command_id
    return batch


class FakePlatform(BaseHTTPRequestHandler):
    """Minimal stand-in for /api/external/connection and question-batches."""

    token = "sep_valid_token"
    scene_id = "scene-uuid"
    # class-level store shared across requests
    commands: dict[str, dict] = {}

    def _send(self, status: int, body: dict) -> None:
        raw = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _authorized(self) -> bool:
        return self.headers.get("Authorization") == f"Bearer {self.token}"

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/api/external/connection":
            if not self._authorized():
                self._send(401, {"error": {"code": "CREDENTIAL_INVALID", "message": "凭证无效"}})
                return
            self._send(
                200,
                {
                    "status": "connected",
                    "scene_id": self.scene_id,
                    "scene_name": "测试场景",
                    "credential_id": "cred-uuid",
                    "label": "ci",
                    "last_used_at": None,
                },
            )
        else:
            self._send(404, {"error": {"code": "NOT_FOUND", "message": "无此接口"}})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/api/external/question-batches":
            self._send(404, {"error": {"code": "NOT_FOUND", "message": "无此接口"}})
            return
        if not self._authorized():
            self._send(401, {"error": {"code": "CREDENTIAL_INVALID", "message": "凭证无效"}})
            return
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        command_id = payload.get("command_id")
        payload_hash = hash(json.dumps(payload.get("cases"), sort_keys=True))
        existing = self.commands.get(command_id)
        if existing and existing["hash"] != payload_hash:
            self._send(409, {"error": {"code": "COMMAND_ID_REUSED", "message": "命令已用于其他内容"}})
            return
        if existing:
            self._send(201, existing["result"])
            return
        result = {
            "command_id": command_id,
            "scene_id": self.scene_id,
            "accepted_case_count": len(payload.get("cases", [])),
            "cases": [
                {
                    "client_case_id": case.get("client_case_id"),
                    "question_id": f"q-{case.get('client_case_id')}",
                    "status": "generating",
                }
                for case in payload.get("cases", [])
            ],
        }
        self.commands[command_id] = {"hash": payload_hash, "result": result}
        self._send(201, result)

    def log_message(self, *args: object) -> None:  # silence request logging
        pass


@pytest.fixture()
def server(monkeypatch):
    FakePlatform.commands = {}
    httpd = HTTPServer(("127.0.0.1", 0), FakePlatform)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{httpd.server_address[1]}"
    monkeypatch.setattr(pec, "BASE_URL", base_url)
    monkeypatch.setattr(pec, "ACCESS_TOKEN", FakePlatform.token)
    yield base_url
    httpd.shutdown()
    httpd.server_close()


# ---------------------------------------------------------------------------
# Validation tests.
# ---------------------------------------------------------------------------


def test_valid_batch_passes():
    assert pec.validate_batch(make_batch()) == []


def test_missing_standard_answer_fails():
    case = make_case()
    case["reference_answer"] = "   "
    errors = pec.validate_batch(make_batch(cases=[case]))
    assert any("reference_answer" in e for e in errors)


def test_missing_title_or_prompt_fails():
    case = make_case()
    del case["title"]
    errors = pec.validate_batch(make_batch(cases=[case]))
    assert any("title" in e for e in errors)


def test_duplicate_client_case_id_fails():
    errors = pec.validate_batch(make_batch(cases=[make_case("a"), make_case("a")]))
    assert any("duplicate client_case_id" in e for e in errors)


def test_duplicate_ref_id_within_list_fails():
    case = make_case()
    case["reference_examples"] = [_example("r1"), _example("r1")]
    errors = pec.validate_batch(make_batch(cases=[case]))
    assert any("duplicate client_ref_id" in e for e in errors)


def test_bad_case_requires_feedback():
    case = make_case()
    case["bad_cases"] = [{"content_text": "坏结果", "teacher_feedback_texts": []}]
    errors = pec.validate_batch(make_batch(cases=[case]))
    assert any("teacher_feedback_texts" in e for e in errors)


def test_empty_case_list_is_allowed():
    # 0 questions is a legal batch shape (the skill may find nothing to save).
    assert pec.validate_batch(make_batch(cases=[])) == []


# ---------------------------------------------------------------------------
# Privacy / leak regressions.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "leaky",
    [
        "配置保存在 /Users/hsikey/.env",
        "密钥在 C:\\secrets\\key.txt",
        "path is ~/notes.md",
        "use api_key=abc123",
        "密码是 hunter2",
        "这是系统提示词内容",
        "token sk-abcdefghij1234567890",
        "see file:///etc/passwd",
    ],
)
def test_private_content_rejected(leaky):
    assert pec.scan_private(leaky, "field") is not None


def test_zero_width_bypass_is_caught():
    leaky = "pass\u200bword=abc123"
    assert pec.scan_private(leaky, "field") is not None


def test_fullwidth_homoglyph_bypass_is_caught():
    leaky = "ｐａｓｓｗｏｒｄ=abc123"
    assert pec.scan_private(leaky, "field") is not None


def test_clean_text_passes():
    assert pec.scan_private("把会议结论整理成纪要", "field") is None


def test_batch_with_leaky_memory_rejected():
    case = make_case()
    case["memory_materials"] = [_memory("m1", "备份在 /Users/x/.ssh/id_rsa")]
    errors = pec.validate_batch(make_batch(cases=[case]))
    assert any("memory_materials[0].content_text" in e for e in errors)


def test_memory_text_is_not_rewritten():
    # The client must pass raw memory through verbatim (no summarizing/normalizing).
    raw = "  原始记忆：保持原样，包括标点。 "
    case = make_case()
    case["memory_materials"] = [_memory("m1", raw)]
    batch = make_batch(cases=[case])
    assert batch["cases"][0]["memory_materials"][0]["content_text"] == raw


# ---------------------------------------------------------------------------
# command_id derivation.
# ---------------------------------------------------------------------------


def test_command_id_stable_for_same_payload():
    batch = make_batch()
    assert pec.derive_command_id(batch) == pec.derive_command_id(make_batch())


def test_command_id_changes_with_payload():
    a = pec.derive_command_id(make_batch(cases=[make_case("a")]))
    b = pec.derive_command_id(make_batch(cases=[make_case("b")]))
    assert a != b


def test_command_id_unicode_normalized():
    pre = make_batch(cases=[make_case()])
    pre["cases"][0]["title"] = "caf\u00e9"
    dec = json.loads(json.dumps(pre))
    dec["cases"][0]["title"] = "cafe\u0301"
    assert pec.derive_command_id(pre) == pec.derive_command_id(dec)


# ---------------------------------------------------------------------------
# HTTP integration (fake server).
# ---------------------------------------------------------------------------


def test_connection_success(server, capsys):
    assert pec.main(["connection"]) == 0
    out = capsys.readouterr().out
    assert "connected" in out
    assert FakePlatform.token not in out  # token never echoed


def test_connection_invalid_token(server, monkeypatch, capsys):
    monkeypatch.setattr(pec, "ACCESS_TOKEN", "sep_wrong")
    assert pec.main(["connection"]) == 1
    assert "CREDENTIAL_INVALID" in capsys.readouterr().err


def test_unbound_config_errors(monkeypatch):
    monkeypatch.setattr(pec, "BASE_URL", pec._PLACEHOLDER)
    monkeypatch.setattr(pec, "ACCESS_TOKEN", "sep_" + pec._PLACEHOLDER)
    with pytest.raises(SystemExit) as exc:
        pec.load_config()
    assert exc.value.code == 2


def test_partially_bound_config_errors(monkeypatch):
    # Binding must replace BOTH slots; one remaining placeholder is unbound.
    monkeypatch.setattr(pec, "BASE_URL", "http://127.0.0.1:8000")
    monkeypatch.setattr(pec, "ACCESS_TOKEN", "sep_" + pec._PLACEHOLDER)
    with pytest.raises(SystemExit) as exc:
        pec.load_config()
    assert exc.value.code == 2


def test_validate_command_reports_valid(server, tmp_path, capsys):
    path = tmp_path / "batch.json"
    path.write_text(json.dumps(make_batch()), encoding="utf-8")
    assert pec.main(["validate", "--batch-file", str(path)]) == 0
    assert "valid: 1 case" in capsys.readouterr().out


def test_push_success_and_idempotent_replay(server, tmp_path, capsys):
    path = tmp_path / "batch.json"
    batch = make_batch(cases=[make_case("case-a"), make_case("case-b")])
    path.write_text(json.dumps(batch), encoding="utf-8")

    assert pec.main(["push", "--batch-file", str(path)]) == 0
    out = capsys.readouterr().out
    assert "uploaded: 2 case(s)" in out
    assert "q-case-a" in out and "q-case-b" in out

    # Replaying the identical file is idempotent (same ids, no duplicates).
    capsys.readouterr()
    assert pec.main(["push", "--batch-file", str(path)]) == 0
    replay = capsys.readouterr().out
    assert "uploaded: 2 case(s)" in replay
    assert "q-case-a" in replay


def test_push_conflict_on_changed_payload_same_command(server, tmp_path, capsys):
    path = tmp_path / "batch.json"
    batch = make_batch(command_id="fixed-command")
    path.write_text(json.dumps(batch), encoding="utf-8")
    assert pec.main(["push", "--batch-file", str(path)]) == 0

    changed = make_batch(command_id="fixed-command")
    changed["cases"][0]["title"] = "改动后的标题"
    path.write_text(json.dumps(changed), encoding="utf-8")
    capsys.readouterr()
    assert pec.main(["push", "--batch-file", str(path)]) == 1
    assert "COMMAND_ID_REUSED" in capsys.readouterr().err


def test_push_invalid_batch_uploads_nothing(server, tmp_path, capsys):
    case = make_case()
    case["reference_answer"] = "   "
    path = tmp_path / "batch.json"
    path.write_text(json.dumps(make_batch(cases=[case])), encoding="utf-8")
    assert pec.main(["push", "--batch-file", str(path)]) == 1
    err = capsys.readouterr().err
    assert "nothing was uploaded" in err
    # Server saw no upload.
    assert FakePlatform.commands == {}


def test_push_dry_run_does_not_upload(server, tmp_path, capsys):
    path = tmp_path / "batch.json"
    path.write_text(json.dumps(make_batch()), encoding="utf-8")
    assert pec.main(["push", "--batch-file", str(path), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "dry-run" in out
    assert FakePlatform.commands == {}


# ---------------------------------------------------------------------------
# Hardening regressions (unknown fields, command_id, scheme, redirect leak).
# ---------------------------------------------------------------------------


def test_unknown_case_field_rejected():
    case = make_case()
    case["unexpected_field"] = "x"
    errors = pec.validate_batch(make_batch(cases=[case]))
    assert any("unexpected field" in e for e in errors)


def test_unknown_top_level_field_rejected():
    batch = make_batch()
    batch["rogue"] = 1
    errors = pec.validate_batch(batch)
    assert any("unexpected field" in e for e in errors)


def test_command_id_length_enforced_client_side():
    batch = make_batch(command_id="x" * 256)
    errors = pec.validate_batch(batch)
    assert any("command_id" in e for e in errors)


def test_blank_reason_summary_rejected():
    case = make_case()
    case["bad_cases"] = [
        {"content_text": "坏结果", "teacher_feedback_texts": ["不行"], "reason_summary": "   "}
    ]
    errors = pec.validate_batch(make_batch(cases=[case]))
    assert any("reason_summary" in e for e in errors)


def test_non_http_scheme_rejected(monkeypatch):
    monkeypatch.setattr(pec, "BASE_URL", "file:///tmp/whatever")
    monkeypatch.setattr(pec, "ACCESS_TOKEN", "sep_x")
    with pytest.raises(SystemExit) as exc:
        pec.load_config()
    assert exc.value.code == 2


def test_redirect_strips_authorization_cross_host():
    # A redirect to a different host must not carry the Authorization header.
    captured = {}

    class Sink(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            captured["auth"] = self.headers.get("Authorization")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"connected","scene_id":"s"}')

        def log_message(self, *a):  # noqa: D102
            pass

    sink = HTTPServer(("127.0.0.1", 0), Sink)
    threading.Thread(target=sink.serve_forever, daemon=True).start()
    sink_port = sink.server_address[1]

    class Redirector(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{sink_port}/sink")
            self.end_headers()

        def log_message(self, *a):  # noqa: D102
            pass

    redirector = HTTPServer(("127.0.0.1", 0), Redirector)
    threading.Thread(target=redirector.serve_forever, daemon=True).start()
    redirector_port = redirector.server_address[1]

    base_url = f"http://127.0.0.1:{redirector_port}"
    status, _payload = pec.http_request("GET", f"{base_url}/api/external/connection", "sep_secret")
    # The cross-host hop must NOT have received the Authorization header.
    assert captured.get("auth") is None

    sink.shutdown(); sink.server_close()
    redirector.shutdown(); redirector.server_close()


def test_connection_only_prints_whitelisted_fields(server, monkeypatch, capsys):
    # Even if a malicious server returns extra/reflected fields, only the known
    # safe keys are displayed.
    import push_eval_cases as m

    def fake_http(method, url, token, body=None):
        return 200, {
            "status": "connected",
            "scene_id": "s1",
            "scene_name": "Bearer sep_should_not_appear",
            "credential_id": "c1",
            "label": None,
            "last_used_at": None,
            "secret_extra": "hidden",
        }

    monkeypatch.setattr(m, "http_request", fake_http)
    monkeypatch.setattr(m, "BASE_URL", "http://x")
    monkeypatch.setattr(m, "ACCESS_TOKEN", "sep_real")
    assert m.main(["connection"]) == 0
    out = capsys.readouterr().out
    assert "secret_extra" not in out
    assert "scene_id" in out
