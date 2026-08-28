from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class WorkspaceRecord:
    id: str
    name: str
    description: str | None
    owner_user_id: str
    created_at: datetime
    updated_at: datetime


workspaces: dict[str, WorkspaceRecord] = {}


def add(workspace: WorkspaceRecord) -> None:
    workspaces[workspace.id] = workspace


def get(workspace_id: str) -> WorkspaceRecord | None:
    return workspaces.get(workspace_id)


def list_for_owner(owner_user_id: str) -> list[WorkspaceRecord]:
    return sorted(
        (item for item in workspaces.values() if item.owner_user_id == owner_user_id),
        key=lambda item: item.created_at,
        reverse=True,
    )


def reset() -> None:
    workspaces.clear()

