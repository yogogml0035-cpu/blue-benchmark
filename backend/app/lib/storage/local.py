from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from app.lib.settings import settings


class StorageError(ValueError):
    """Raised when a caller attempts an unsafe or unavailable storage operation."""


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


@dataclass(frozen=True, slots=True)
class StoredObject:
    key: str
    sha256: str
    size_bytes: int


class LocalStorage:
    """A key-addressed local store that never accepts user paths as keys."""

    _NAMESPACES = frozenset({"uploads", "evidence", "versions", "staging"})

    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or settings.storage_root).expanduser().resolve()
        self.ensure_layout()

    def ensure_layout(self) -> None:
        for namespace in self._NAMESPACES:
            (self.root / namespace).mkdir(parents=True, exist_ok=True)

    def _path_for_key(self, key: str) -> Path:
        if not key or "\\" in key:
            raise StorageError("storage key must be a non-empty POSIX relative key")
        path = PurePosixPath(key)
        if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
            raise StorageError("storage key contains an unsafe path")
        if path.parts[0] not in self._NAMESPACES:
            raise StorageError("storage key uses an unknown namespace")
        resolved = (self.root / Path(*path.parts)).resolve()
        if self.root not in resolved.parents:
            raise StorageError("storage key escapes storage root")
        return resolved

    def stage_bytes(self, batch_id: str, object_id: str, content: bytes) -> StoredObject:
        key = f"staging/{batch_id}/{object_id}"
        path = self._path_for_key(key)
        self._atomic_write(path, content)
        return StoredObject(key=key, sha256=sha256_bytes(content), size_bytes=len(content))

    def publish(self, staged_key: str, final_key: str) -> None:
        staged = self._path_for_key(staged_key)
        final = self._path_for_key(final_key)
        if not staged.is_file():
            raise StorageError("staged object is missing")
        final.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staged, final)
        try:
            self._atomic_write(self._ready_path(final), b"ready\n")
        except Exception:
            try:
                final.unlink()
            except FileNotFoundError:
                pass
            try:
                self._ready_path(final).unlink()
            except FileNotFoundError:
                pass
            raise

    def write_bytes(self, key: str, content: bytes) -> StoredObject:
        path = self._path_for_key(key)
        self._atomic_write(path, content)
        return StoredObject(key=key, sha256=sha256_bytes(content), size_bytes=len(content))

    def read_bytes(self, key: str) -> bytes:
        path = self._path_for_key(key)
        try:
            return path.read_bytes()
        except FileNotFoundError as exc:
            raise StorageError("stored object is missing") from exc

    def delete(self, key: str) -> None:
        path = self._path_for_key(key)
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        try:
            self._ready_path(path).unlink()
        except FileNotFoundError:
            return

    def exists(self, key: str) -> bool:
        path = self._path_for_key(key)
        return path.is_file() and self._ready_path(path).is_file()

    def is_ready(self, key: str) -> bool:
        path = self._path_for_key(key)
        return path.is_file() and self._ready_path(path).is_file()

    @staticmethod
    def _ready_path(path: Path) -> Path:
        return path.with_name(f".{path.name}.ready")

    @staticmethod
    def _atomic_write(path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as temporary:
                temporary.write(content)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_name, path)
        except Exception:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
            raise
