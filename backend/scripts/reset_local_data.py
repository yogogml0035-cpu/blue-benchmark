"""One-shot safe reset for the CURRENT LOCAL project databases (C5 owner).

Scope and authority: this tool exists solely to execute the user-authorized
ONE-TIME cleanup of the local Docker PostgreSQL project databases
(``skill_eval`` and ``skill_eval_checkpoint``) during the M0 rubric refactor
cutover. It is NOT a recurring maintenance job, must never be wired into
``make test``, application startup, or ordinary migrations, and its authority
does not extend to data uploaded after the cutover.

Safety contract:

* target whitelist by database NAME plus expected local host/port — anything
  else (including arbitrary DATABASE_URL values, remote hosts, ``postgres``,
  or template databases) is refused;
* dry-run by default: sanitized plan with per-table impact counts;
* ``--execute`` requires retyping the exact target list;
* active third-party connections on a target abort the run (stop the
  project's own API/Worker first; the tool never kills anything);
* controlled pg_dump backups (via the verified Docker container) must
  succeed and verify BEFORE any destructive statement;
* the container and the TCP endpoint are proven to be the same PostgreSQL
  instance (system identifier comparison) before dumping;
* only the project schemas inside the two target databases are rebuilt —
  never roles, other databases, the Docker volume, .env secrets, or
  ``.local-samples``;
* post-verification: business schema reaches the current Alembic head with
  an empty question library, and the checkpoint store is freshly set up.

Usage:
    cd backend && uv run python -m scripts.reset_local_data --dry-run
    cd backend && uv run python -m scripts.reset_local_data --execute \
        --confirm-targets skill_eval,skill_eval_checkpoint
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

ALLOWED_TARGETS: frozenset[str] = frozenset({"skill_eval", "skill_eval_checkpoint"})
EXPECTED_HOST = "127.0.0.1"
EXPECTED_PORT = 5432
DEFAULT_CONTAINER = "skill-eval-platform-postgres"
DEFAULT_BACKUP_ROOT = Path(
    "/Users/hsikey/Company/skill-eval-platform-wt/_artifacts/m0-rubric-anchors-evidence/c5"
)


class ResetRefused(RuntimeError):
    """Any refusal before destructive work begins."""


def _mask_dsn(dsn: str) -> str:
    raw = dsn.replace("postgresql+psycopg://", "postgresql://")
    parts = urlsplit(raw)
    user = parts.username or "?"
    return f"postgresql://{user}:***@{parts.hostname}:{parts.port or 5432}{parts.path}"


def verify_target(dsn: str, *, allowed: frozenset[str] = ALLOWED_TARGETS) -> str:
    """Validate one target DSN; return its database name or refuse."""
    raw = dsn.replace("postgresql+psycopg://", "postgresql://")
    if not raw.startswith("postgresql://"):
        raise ResetRefused(f"目标必须是 PostgreSQL DSN：{_mask_dsn(dsn)}")
    parts = urlsplit(raw)
    db_name = (parts.path or "/").lstrip("/").split("?")[0]
    if not db_name:
        raise ResetRefused("目标 DSN 缺少库名。")
    if db_name not in allowed:
        raise ResetRefused(f"目标库 {db_name} 不在一次性授权白名单 {sorted(allowed)} 内。")
    host = parts.hostname or ""
    port = parts.port or 5432
    if host != EXPECTED_HOST or port != EXPECTED_PORT:
        raise ResetRefused(f"目标实例 {host}:{port} 不是本地 Docker PostgreSQL（{EXPECTED_HOST}:{EXPECTED_PORT}）。")
    if parts.password is None:
        raise ResetRefused("目标 DSN 缺少凭证，无法核验身份（不会输出该凭证）。")
    return db_name


def _plain_dsn(dsn: str) -> str:
    return dsn.replace("postgresql+psycopg://", "postgresql://")


def server_identity(conn) -> tuple[str, str]:
    with conn.cursor() as cur:
        cur.execute("SELECT system_identifier, current_database() FROM pg_control_system(), (SELECT current_database() AS current_database) AS d")
        row = cur.fetchone()
    return str(row[0]), str(row[1])


def check_no_active_writers(conn, db_name: str) -> int:
    """Refuse when other sessions are attached to the target database.

    Returns the count of the tool's OWN backends (allowed). Anything else
    means a writer was not stopped.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT pg_backend_pid()")
        self_pid = cur.fetchone()[0]
        cur.execute(
            "SELECT count(*) FROM pg_stat_activity "
            "WHERE datname = %s AND pid <> %s AND backend_type = 'client backend'",
            (db_name, self_pid),
        )
        others = int(cur.fetchone()[0])
    if others > 0:
        raise ResetRefused(
            f"目标库 {db_name} 仍有 {others} 个活动连接；先停止本项目 API/Worker 再执行。"
        )
    return others


@dataclass(frozen=True)
class TargetPlan:
    db_name: str
    masked_dsn: str
    table_counts: dict[str, int]
    total_rows: int


def build_plan(dsn: str, *, allowed: frozenset[str] = ALLOWED_TARGETS) -> TargetPlan:
    """Read-only impact assessment for one target (sanitized output only)."""
    import psycopg

    db_name = verify_target(dsn, allowed=allowed)
    with psycopg.connect(_plain_dsn(dsn), autocommit=True, connect_timeout=10) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
            )
            tables = [row[0] for row in cur.fetchall()]
            counts: dict[str, int] = {}
            for table in tables:
                cur.execute(f'SELECT count(*) FROM public."{table}"')  # noqa: S608
                counts[table] = int(cur.fetchone()[0])
    return TargetPlan(db_name, _mask_dsn(dsn), counts, sum(counts.values()))


def verify_container_matches_endpoint(container: str, dsn: str) -> str:
    """Prove the Docker container hosts the SAME server as the TCP DSN."""
    import psycopg

    with psycopg.connect(_plain_dsn(dsn), autocommit=True, connect_timeout=10) as conn:
        tcp_id, _ = server_identity(conn)
    out = subprocess.run(
        ["docker", "exec", container, "psql", "-U", "skill_eval", "-d", "postgres",
         "-tAc", "SELECT system_identifier FROM pg_control_system()"],
        capture_output=True, text=True, timeout=30,
    )
    if out.returncode != 0:
        raise ResetRefused(f"无法通过容器 {container} 核验实例身份：{out.stderr.strip()[:160]}")
    container_id = out.stdout.strip()
    if container_id != tcp_id:
        raise ResetRefused(
            f"容器 {container} 与目标 DSN 不是同一 PostgreSQL 实例，拒绝备份/重置。"
        )
    return tcp_id


def backup_database(container: str, db_name: str, backup_dir: Path) -> dict[str, Any]:
    """pg_dump via the verified container, copied out to the artifacts dir."""
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    remote_path = f"/tmp/{db_name}-{stamp}.dump"
    local_path = backup_dir / f"{db_name}-{stamp}.dump"
    dump = subprocess.run(
        ["docker", "exec", container, "pg_dump", "-U", "skill_eval", "-d", db_name,
         "-Fc", "-f", remote_path],
        capture_output=True, text=True, timeout=600,
    )
    if dump.returncode != 0:
        raise ResetRefused(f"备份 {db_name} 失败：{dump.stderr.strip()[:200]}")
    copied = subprocess.run(
        ["docker", "cp", f"{container}:{remote_path}", str(local_path)],
        capture_output=True, text=True, timeout=300,
    )
    if copied.returncode != 0 or not local_path.is_file() or local_path.stat().st_size == 0:
        raise ResetRefused(f"备份文件取出失败：{db_name}")
    subprocess.run(
        ["docker", "exec", container, "rm", "-f", remote_path],
        capture_output=True, text=True, timeout=60,
    )
    digest = hashlib.sha256(local_path.read_bytes()).hexdigest()
    return {"db": db_name, "path": str(local_path), "bytes": local_path.stat().st_size,
            "sha256": digest}


def reset_database(dsn: str, *, allowed: frozenset[str] = ALLOWED_TARGETS) -> None:
    """Drop and recreate the public schema of ONE verified target."""
    import psycopg

    db_name = verify_target(dsn, allowed=allowed)
    with psycopg.connect(_plain_dsn(dsn), autocommit=True, connect_timeout=10) as conn:
        check_no_active_writers(conn, db_name)
        with conn.cursor() as cur:
            cur.execute("SELECT current_user")
            role = cur.fetchone()[0]
            cur.execute("DROP SCHEMA public CASCADE")
            cur.execute("CREATE SCHEMA public")
            cur.execute("GRANT ALL ON SCHEMA public TO %s" % f'"{role}"')  # noqa: S608
            cur.execute("GRANT ALL ON SCHEMA public TO PUBLIC")
            if db_name == "skill_eval_checkpoint":
                # The checkpoint role connects separately for saver traffic.
                cur.execute(
                    "SELECT 1 FROM pg_roles WHERE rolname = 'skill_eval_checkpoint'"
                )
                if cur.fetchone():
                    cur.execute("GRANT ALL ON SCHEMA public TO skill_eval_checkpoint")


def prepare_business_schema(business_dsn: str) -> None:
    """Run Alembic to the current head on the freshly reset business DB."""
    from alembic import command
    from alembic.config import Config

    os.environ["ALEMBIC_DATABASE_URL"] = business_dsn.replace(
        "postgresql://", "postgresql+psycopg://"
    ) if "+psycopg" not in business_dsn else business_dsn
    cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
    command.upgrade(cfg, "head")


def prepare_checkpoint_schema(checkpoint_dsn: str) -> None:
    """Create the checkpointer tables with the configured encrypted serde."""
    import psycopg
    from pydantic import SecretStr

    from app.lib.ai_runtime import deep_runtime
    from app.lib.settings import settings

    class _Cfg:
        checkpoint_database_url = SecretStr(_plain_dsn(checkpoint_dsn))
        langgraph_aes_key = settings.langgraph_aes_key

    if not settings.langgraph_aes_key.get_secret_value():
        raise ResetRefused("LANGGRAPH_AES_KEY 未配置，拒绝准备检查点库。")
    with psycopg.connect(_plain_dsn(checkpoint_dsn), autocommit=True) as conn:
        deep_runtime.build_saver(conn, _Cfg()).setup()


def verify_reset(business_dsn: str, checkpoint_dsn: str) -> dict[str, Any]:
    """Post-verification: schema head, empty library, checkpoint tables."""
    import psycopg
    from sqlalchemy import create_engine

    from app.lib.database.session import BUSINESS_SCHEMA_HEAD, check_schema_ready

    engine = create_engine(
        business_dsn if "+psycopg" in business_dsn
        else business_dsn.replace("postgresql://", "postgresql+psycopg://")
    )
    ready = check_schema_ready(engine)
    engine.dispose()
    if not ready:
        raise ResetRefused(f"业务库 schema 未达到当前 head（{BUSINESS_SCHEMA_HEAD}）。")
    with psycopg.connect(_plain_dsn(business_dsn), autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM eval_questions")
            questions = int(cur.fetchone()[0])
    if questions != 0:
        raise ResetRefused("重置后题库不为空。")
    with psycopg.connect(_plain_dsn(checkpoint_dsn), autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM checkpoint_migrations")
            migrations = int(cur.fetchone()[0])
            cur.execute("SELECT count(*) FROM checkpoints")
            checkpoints = int(cur.fetchone()[0])
    if migrations == 0 or checkpoints != 0:
        raise ResetRefused("检查点库准备不完整或仍有旧数据。")
    return {"schema_head": BUSINESS_SCHEMA_HEAD, "questions": questions,
            "checkpoint_migrations": migrations, "checkpoints": checkpoints}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", default=False,
                        help="只输出脱敏计划与影响范围（不加 --execute 时即默认行为）")
    parser.add_argument("--execute", action="store_true",
                        help="执行一次性重置（需要 --confirm-targets 精确匹配）")
    parser.add_argument("--confirm-targets", default="",
                        help="执行确认：必须精确为 skill_eval,skill_eval_checkpoint")
    parser.add_argument("--container", default=DEFAULT_CONTAINER)
    parser.add_argument("--backup-dir", default="",
                        help=f"备份目录（默认 {DEFAULT_BACKUP_ROOT}/<UTC时间戳>）")
    parser.add_argument("--business-dsn", default="")
    parser.add_argument("--checkpoint-dsn", default="")
    args = parser.parse_args(argv)

    if args.execute and args.confirm_targets.strip() != "skill_eval,skill_eval_checkpoint":
        print("RESET=REFUSED --confirm-targets 必须精确为 skill_eval,skill_eval_checkpoint",
              file=sys.stderr)
        return 2

    from app.lib.settings import settings

    business_dsn = args.business_dsn or settings.database_url
    checkpoint_dsn = args.checkpoint_dsn or settings.checkpoint_database_url.get_secret_value()
    if not checkpoint_dsn:
        print("RESET=FAIL CHECKPOINT_DATABASE_URL 未配置", file=sys.stderr)
        return 1

    try:
        plans = [build_plan(business_dsn), build_plan(checkpoint_dsn)]
    except ResetRefused as exc:
        print(f"RESET=REFUSED {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001
        print(f"RESET=FAIL 目标不可达：{type(exc).__name__}", file=sys.stderr)
        return 1

    print("RESET_PLAN=BEGIN（脱敏，绝不输出凭证）")
    for plan in plans:
        print(f"  target db={plan.db_name} dsn={plan.masked_dsn} tables={len(plan.table_counts)} rows={plan.total_rows}")
        for table, count in sorted(plan.table_counts.items()):
            print(f"    {table}: {count}")

    if not args.execute:
        print("RESET_PLAN=OK（dry-run；未做任何修改。加 --execute --confirm-targets 才执行）")
        return 0

    try:
        server_id = verify_container_matches_endpoint(args.container, business_dsn)
        print(f"RESET_STAGE=container_verified system_identifier={server_id[:12]}…")

        backup_root = Path(args.backup_dir) if args.backup_dir else (
            DEFAULT_BACKUP_ROOT / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        )
        backups = []
        for dsn in (business_dsn, checkpoint_dsn):
            record = backup_database(args.container, verify_target(dsn), backup_root)
            backups.append(record)
            print(f"RESET_STAGE=backup db={record['db']} bytes={record['bytes']} sha256={record['sha256'][:16]}… path={record['path']}")

        for dsn in (business_dsn, checkpoint_dsn):
            reset_database(dsn)
            print(f"RESET_STAGE=schema_rebuilt db={verify_target(dsn)}")

        prepare_business_schema(business_dsn)
        print("RESET_STAGE=business_schema_at_head")
        prepare_checkpoint_schema(checkpoint_dsn)
        print("RESET_STAGE=checkpoint_prepared")

        result = verify_reset(business_dsn, checkpoint_dsn)
    except ResetRefused as exc:
        print(f"RESET=FAIL {exc}", file=sys.stderr)
        print("RESET_ROLLBACK=按受控备份与 Git 成套回退；备份位置见上方 RESET_STAGE=backup 行。", file=sys.stderr)
        return 1

    summary = {
        "executed_at_utc": datetime.now(timezone.utc).isoformat(),
        "container": args.container,
        "server_identifier_prefix": server_id[:12],
        "backups": backups,
        "verification": result,
        "plans_before": [
            {"db": p.db_name, "tables": len(p.table_counts), "rows": p.total_rows}
            for p in plans
        ],
    }
    record_path = backup_root / "reset-record.json"
    record_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"RESET=OK record={record_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
