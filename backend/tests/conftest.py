import os
from pathlib import Path
import tempfile


def pytest_configure() -> None:
    """Give every pytest process an isolated durable test database and store."""

    # A PID can be reused between pytest invocations, leaving an older schema
    # behind. Each process gets a fresh isolated database and storage root.
    test_root = Path(tempfile.mkdtemp(prefix="skill-eval-platform-tests-"))
    os.environ.setdefault("DATABASE_URL", f"sqlite:///{test_root / 'business.db'}")
    os.environ.setdefault("STORAGE_ROOT", str(test_root / "storage"))
