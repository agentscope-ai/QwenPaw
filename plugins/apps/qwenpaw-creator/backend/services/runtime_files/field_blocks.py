# -*- coding: utf-8 -*-
"""Short TTL field blocks used to reduce Project editing conflicts."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager
from datetime import datetime, timedelta
import hmac
import os
from pathlib import Path
import secrets
from uuid import uuid4

from .atomic_store import AtomicJsonRecordStore, durable_unlink
from .errors import (
    FieldBlockBaseConflictError,
    FieldBlockConflictError,
    FieldBlockTokenError,
    RecordAlreadyExistsError,
    RecordNotFoundError,
    RuntimeFileValidationError,
)
from .locking import CrossProcessFileLock
from .models import FieldBlockRecord, utc_now


def parse_json_pointer(pointer: str) -> tuple[str, ...]:
    """Validate and decode an RFC 6901 JSON Pointer into path segments."""

    if pointer == "":
        return ()
    if not pointer.startswith("/"):
        raise RuntimeFileValidationError(
            "JSON pointer must be empty or begin with '/'",
        )
    decoded: list[str] = []
    for raw_segment in pointer.split("/")[1:]:
        segment: list[str] = []
        index = 0
        while index < len(raw_segment):
            character = raw_segment[index]
            if character != "~":
                segment.append(character)
                index += 1
                continue
            if index + 1 >= len(raw_segment) or raw_segment[index + 1] not in {
                "0",
                "1",
            }:
                raise RuntimeFileValidationError(
                    f"invalid RFC 6901 escape in JSON pointer: {pointer!r}",
                )
            segment.append("~" if raw_segment[index + 1] == "0" else "/")
            index += 2
        decoded.append("".join(segment))
    return tuple(decoded)


def pointers_overlap(first: str, second: str) -> bool:
    first_parts = parse_json_pointer(first)
    second_parts = parse_json_pointer(second)
    shared = min(len(first_parts), len(second_parts))
    return first_parts[:shared] == second_parts[:shared]


class FieldBlockStore:
    """Coordinates field blocks under one Project's ``runtime/locks/fields``.

    A single short index lock makes overlap checking and record publication one
    atomic operation across processes.  Expired JSON files are diagnostics only
    and are durably removed while holding that lock.  Project writes must still
    use field-value CAS; a block is not an authorization or correctness layer.
    """

    def __init__(
        self,
        root: str | os.PathLike[str],
        *,
        lock_timeout_seconds: float | None = 10.0,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.root = Path(root)
        self.lock_timeout_seconds = lock_timeout_seconds
        self.clock = clock
        self.index_lock_path = self.root / ".index.lock"

    def _index_lock(self) -> CrossProcessFileLock:
        return CrossProcessFileLock(
            self.index_lock_path,
            timeout_seconds=self.lock_timeout_seconds,
        )

    def _path(self, block_id: str) -> Path:
        safe = block_id.strip()
        if (
            not safe
            or safe in {".", ".."}
            or any(character in safe for character in ("/", "\\", "\x00"))
            or any(
                ord(character) < 32 or ord(character) == 127
                for character in safe
            )
        ):
            raise RuntimeFileValidationError(
                f"invalid field block ID: {block_id!r}",
            )
        return self.root / f"{safe}.json"

    def _store(self, block_id: str) -> AtomicJsonRecordStore[FieldBlockRecord]:
        path = self._path(block_id)
        return AtomicJsonRecordStore(
            path,
            FieldBlockRecord,
            lock_path=self.root / ".record-locks" / f"{path.name}.lock",
            lock_timeout_seconds=self.lock_timeout_seconds,
        )

    def _records_unlocked(self) -> list[FieldBlockRecord]:
        records: list[FieldBlockRecord] = []
        if not self.root.exists():
            return records
        for path in sorted(self.root.glob("*.json")):
            records.append(
                AtomicJsonRecordStore(path, FieldBlockRecord).read(),
            )
        return records

    def _cleanup_unlocked(self, now: datetime) -> list[str]:
        expired: list[str] = []
        for record in self._records_unlocked():
            if record.expires_at <= now:
                durable_unlink(self._path(record.block_id))
                expired.append(record.block_id)
        return expired

    @staticmethod
    def _ttl(ttl_seconds: float) -> timedelta:
        if ttl_seconds <= 0:
            raise RuntimeFileValidationError(
                "field block TTL must be positive",
            )
        return timedelta(seconds=ttl_seconds)

    def acquire(
        self,
        *,
        project_id: str,
        json_pointer: str,
        owner_kind: str,
        owner_id: str,
        base_field_hash: str,
        ttl_seconds: float,
        block_id: str | None = None,
        token: str | None = None,
        current_field_hash: Callable[[], str] | None = None,
    ) -> FieldBlockRecord:
        parse_json_pointer(json_pointer)
        ttl = self._ttl(ttl_seconds)
        now = self.clock()
        block = FieldBlockRecord(
            block_id=block_id or f"block-{uuid4().hex}",
            project_id=project_id,
            json_pointer=json_pointer,
            owner_kind=owner_kind,
            owner_id=owner_id,
            token=token or secrets.token_urlsafe(32),
            base_field_hash=base_field_hash,
            acquired_at=now,
            expires_at=now + ttl,
        )
        with self._index_lock():
            self._cleanup_unlocked(now)
            if current_field_hash is not None:
                actual_hash = current_field_hash()
                if actual_hash != base_field_hash:
                    raise FieldBlockBaseConflictError(
                        expected=base_field_hash,
                        actual=actual_hash,
                    )
            for existing in self._records_unlocked():
                if existing.project_id == project_id and pointers_overlap(
                    existing.json_pointer,
                    json_pointer,
                ):
                    raise FieldBlockConflictError(existing)
            if self._store(block.block_id).try_create(block) is None:
                raise RecordAlreadyExistsError(self._path(block.block_id))
        return block

    @contextmanager
    def guard_write(
        self,
        *,
        project_id: str,
        json_pointers: list[str] | tuple[str, ...],
        token: str | None = None,
    ):
        """Hold the field index while admitting one short Project publish.

        This closes the race between a caller's preliminary block check and
        the actual atomic Project replacement.  It remains an ergonomic guard:
        field-value CAS is still the correctness authority.
        """

        pointers = tuple(json_pointers)
        for pointer in pointers:
            parse_json_pointer(pointer)
        with self._index_lock():
            self._cleanup_unlocked(self.clock())
            for existing in self._records_unlocked():
                if existing.project_id != project_id:
                    continue
                if token is not None and hmac.compare_digest(
                    existing.token,
                    token,
                ):
                    continue
                if any(
                    pointers_overlap(existing.json_pointer, pointer)
                    for pointer in pointers
                ):
                    raise FieldBlockConflictError(existing)
            yield

    def get(
        self,
        block_id: str,
        *,
        include_expired: bool = False,
    ) -> FieldBlockRecord | None:
        record = self._store(block_id).read_or_none()
        if record is None:
            return None
        if not include_expired and record.expires_at <= self.clock():
            return None
        return record

    @staticmethod
    def _check_token(record: FieldBlockRecord, token: str) -> None:
        if not hmac.compare_digest(record.token, token):
            raise FieldBlockTokenError(record.block_id)

    def renew(
        self,
        block_id: str,
        *,
        token: str,
        ttl_seconds: float,
    ) -> FieldBlockRecord:
        ttl = self._ttl(ttl_seconds)
        now = self.clock()
        with self._index_lock():
            record = self._store(block_id).read_or_none()
            if record is None:
                raise RecordNotFoundError(self._path(block_id))
            if record.expires_at <= now:
                durable_unlink(self._path(block_id))
                raise RecordNotFoundError(self._path(block_id))
            self._check_token(record, token)
            renewed = record.model_copy(update={"expires_at": now + ttl})
            return self._store(block_id).write(renewed).value

    def release(self, block_id: str, *, token: str) -> bool:
        now = self.clock()
        with self._index_lock():
            record = self._store(block_id).read_or_none()
            if record is None:
                return False
            if record.expires_at <= now:
                durable_unlink(self._path(block_id))
                return False
            self._check_token(record, token)
            return durable_unlink(self._path(block_id))

    def list_active(
        self,
        *,
        project_id: str | None = None,
    ) -> list[FieldBlockRecord]:
        now = self.clock()
        with self._index_lock():
            self._cleanup_unlocked(now)
            records = self._records_unlocked()
        if project_id is not None:
            records = [
                record for record in records if record.project_id == project_id
            ]
        return records

    def cleanup_expired(self) -> list[str]:
        with self._index_lock():
            return self._cleanup_unlocked(self.clock())
