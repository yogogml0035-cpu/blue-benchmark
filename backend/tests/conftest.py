import os
from pathlib import Path
import tempfile


def pytest_configure() -> None:
    """Give every pytest process an isolated durable test database and store."""

    test_root = Path(tempfile.gettempdir()) / f"skill-eval-platform-tests-{os.getpid()}"
    os.environ.setdefault("DATABASE_URL", f"sqlite:///{test_root / 'business.db'}")
    os.environ.setdefault("STORAGE_ROOT", str(test_root / "storage"))
