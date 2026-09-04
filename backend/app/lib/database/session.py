from contextlib import contextmanager
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, delete, event, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.engine.url import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.lib.database.models import (
    AgentRunAttemptRow,
    Base,
    BatchUploadCommandRow,
    EvalQuestionRow,
    OperationJobRow,
    SceneCredentialRow,
    SceneRow,
    SessionRow,
    UserRow,
)
from app.lib.settings import settings


BUSINESS_SCHEMA_HEAD = "0020_credential_one_to_one"


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _create_engine(database_url: str) -> Engine:
    if database_url.startswith("sqlite"):
        database_path = make_url(database_url).database
        if database_path and database_path != ":memory:":
            Path(database_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
    connect_args = {"check_same_thread": False, "timeout": 10} if database_url.startswith("sqlite") else {}
    return create_engine(database_url, future=True, pool_pre_ping=True, connect_args=connect_args)


engine = _create_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)


if engine.dialect.name == "sqlite":

    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def check_schema_ready(database_engine: Engine = engine) -> bool:
    required = set(Base.metadata.tables)
    with database_engine.connect() as connection:
        tables = set(inspect(connection).get_table_names())
        if not required.issubset(tables) or "alembic_version" not in tables:
            return False
        revisions = connection.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
        if revisions != [BUSINESS_SCHEMA_HEAD]:
            return False
        required_columns = {
            "users": {"id", "username", "password_hash", "password_generation", "admin_slot"},
            "sessions": {"token_hash", "user_id", "password_generation"},
            "scenes": {"id", "name", "created_at", "updated_at"},
            "scene_credentials": {"id", "scene_id", "token_hash", "token_plaintext", "revoked_at", "last_used_at"},
            "eval_questions": {
                "id",
                "scene_id",
                "client_case_id",
                "title",
                "task_prompt",
                "reference_examples_json",
                "bad_cases_json",
                "reference_answer",
                "memory_materials_json",
                "criteria_json",
                "criteria_confirmed",
                "status",
                "content_revision",
                "active_operation_id",
                "last_error_json",
                "published_at",
                "ever_published",
            },
            "batch_upload_commands": {"id", "scene_id", "command_id", "payload_hash", "status", "result_json"},
            "operation_jobs": {"id", "kind", "command_id", "status", "lease_until", "business_revision"},
        }
        columns_ready = all(
            columns.issubset({item["name"] for item in inspect(connection).get_columns(table)})
            for table, columns in required_columns.items()
        )
        required_unique_constraints = {
            "scenes": {"uq_scene_name"},
            "scene_credentials": {"uq_scene_credential_token_hash"},
            "eval_questions": {"uq_eval_question_scene_client_case"},
            "batch_upload_commands": {"uq_batch_upload_command"},
        }
        unique_ready = all(
            names.issubset(
                {item.get("name") for item in inspect(connection).get_unique_constraints(table)}
            )
            for table, names in required_unique_constraints.items()
        )
        required_check_constraints = {
            "batch_upload_commands": {"ck_batch_upload_command_status"},
        }
        checks_ready = all(
            names.issubset(
                {item.get("name") for item in inspect(connection).get_check_constraints(table)}
            )
            for table, names in required_check_constraints.items()
        )
        required_indexes = {
            "scene_credentials": {"ix_scene_credential_active"},
            "eval_questions": {"ix_eval_question_status"},
            "operation_jobs": {"ix_operation_claim"},
        }
        indexes_ready = all(
            names.issubset(
                {item.get("name") for item in inspect(connection).get_indexes(table)}
            )
            for table, names in required_indexes.items()
        )
        return columns_ready and unique_ready and checks_ready and indexes_ready


def create_schema_for_tests(database_engine: Engine = engine) -> None:
    """Create the current schema for isolated tests.

    Production uses the separate Alembic migration command. This helper keeps
    the HTTP contract tests self-contained without making application startup
    mutate a production database.
    """

    Base.metadata.create_all(database_engine)
    with database_engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE IF NOT EXISTS alembic_version "
                "(version_num VARCHAR(32) NOT NULL)"
            )
        )
        connection.execute(text("DELETE FROM alembic_version"))
        connection.execute(
            text("INSERT INTO alembic_version (version_num) VALUES (:revision)"),
            {"revision": BUSINESS_SCHEMA_HEAD},
        )


def clear_business_data() -> None:
    create_schema_for_tests()
    tables = [
        AgentRunAttemptRow,
        OperationJobRow,
        BatchUploadCommandRow,
        EvalQuestionRow,
        SceneCredentialRow,
        SceneRow,
        SessionRow,
        UserRow,
    ]
    with session_scope() as session:
        for table in tables:
            session.execute(delete(table))
