# -*- coding: utf-8 -*-
"""Errors raised by the filesystem-backed Creator Runtime primitives.

The primitives deliberately do not depend on the HTTP/domain error hierarchy.
A caller at an API boundary can therefore map these storage errors without
making the file layer aware of FastAPI or of the legacy SQLite Runtime.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


class RuntimeFileError(RuntimeError):
    """Base class for durable Runtime file errors."""


class RuntimeFileValidationError(RuntimeFileError, ValueError):
    """A path, key or stored value violates the file-store contract."""


class RecordNotFoundError(RuntimeFileError):
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        super().__init__(f"Runtime record does not exist: {self.path}")


class RecordAlreadyExistsError(RuntimeFileError):
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        super().__init__(f"Runtime record already exists: {self.path}")


class RecordConflictError(RuntimeFileError):
    """A compare-and-swap condition no longer matches the stored record."""

    def __init__(
        self,
        path: Path,
        *,
        expected_checksum: str | None,
        actual_checksum: str | None,
    ) -> None:
        self.path = Path(path)
        self.expected_checksum = expected_checksum
        self.actual_checksum = actual_checksum
        super().__init__(
            "Runtime record CAS conflict: "
            f"{self.path} expected={expected_checksum!r} "
            f"actual={actual_checksum!r}",
        )


class CorruptRecordError(RuntimeFileError):
    def __init__(self, path: Path, message: str) -> None:
        self.path = Path(path)
        super().__init__(f"Corrupt Runtime record {self.path}: {message}")


class LockTimeoutError(RuntimeFileError, TimeoutError):
    def __init__(self, path: Path, timeout_seconds: float | None) -> None:
        self.path = Path(path)
        self.timeout_seconds = timeout_seconds
        super().__init__(
            f"Timed out acquiring Runtime file lock {self.path} "
            f"after {timeout_seconds!r} seconds",
        )


class JsonlCorruptionError(CorruptRecordError):
    """A complete JSONL line is malformed or its durable seq is invalid."""


class SequenceConflictError(RuntimeFileError):
    def __init__(self, *, expected: int, actual: int) -> None:
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"JSONL sequence conflict: expected next seq {expected}, "
            f"got {actual}",
        )


class IdempotencyConflictError(RuntimeFileError):
    def __init__(
        self,
        *,
        owner_id: str,
        scope: str,
        idempotency_key: str,
        existing_request_hash: str,
        request_hash: str,
    ) -> None:
        self.owner_id = owner_id
        self.scope = scope
        self.idempotency_key = idempotency_key
        self.existing_request_hash = existing_request_hash
        self.request_hash = request_hash
        super().__init__(
            "Idempotency key was reused with a different request hash: "
            f"owner={owner_id!r} scope={scope!r} key={idempotency_key!r}",
        )


class IdempotencyStateConflictError(RuntimeFileError):
    def __init__(self, *, expected: str, actual: str) -> None:
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"Idempotency record state conflict: expected {expected!r}, "
            f"got {actual!r}",
        )


class FieldBlockConflictError(RuntimeFileError):
    def __init__(self, block: Any) -> None:
        self.block = block
        pointer = getattr(block, "json_pointer", None)
        owner_id = getattr(block, "owner_id", None)
        super().__init__(
            f"Field is already blocked by owner {owner_id!r} "
            f"at pointer {pointer!r}",
        )


class FieldBlockTokenError(RuntimeFileError):
    def __init__(self, block_id: str) -> None:
        self.block_id = block_id
        super().__init__(f"Field block token does not match: {block_id!r}")


class FieldBlockBaseConflictError(RuntimeFileError):
    def __init__(self, *, expected: str, actual: str) -> None:
        self.expected = expected
        self.actual = actual
        super().__init__(
            "Field block base hash no longer matches: "
            f"expected={expected!r} actual={actual!r}",
        )
