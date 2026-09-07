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
    for expected in [
        "scenes", "scene_credentials", "eval_questions", "batch_upload_commands",
        "question_run_threads", "question_run_events",
    ]:
        assert expected in tables, expected
    for legacy in ["cases", "workspaces", "benchmark_question_drafts", "human_scores"]:
        assert legacy not in tables, legacy
    with engine.connect() as connection:
        revisions = connection.execute(
            sa.text("SELECT version_num FROM alembic_version")
        ).scalars().all()
    assert revisions == ["0022_drop_scene_credential_label"]
    question_columns = {item["name"] for item in sa.inspect(engine).get_columns("eval_questions")}
    assert {"criteria_confirmed", "ever_published"}.issubset(question_columns)
    credential_columns = {
        item["name"] for item in sa.inspect(engine).get_columns("scene_credentials")
    }
    assert "token_plaintext" in credential_columns
    assert "label" not in credential_columns


def test_review_contracts_upgrade_backfills_published(tmp_path) -> None:
    """0018 -> 0019: published questions backfill confirmed+ever_published."""

    database_url = f"sqlite:///{tmp_path / 'upgrade.db'}"
    config = _alembic_config(database_url)
    command.upgrade(config, "0018_m0_question_library")
    engine = sa.create_engine(database_url)
    now = "2026-09-03 00:00:00+00:00"
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "INSERT INTO scenes (id, name, created_at, updated_at) "
                "VALUES ('s1', '场景', :now, :now)"
            ),
            {"now": now},
        )
        connection.execute(
            sa.text(
                "INSERT INTO eval_questions "
                "(id, scene_id, client_case_id, title, task_prompt, "
                " reference_examples_json, bad_cases_json, reference_answer, "
                " memory_materials_json, status, content_revision, created_at, updated_at, published_at) "
                "VALUES ('q-pub', 's1', 'c-pub', '已发布', '任务', '[]', '[]', '答案', '[]', "
                "'published', 1, :now, :now, :now)"
            ),
            {"now": now},
        )
        connection.execute(
            sa.text(
                "INSERT INTO eval_questions "
                "(id, scene_id, client_case_id, title, task_prompt, "
                " reference_examples_json, bad_cases_json, reference_answer, "
                " memory_materials_json, status, content_revision, created_at, updated_at) "
                "VALUES ('q-pending', 's1', 'c-pending', '待审', '任务', '[]', '[]', '答案', '[]', "
                "'pending_review', 1, :now, :now)"
            ),
            {"now": now},
        )

    command.upgrade(config, "head")

    with engine.connect() as connection:
        pub = connection.execute(
            sa.text(
                "SELECT criteria_confirmed, ever_published FROM eval_questions WHERE id='q-pub'"
            )
        ).one()
        pending = connection.execute(
            sa.text(
                "SELECT criteria_confirmed, ever_published FROM eval_questions WHERE id='q-pending'"
            )
        ).one()
    assert bool(pub[0]) and bool(pub[1]), "published history must backfill both facts"
    assert not pending[0] and not pending[1], "unpublished history stays unconfirmed"


def test_credential_one_to_one_upgrade_normalizes_duplicates(tmp_path) -> None:
    """0019 -> 0020: scenes keep their newest active credential; the rest are
    revoked as ``model-migration``. Already-revoked rows stay untouched."""

    database_url = f"sqlite:///{tmp_path / 'one-to-one.db'}"
    config = _alembic_config(database_url)
    command.upgrade(config, "0019_m0_web_review_contracts")
    engine = sa.create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            sa.text("INSERT INTO scenes (id, name, created_at, updated_at) "
                    "VALUES ('s1', '场景', '2026-09-01 00:00:00', '2026-09-01 00:00:00')")
        )
        for credential_id, created_at, revoked in [
            ("c-old", "2026-09-01 01:00:00", None),
            ("c-new", "2026-09-02 01:00:00", None),
            ("c-ancient", "2026-08-01 01:00:00", "2026-08-02 01:00:00"),
        ]:
            connection.execute(
                sa.text(
                    "INSERT INTO scene_credentials "
                    "(id, scene_id, token_hash, created_at, revoked_at) "
                    "VALUES (:id, 's1', :hash, :created, :revoked)"
                ),
                {
                    "id": credential_id,
                    "hash": f"hash-{credential_id}",
                    "created": created_at,
                    "revoked": revoked,
                },
            )

    command.upgrade(config, "head")

    with engine.connect() as connection:
        rows = dict(
            connection.execute(
                sa.text(
                    "SELECT id, revoked_reason FROM scene_credentials ORDER BY created_at"
                )
            ).all()
        )
        columns = {item["name"] for item in sa.inspect(engine).get_columns("scene_credentials")}
    assert "token_plaintext" in columns
    assert rows["c-new"] is None, "newest active credential must survive"
    assert rows["c-old"] == "model-migration"
    assert rows["c-ancient"] is None, "pre-revoked history keeps its original state"


def test_credential_label_upgrade_drops_and_downgrade_restores(tmp_path) -> None:
    """0021 -> 0022: the unused ``label`` column is dropped; downgrade restores
    it as nullable. Existing rows survive both directions."""

    database_url = f"sqlite:///{tmp_path / 'label-drop.db'}"
    config = _alembic_config(database_url)
    command.upgrade(config, "0021_m0_runtime_messages_threads")
    engine = sa.create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "INSERT INTO scenes (id, name, created_at, updated_at) "
                "VALUES ('s1', '场景', '2026-09-07 00:00:00', '2026-09-07 00:00:00')"
            )
        )
        # 0001 builds the schema from the current ORM metadata (label already
        # gone), so a legacy-head database is simulated by adding it back.
        connection.execute(
            sa.text("ALTER TABLE scene_credentials ADD COLUMN label VARCHAR(200)")
        )
        connection.execute(
            sa.text(
                "INSERT INTO scene_credentials "
                "(id, scene_id, token_hash, label, created_at) "
                "VALUES ('c1', 's1', 'hash-c1', '旧名称', '2026-09-07 01:00:00')"
            )
        )

    command.upgrade(config, "head")

    with engine.connect() as connection:
        columns = {item["name"] for item in sa.inspect(engine).get_columns("scene_credentials")}
        kept = connection.execute(
            sa.text("SELECT token_hash FROM scene_credentials WHERE id='c1'")
        ).scalar_one()
    assert "label" not in columns
    assert kept == "hash-c1", "dropping the dead column must keep the credential row"

    command.downgrade(config, "0021_m0_runtime_messages_threads")

    with engine.connect() as connection:
        columns = {item["name"] for item in sa.inspect(engine).get_columns("scene_credentials")}
        label_value = connection.execute(
            sa.text("SELECT label FROM scene_credentials WHERE id='c1'")
        ).scalar_one()
    assert "label" in columns
    assert label_value is None, "restored column has no backfill; NULL is the contract"


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
    engine = sa.create_engine(database_url)

    # 0022 -> 0021: the dropped label column is restored, nothing else moves.
    command.downgrade(config, "-1")
    credential_columns = {
        item["name"] for item in sa.inspect(engine).get_columns("scene_credentials")
    }
    assert "label" in credential_columns
    assert "question_run_threads" in _table_names(engine)

    # 0021 -> 0020: the runtime log/registry tables disappear, nothing else.
    command.downgrade(config, "-1")
    tables_after_runtime = _table_names(engine)
    assert "question_run_threads" not in tables_after_runtime
    assert "question_run_events" not in tables_after_runtime
    assert "eval_questions" in tables_after_runtime

    # 0020 -> 0019: the plaintext column disappears, tables stay.
    command.downgrade(config, "-1")
    credential_columns = {
        item["name"] for item in sa.inspect(engine).get_columns("scene_credentials")
    }
    assert "token_plaintext" not in credential_columns
    assert "scene_credentials" in _table_names(engine)

    # 0019 -> 0018: the review-contract columns disappear, tables stay.
    command.downgrade(config, "-1")
    question_columns = {item["name"] for item in sa.inspect(engine).get_columns("eval_questions")}
    assert "criteria_confirmed" not in question_columns
    assert "ever_published" not in question_columns
    assert "eval_questions" in _table_names(engine)

    # 0018 -> 0017: the whole M0 shape is dropped, legacy shape restored.
    command.downgrade(config, "-1")
    tables = _table_names(engine)
    for new_table in ["scenes", "scene_credentials", "eval_questions", "batch_upload_commands"]:
        assert new_table not in tables, new_table
    assert "workspaces" in tables
    # And upgrading again converges to the new head.
    command.upgrade(config, "head")
    assert "eval_questions" in _table_names(engine)
