"""Migration contract: fresh DB, legacy-head upgrade, and downgrade."""

import os
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config


@pytest.fixture(autouse=True)
def _clear_alembic_url():
    yield
    os.environ.pop("ALEMBIC_DATABASE_URL", None)


def _alembic_config(database_url: str) -> Config:
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    # migrations/env.py reads this override instead of the application settings.
    os.environ["ALEMBIC_DATABASE_URL"] = database_url
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def _table_names(engine: sa.Engine) -> set[str]:
    with engine.connect() as connection:
        return set(sa.inspect(connection).get_table_names())


def test_fresh_database_reaches_new_head(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'fresh.db'}"
    command.upgrade(_alembic_config(database_url), "head")
    engine = sa.create_engine(database_url)
    tables = _table_names(engine)
    for expected in ["scenes", "scene_credentials", "eval_questions", "batch_upload_commands"]:
        assert expected in tables, expected
    for legacy in ["cases", "workspaces", "benchmark_question_drafts", "human_scores"]:
        assert legacy not in tables, legacy
    with engine.connect() as connection:
        revisions = connection.execute(
            sa.text("SELECT version_num FROM alembic_version")
        ).scalars().all()
    assert revisions == ["0018_m0_question_library"]


def test_legacy_head_upgrade_drops_old_business_tables(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'legacy.db'}"
    engine = sa.create_engine(database_url)

    # Build a minimal legacy schema stamped at the previous head.
    metadata = sa.MetaData()
    sa.Table(
        "workspaces",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
    )
    sa.Table(
        "cases",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), nullable=False),
    )
    sa.Table(
        "human_scores",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("submission_id", sa.String(36), nullable=False),
    )
    sa.Table(
        "operation_jobs",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("kind", sa.String(64), nullable=False),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(sa.text("INSERT INTO workspaces (id, name) VALUES ('w1', '旧场景')"))
        connection.execute(sa.text("INSERT INTO cases (id, workspace_id) VALUES ('c1', 'w1')"))
        connection.execute(sa.text("INSERT INTO operation_jobs (id, kind) VALUES ('j1', 'rubric_process')"))
        connection.execute(
            sa.text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
        )
        connection.execute(
            sa.text("INSERT INTO alembic_version (version_num) VALUES ('0017_external_input_metadata')")
        )

    command.upgrade(_alembic_config(database_url), "head")

    tables = _table_names(engine)
    for legacy in ["workspaces", "cases", "human_scores"]:
        assert legacy not in tables, legacy
    for expected in ["scenes", "eval_questions"]:
        assert expected in tables, expected
    with engine.connect() as connection:
        jobs = connection.execute(sa.text("SELECT COUNT(*) FROM operation_jobs")).scalar()
    assert jobs == 0, "legacy job history must be cleared"


def test_downgrade_restores_executable_schema(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'roundtrip.db'}"
    config = _alembic_config(database_url)
    command.upgrade(config, "head")
    command.downgrade(config, "-1")
    engine = sa.create_engine(database_url)
    tables = _table_names(engine)
    for new_table in ["scenes", "scene_credentials", "eval_questions", "batch_upload_commands"]:
        assert new_table not in tables, new_table
    assert "workspaces" in tables
    # And upgrading again converges to the new head.
    command.upgrade(config, "head")
    assert "eval_questions" in _table_names(engine)
