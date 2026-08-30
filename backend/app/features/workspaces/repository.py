from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select

from app.lib.database import as_utc, session_scope
from app.lib.database.models import WorkspaceRow


@dataclass(slots=True)
class WorkspaceRecord:
    id: str
    name: str
    description: str | None
    owner_user_id: str
    created_at: datetime
    updated_at: datetime


def add(workspace: WorkspaceRecord) -> None:
    with session_scope() as session:
        session.add(
            WorkspaceRow(
                id=workspace.id,
                name=workspace.name,
                description=workspace.description,
                owner_user_id=workspace.owner_user_id,
                created_at=workspace.created_at,
                updated_at=workspace.updated_at,
            )
        )


def _to_record(row: WorkspaceRow) -> WorkspaceRecord:
    return WorkspaceRecord(
        id=row.id,
        name=row.name,
        description=row.description,
        owner_user_id=row.owner_user_id,
        created_at=as_utc(row.created_at),
        updated_at=as_utc(row.updated_at),
    )


def get(workspace_id: str) -> WorkspaceRecord | None:
    with session_scope() as session:
        row = session.get(WorkspaceRow, workspace_id)
        return _to_record(row) if row else None


def list_for_owner(owner_user_id: str) -> list[WorkspaceRecord]:
    with session_scope() as session:
        rows = session.scalars(
            select(WorkspaceRow)
            .where(WorkspaceRow.owner_user_id == owner_user_id)
            .order_by(WorkspaceRow.created_at.desc())
        ).all()
        return [_to_record(row) for row in rows]


def reset() -> None:
    from app.lib.database import clear_business_data

    clear_business_data()
