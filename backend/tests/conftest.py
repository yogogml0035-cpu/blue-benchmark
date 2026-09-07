import os
from pathlib import Path
import tempfile


def pytest_configure() -> None:
    """Give every pytest process an isolated durable test database."""

    # A PID can be reused between pytest invocations, leaving an older schema
    # behind. Each process gets a fresh isolated database.
    test_root = Path(tempfile.mkdtemp(prefix="blue-benchmark-tests-"))
    os.environ.setdefault("DATABASE_URL", f"sqlite:///{test_root / 'business.db'}")
    os.environ.setdefault("AI_RUNTIME_MODE", "fake")
    os.environ.setdefault("DATABASE_SCHEMA_CHECK_ON_STARTUP", "false")
