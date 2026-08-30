from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any, Iterable

from deepagents.backends import BackendProtocol
from deepagents.backends.protocol import (
    DeleteResult,
    EditResult,
    FileData,
    FileInfo,
    GrepMatch,
    GrepResult,
    GlobResult,
    LsResult,
    ReadResult,
    WriteResult,
)

from app.features.case_builder import ingestion_repository
from app.lib.storage import LocalStorage, StorageError


class EvidenceValidationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class EvidenceDocument:
    file_id: str
    name: str
    storage_key: str
    size_bytes: int
    sha256: str
    parse_state: str
    canonical_view: dict | None
    role: str
    ignored: bool
    visibility: str


def documents_for_files(file_ids: list[str] | tuple[str, ...]) -> dict[str, EvidenceDocument]:
    result: dict[str, EvidenceDocument] = {}
    for file_id in file_ids:
        record = ingestion_repository.get_file(file_id)
        if record is None:
            continue
        result[file_id] = EvidenceDocument(
            file_id=record.id,
            name=record.original_name,
            storage_key=record.storage_key,
            size_bytes=record.size_bytes,
            sha256=record.sha256,
            parse_state=record.parse_state,
            canonical_view=record.canonical_view,
            role=record.role,
            ignored=record.ignored,
            visibility=record.visibility,
        )
    return result


class ReadOnlyEvidenceBackend(BackendProtocol):
    """Virtual `/evidence/<file-id>` backend with no host-path access."""

    def __init__(self, documents: dict[str, EvidenceDocument], storage: LocalStorage | None = None) -> None:
        self.documents = dict(documents)
        self.storage = storage or LocalStorage()

    @staticmethod
    def _file_id(path: str) -> str | None:
        if not path.startswith("/") or "\\" in path:
            return None
        parts = PurePosixPath(path).parts
        if len(parts) != 3 or parts[0] != "/" or parts[1] != "evidence":
            return None
        return parts[2]

    def _document(self, path: str) -> EvidenceDocument | None:
        file_id = self._file_id(path)
        return self.documents.get(file_id) if file_id else None

    def _content(self, document: EvidenceDocument) -> str:
        try:
            content = self.storage.read_bytes(document.storage_key)
        except StorageError as exc:
            raise FileNotFoundError(document.file_id) from exc
        return content.decode("utf-8-sig")

    def ls(self, path: str) -> LsResult:
        if path.rstrip("/") not in {"", "/", "/evidence"}:
            return LsResult(error="Error: evidence path is outside the current scope")
        entries = [
            FileInfo(path=f"/evidence/{item.file_id}", is_dir=False, size=item.size_bytes)
            for item in sorted(self.documents.values(), key=lambda value: value.file_id)
        ]
        return LsResult(entries=entries)

    def read(self, file_path: str, offset: int = 0, limit: int = 2000) -> ReadResult:
        document = self._document(file_path)
        if document is None:
            return ReadResult(error="Error: file is outside the current evidence scope")
        if limit <= 0:
            return ReadResult(total_lines=0, no_lines_requested=True)
        try:
            content = self._content(document)
        except (FileNotFoundError, UnicodeDecodeError):
            return ReadResult(error="Error: evidence file cannot be read")
        lines = content.splitlines()
        safe_offset = max(offset, 0)
        selected = lines[safe_offset : safe_offset + limit]
        next_offset = safe_offset + len(selected) if safe_offset + len(selected) < len(lines) else None
        text = "\n".join(selected)
        if selected and content.endswith("\n") and safe_offset + len(selected) == len(lines):
            text += "\n"
        return ReadResult(
            file_data=FileData(content=text, encoding="utf-8", created_at=datetime.now(timezone.utc).isoformat(), modified_at=datetime.now(timezone.utc).isoformat()),
            total_lines=len(lines),
            start_line=safe_offset + 1 if selected else max(1, len(lines)),
            end_line=safe_offset + len(selected) if selected else max(1, len(lines)),
            next_offset=next_offset,
        )

    def glob(self, pattern: str, path: str | None = None) -> GlobResult:
        base = (path or "/evidence").rstrip("/") or "/evidence"
        if base not in {"/evidence", "/"}:
            if self._document(base) is None:
                return GlobResult(error="Error: glob path is outside the current scope")
        matches = []
        for document in sorted(self.documents.values(), key=lambda value: value.file_id):
            candidate = f"/evidence/{document.file_id}"
            relative = candidate.removeprefix(base + "/") if base != "/" else candidate.removeprefix("/")
            if fnmatch.fnmatch(candidate, pattern) or fnmatch.fnmatch(relative, pattern) or pattern in {"*", "**", "**/*"}:
                matches.append(FileInfo(path=candidate, is_dir=False, size=document.size_bytes))
        return GlobResult(matches=matches)

    def grep(self, pattern: str, path: str | None = None, glob: str | None = None, *, max_count: int | None = None) -> GrepResult:
        if path and path.rstrip("/") not in {"", "/", "/evidence"} and self._document(path) is None:
            return GrepResult(error="Error: grep path is outside the current scope")
        matches: list[GrepMatch] = []
        for document in sorted(self.documents.values(), key=lambda value: value.file_id):
            virtual_path = f"/evidence/{document.file_id}"
            if path and path.rstrip("/") not in {"", "/", "/evidence"} and path.rstrip("/") != virtual_path:
                continue
            if glob and not (fnmatch.fnmatch(virtual_path, glob) or fnmatch.fnmatch(document.name, glob)):
                continue
            try:
                lines = self._content(document).splitlines()
            except (FileNotFoundError, UnicodeDecodeError):
                continue
            for line_number, line in enumerate(lines, start=1):
                if pattern in line:
                    matches.append(GrepMatch(path=virtual_path, line=line_number, text=line))
                    if max_count is not None and len(matches) >= max_count:
                        return GrepResult(matches=matches, truncated=False)
        return GrepResult(matches=matches)

    def write(self, file_path: str, content: str) -> WriteResult:
        return WriteResult(error="Error: evidence backend is read-only")

    def edit(self, file_path: str, old_string: str, new_string: str, replace_all: bool = False) -> EditResult:
        return EditResult(error="Error: evidence backend is read-only")

    def delete(self, file_path: str) -> DeleteResult:
        return DeleteResult(error="Error: evidence backend is read-only")


def validate_evidence_refs(
    refs: Iterable[Any],
    documents: dict[str, EvidenceDocument],
) -> None:
    """Validate model locators against deterministic application metadata."""

    for ref in refs:
        source_id = getattr(ref, "source_id", None)
        document = documents.get(source_id)
        if document is None:
            raise EvidenceValidationError("evidence reference is outside the current scope")
        locator = getattr(ref, "locator", None)
        if locator is None:
            continue
        kind = getattr(locator, "kind", None)
        if kind == "line_range":
            line_count = int((document.canonical_view or {}).get("line_count") or 0)
            if line_count <= 0:
                raise EvidenceValidationError("line locator refers to a file without line metadata")
            if locator.start_line < 1 or locator.end_line > line_count:
                raise EvidenceValidationError("line locator is outside the canonical view")
        elif kind == "json_pointer":
            if (document.canonical_view or {}).get("kind") not in {"json", "jsonl"}:
                raise EvidenceValidationError("JSON pointer refers to a non-JSON evidence file")
            if not locator.pointer.startswith("/"):
                raise EvidenceValidationError("JSON pointer must be absolute")
        elif kind == "event_id":
            event_ids = (document.canonical_view or {}).get("event_ids")
            if event_ids is not None and locator.event_id not in event_ids:
                raise EvidenceValidationError("event locator is outside the canonical view")
