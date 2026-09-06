"""Targeted tests for the one-shot safe reset tool (C5).

The CLI target whitelist is deliberately NOT overridable, so these tests
exercise the internal functions with an explicit isolated allow-set against
the task-exclusive ``skill_eval_c5_reset_test`` database, plus the CLI's
refusal paths. Preparation (once per machine)::

    docker exec skill-eval-platform-postgres psql -U skill_eval -d postgres \
      -c 'CREATE DATABASE skill_eval_c5_reset_test OWNER skill_eval'
"""

from __future__ import annotations

import os
from urllib.parse import urlsplit, urlunsplit

import pytest

from scripts import reset_local_data as rst

TEST_DB = "skill_eval_c5_reset_test"
ALLOWED = frozenset({TEST_DB})


def _test_dsn() -> str:
    # conftest forces a SQLite DATABASE_URL for the app; the reset-tool tests
    # derive their isolated PG target from the private .env instead.
    base = os.environ.get("RESET_TEST_DSN", "")
    if not base:
        env_file = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
        try:
            for line in open(env_file, encoding="utf-8"):
                if line.startswith("DATABASE_URL="):
                    base = line.split("=", 1)[1].strip()
                    break
        except OSError:
            base = ""
    if not base or base.startswith("sqlite"):
        message = "无 PostgreSQL 业务 DSN 可派生重置工具测试目标（非验收证据）"
        if os.environ.get("RUNTIME_PG_REQUIRED") == "1":
            pytest.fail(message)
        pytest.skip(message)
    parts = urlsplit(base.replace("postgresql+psycopg://", "postgresql://"))
    return urlunsplit(("postgresql", parts.netloc, f"/{TEST_DB}", "", ""))


@pytest.fixture()
def dsn() -> str:
    import psycopg

    candidate = _test_dsn()
    try:
        with psycopg.connect(candidate, autocommit=True, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT current_database()")
                assert cur.fetchone()[0] == TEST_DB
    except Exception as exc:  # noqa: BLE001
        message = f"重置工具测试库 {TEST_DB} 不可达：{type(exc).__name__}"
        if os.environ.get("RUNTIME_PG_REQUIRED") == "1":
            pytest.fail(message)
        pytest.skip(message)
    return candidate


# ---------------------------------------------------------------------------
# Target whitelist / refusal paths
# ---------------------------------------------------------------------------

def test_verify_target_whitelist():
    ok = f"postgresql://u:p@{rst.EXPECTED_HOST}:{rst.EXPECTED_PORT}/skill_eval"
    assert rst.verify_target(ok) == "skill_eval"
    ckpt = f"postgresql://u:p@{rst.EXPECTED_HOST}:{rst.EXPECTED_PORT}/skill_eval_checkpoint"
    assert rst.verify_target(ckpt) == "skill_eval_checkpoint"


@pytest.mark.parametrize("bad", [
    "postgresql://u:p@127.0.0.1:5432/postgres",
    "postgresql://u:p@127.0.0.1:5432/template1",
    "postgresql://u:p@127.0.0.1:5432/some_other_project",
    "postgresql://u:p@db.example.com:5432/skill_eval",       # remote host
    "postgresql://u:p@127.0.0.1:6543/skill_eval",            # wrong port
    "postgresql://u@127.0.0.1:5432/skill_eval",              # no password to verify
    "sqlite:///business.db",                                  # wrong engine
    "postgresql://u:p@127.0.0.1:5432/",                       # no dbname
    # C-1 regressions: libpq query/fragment overrides must never pass.
    "postgresql://u:p@127.0.0.1:5432/skill_eval?host=evil.example.com",
    "postgresql://u:p@127.0.0.1:5432/skill_eval?hostaddr=93.184.216.34",
    "postgresql://u:p@127.0.0.1:5432/skill_eval?dbname=postgres",
    "postgresql://u:p@127.0.0.1:5432/skill_eval?port=6543",
    "postgresql://u:p@127.0.0.1:5432/skill_eval#frag",
    # Additional shape attacks verified refused.
    "postgresql://u:p@127.0.0.1:5432/SkillEval",              # case mismatch
    "postgresql://u:p@127.0.0.1:5432/skill%5Feval",           # percent-encoding
    "postgresql://u:p@127.0.0.1:5432/skill_eval/extra",       # multi-segment path
    "postgresql://u:p@[::1]:5432/skill_eval",                 # IPv6 literal
    "postgresql+asyncpg://u:p@127.0.0.1:5432/skill_eval",     # other driver prefix
    "postgresql://u:p@localhost:5432/skill_eval",             # non-IP hostname
])
def test_verify_target_refuses(bad):
    with pytest.raises(rst.ResetRefused):
        rst.verify_target(bad)


def test_connect_params_never_reparses_raw_dsn():
    params = rst.connect_params("postgresql+psycopg://u:p@127.0.0.1:5432/skill_eval")
    assert params == {"host": "127.0.0.1", "port": 5432, "dbname": "skill_eval",
                      "user": "u", "password": "p"}


def test_cli_execute_requires_exact_confirmation(dsn):
    rc = rst.main([
        "--execute", "--confirm-targets", "skill_eval",
        "--business-dsn", dsn, "--checkpoint-dsn", dsn,
    ])
    # Wrong confirm string: refused before any DSN is even parsed.
    assert rc == 2


def test_cli_refuses_non_whitelisted_dsn(dsn):
    rc = rst.main(["--dry-run", "--business-dsn", dsn, "--checkpoint-dsn", dsn])
    assert rc == 2  # test db name is not in the production whitelist


# ---------------------------------------------------------------------------
# Plan / reset / backup against the isolated database
# ---------------------------------------------------------------------------

def test_build_plan_counts_and_is_read_only(dsn):
    import psycopg

    with psycopg.connect(dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("CREATE TABLE IF NOT EXISTS marker_rows (id serial primary key, note text)")
            cur.execute("INSERT INTO marker_rows (note) VALUES ('reset-target-marker')")
    plan = rst.build_plan(dsn, allowed=ALLOWED)
    assert plan.db_name == TEST_DB
    assert plan.table_counts.get("marker_rows", 0) >= 1
    assert "***" in plan.masked_dsn
    with psycopg.connect(dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM marker_rows")
            assert cur.fetchone()[0] >= 1, "dry-run 计划不得修改数据"


def test_reset_database_rebuilds_schema_only(dsn):
    import psycopg

    with psycopg.connect(dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("CREATE TABLE IF NOT EXISTS doomed (id int)")
            cur.execute("INSERT INTO doomed VALUES (1)")
    rst.reset_database(dsn, allowed=ALLOWED)
    with psycopg.connect(dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM pg_tables WHERE schemaname='public'"
            )
            assert cur.fetchone()[0] == 0
            cur.execute("SELECT has_schema_privilege(current_user, 'public', 'CREATE')")
            assert cur.fetchone()[0]


def test_reset_refuses_when_other_sessions_active(dsn):
    import psycopg

    blocker = psycopg.connect(dsn, autocommit=True)
    try:
        with pytest.raises(rst.ResetRefused, match="活动连接"):
            rst.reset_database(dsn, allowed=ALLOWED)
    finally:
        blocker.close()


def test_container_identity_and_backup_roundtrip(dsn, tmp_path):
    container = rst.DEFAULT_CONTAINER
    server_id = rst.verify_container_matches_endpoint(container, dsn, allowed=ALLOWED)
    assert server_id
    import psycopg

    with psycopg.connect(dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("CREATE TABLE IF NOT EXISTS backup_marker (id int)")
            cur.execute("INSERT INTO backup_marker VALUES (7)")
    record = rst.backup_database(container, TEST_DB, tmp_path)
    assert record["bytes"] > 0 and len(record["sha256"]) == 64
    assert os.path.isfile(record["path"])
