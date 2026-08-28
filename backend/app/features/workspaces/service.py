from datetime import datetime, timezone
from uuid import uuid4

from app.features.auth.repository import UserRecord
from app.features.workspaces import repository
from app.features.workspaces.schemas import Workspace, WorkspaceCreateRequest
from app.lib.errors import AppError


def to_workspace(record: repository.WorkspaceRecord) -> Workspace:
    return Workspace(
        id=record.id,
        name=record.name,
        description=record.description,
        owner_user_id=record.owner_user_id,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def create(payload: WorkspaceCreateRequest, user: UserRecord) -> Workspace:
    now = datetime.now(timezone.utc)
    record = repository.WorkspaceRecord(
        id=str(uuid4()),
        name=payload.name,
        description=payload.description,
        owner_user_id=user.id,
        created_at=now,
        updated_at=now,
    )
    repository.add(record)
    return to_workspace(record)


def list_for_user(user: UserRecord) -> list[Workspace]:
    return [to_workspace(item) for item in repository.list_for_owner(user.id)]


def assert_owner(workspace_id: str, user: UserRecord) -> repository.WorkspaceRecord:
    workspace = repository.get(workspace_id)
    if workspace is None:
        raise AppError(404, "RESOURCE_NOT_FOUND", "私有场景不存在。")
    if workspace.owner_user_id != user.id:
        raise AppError(403, "FORBIDDEN", "你无权访问这个私有场景。")
    return workspace


def get_owned(workspace_id: str, user: UserRecord) -> Workspace:
    return to_workspace(assert_owner(workspace_id, user))

