from pathlib import Path

from app.lib.settings import PROJECT_ROOT, Settings


def test_relative_storage_root_is_stable_across_entrypoint_working_directories() -> None:
    assert Settings(storage_root=Path("storage")).storage_root == PROJECT_ROOT / "storage"
