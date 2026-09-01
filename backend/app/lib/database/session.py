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
    BenchmarkQuestionRevisionRow,
    Base,
    CaseRow,
    CoCreationSessionRow,
    CoCreationTurnRow,
    ContractImpactReviewRow,
    CoverageSnapshotRow,
    EvaluationSetVersionRow,
    EvaluationSubmissionRow,
    EvidenceFileRow,
    FileDispositionRow,
    HumanScoreItemRow,
    HumanScoreRow,
    OperationJobRow,
    QuestionRevisionRow,
    SessionRow,
    SafeStreamEventRow,
    RubricDraftRow,
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


BUSINESS_SCHEMA_HEAD = "0015_question_lifecycle"


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
            "working_set_members": {"id", "draft_id", "task_package_id", "question_revision_id", "question_revision_number", "question_revision_hash", "review_status"},
            "contract_impact_reviews": {"id", "draft_id", "task_package_id", "status"},
            "coverage_snapshots": {"id", "draft_id", "snapshot_json", "risk_confirmed"},
            "evaluation_set_versions": {"id", "workspace_id", "version_number", "overall_sha256"},
            "authoring_conversations": {"id", "workspace_id", "status", "revision", "active_operation_id", "source_file_ids_json"},
            "authoring_messages": {"id", "conversation_id", "sequence", "role", "content_text"},
            "safe_stream_events": {"id", "conversation_id", "sequence", "kind", "payload_json"},
            "benchmark_question_drafts": {"id", "conversation_id", "status", "revision", "input_json", "bad_samples_json", "lifecycle_status", "active_revision_id", "lifecycle_receipts_json", "lifecycle_pending_json", "question_checkpoint_id", "question_question_count", "question_input_revision", "question_prompt_sequence"},
            "benchmark_rubric_drafts": {"id", "workspace_id", "question_draft_id", "status", "revision", "source_question_revision", "source_question_hash", "rubric_json"},
            "benchmark_question_revisions": {"id", "workspace_id", "question_draft_id", "revision_number", "source_question_revision", "contract_revision_id", "question_snapshot_json", "bad_samples_json", "rubric_json", "content_sha256", "publication_status"},
            "evaluation_submissions": {"id", "workspace_id", "question_revision_id", "content_storage_key", "source", "original_name", "media_type", "size_bytes", "sha256", "command_id", "payload_hash", "submitted_by", "submitted_at"},
            "human_scores": {"id", "submission_id", "question_revision_id", "parent_score_id", "status", "total_score", "critical_passed", "passed", "overall_reason", "command_id", "payload_hash", "scored_by", "submitted_at"},
            "human_score_items": {"id", "score_id", "criterion_id", "score", "reason", "hard_fail_triggered", "critical_passed", "created_at"},
        }
        columns_ready = all(
            columns.issubset({item["name"] for item in inspect(connection).get_columns(table)})
            for table, columns in required_columns.items()
        )
        required_unique_constraints = {
            "benchmark_question_revisions": {
                "uq_benchmark_question_revision_workspace_identity",
            },
            "evaluation_submissions": {
                "uq_evaluation_submission_command",
                "uq_evaluation_submission_storage_key",
                "uq_evaluation_submission_revision_identity",
            },
            "human_scores": {
                "uq_human_score_command",
                "uq_human_score_submission_identity",
            },
            "human_score_items": {"uq_human_score_item_criterion"},
        }
        unique_ready = all(
            names.issubset(
                {item.get("name") for item in inspect(connection).get_unique_constraints(table)}
            )
            for table, names in required_unique_constraints.items()
        )
        required_check_constraints = {
            "evaluation_submissions": {
                "ck_evaluation_submission_source",
                "ck_evaluation_submission_size",
                "ck_evaluation_submission_sha256",
            },
            "human_scores": {"ck_human_score_status", "ck_human_score_total"},
            "human_score_items": {"ck_human_score_item_score"},
        }
        checks_ready = all(
            names.issubset(
                {item.get("name") for item in inspect(connection).get_check_constraints(table)}
            )
            for table, names in required_check_constraints.items()
        )
        required_foreign_keys = {
            "evaluation_submissions": {"fk_evaluation_submission_question_revision_workspace"},
            "human_scores": {
                "fk_human_score_submission",
                "fk_human_score_question_revision",
                "fk_human_score_parent_submission",
            },
        }
        foreign_keys_ready = all(
            names.issubset(
                {item.get("name") for item in inspect(connection).get_foreign_keys(table)}
            )
            for table, names in required_foreign_keys.items()
        )
        required_indexes = {
            "evaluation_submissions": {"ix_evaluation_submission_workspace_created"},
            "human_scores": {
                "ix_human_score_submission_submitted",
                "uq_human_score_submission_parent",
            },
            "human_score_items": {"ix_human_score_items_score_id"},
        }
        indexes_ready = all(
            names.issubset(
                {item.get("name") for item in inspect(connection).get_indexes(table)}
            )
            for table, names in required_indexes.items()
        )
        return columns_ready and unique_ready and checks_ready and foreign_keys_ready and indexes_ready


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
        HumanScoreItemRow,
        HumanScoreRow,
        EvaluationSubmissionRow,
        RubricDraftRow,
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
        BenchmarkQuestionRevisionRow,
        BenchmarkQuestionDraftRow,
        AuthoringConversationRow,
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
