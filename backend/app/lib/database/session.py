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
    AuthoringConversationRow,
    AuthoringMessageRow,
    BenchmarkQuestionDraftRow,
    Base,
    CaseRow,
    CoCreationSessionRow,
    CoCreationTurnRow,
    ContractImpactReviewRow,
    CoverageSnapshotRow,
    EvaluationSetVersionRow,
    EvidenceFileRow,
    FileDispositionRow,
    OperationJobRow,
    QuestionRevisionRow,
    SessionRow,
    SafeStreamEventRow,
    ScenarioContractRevisionRow,
    SkillRunEvidenceRow,
    StandardPromotionProposalRow,
    TaskPackageRow,
    TeacherFeedbackRow,
    UploadBatchRow,
    UserRow,
    WorkingSetCommandRow,
    WorkingSetDraftRow,
    WorkingSetMemberRow,
    WorkspaceRow,
)
from app.lib.settings import settings


BUSINESS_SCHEMA_HEAD = "0008_authoring_question_prompt"


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
            "users": {"id", "username", "password_hash"},
            "workspaces": {"id", "owner_user_id", "updated_at"},
            "upload_batches": {"id", "workspace_id", "command_id", "revision"},
            "operation_jobs": {"id", "kind", "command_id", "status", "lease_until"},
            "task_packages": {"id", "upload_batch_id", "analysis_json", "judgment_package_json"},
            "co_creation_sessions": {"id", "task_package_id", "command_id", "kind", "projection_json"},
            "co_creation_turns": {"id", "session_id", "question_id", "answer_command_id"},
            "scenario_contract_revisions": {"id", "workspace_id", "revision", "contract_json"},
            "working_set_drafts": {"id", "workspace_id", "active_key", "revision", "freeze_intent_json"},
            "working_set_members": {"id", "draft_id", "task_package_id", "review_status"},
            "contract_impact_reviews": {"id", "draft_id", "task_package_id", "status"},
            "coverage_snapshots": {"id", "draft_id", "snapshot_json", "risk_confirmed"},
            "evaluation_set_versions": {"id", "workspace_id", "version_number", "overall_sha256"},
            "authoring_conversations": {"id", "workspace_id", "status", "revision", "active_operation_id", "source_file_ids_json"},
            "authoring_messages": {"id", "conversation_id", "sequence", "role", "content_text"},
            "safe_stream_events": {"id", "conversation_id", "sequence", "kind", "payload_json"},
            "benchmark_question_drafts": {"id", "conversation_id", "status", "revision", "input_json", "question_checkpoint_id", "question_question_count", "question_input_revision", "question_prompt_sequence"},
        }
        return all(
            columns.issubset({item["name"] for item in inspect(connection).get_columns(table)})
            for table, columns in required_columns.items()
        )


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
        SafeStreamEventRow,
        AuthoringMessageRow,
        BenchmarkQuestionDraftRow,
        AuthoringConversationRow,
        OperationJobRow,
        StandardPromotionProposalRow,
        TeacherFeedbackRow,
        QuestionRevisionRow,
        CoCreationTurnRow,
        CoCreationSessionRow,
        EvaluationSetVersionRow,
        CoverageSnapshotRow,
        ContractImpactReviewRow,
        WorkingSetCommandRow,
        WorkingSetMemberRow,
        WorkingSetDraftRow,
        SkillRunEvidenceRow,
        TaskPackageRow,
        ScenarioContractRevisionRow,
        FileDispositionRow,
        EvidenceFileRow,
        UploadBatchRow,
        CaseRow,
        WorkspaceRow,
        SessionRow,
        UserRow,
    ]
    with session_scope() as session:
        for table in tables:
            session.execute(delete(table))
