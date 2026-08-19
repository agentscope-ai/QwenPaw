# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=consider-using-max-builtin,not-callable
"""Append-only JSONL streams with durable monotonic sequence numbers."""

from __future__ import annotations

from datetime import datetime
import json
import logging
import os
from pathlib import Path
from typing import Any, Generic, Iterator, TypeVar, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError as PydanticValidationError,
)

from .atomic_store import (
    chmod_descriptor_if_supported,
    canonical_json_bytes,
    fsync_directory,
    strict_json_loads,
)
from .errors import (
    JsonlCorruptionError,
    RuntimeFileValidationError,
    SequenceConflictError,
)
from .locking import CrossProcessFileLock
from .models import AwareDatetime, utc_now

logger = logging.getLogger("qwenpaw.creator.runtime_files.jsonl_store")


T = TypeVar("T")


class JsonlEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seq: int = Field(ge=1)
    written_at: AwareDatetime
    record: Any


class DurableJsonlStore(Generic[T]):
    """A recoverable JSONL stream whose complete lines are never rewritten.

    Every append holds a sibling advisory lock, validates/reconciles the final
    line, allocates the next contiguous sequence, appends one UTF-8 line and
    fsyncs it before returning.  A crash during the write may leave only an
    unterminated final fragment; the next locked append truncates that
    fragment. A malformed *complete* line is corruption and is never skipped.
    """

    def __init__(
        self,
        path: str | os.PathLike[str],
        model_type: type[T] | None = None,
        *,
        lock_path: str | os.PathLike[str] | None = None,
        lock_timeout_seconds: float | None = 10.0,
        mode: int = 0o600,
    ) -> None:
        self.path = Path(path)
        self.model_type = model_type
        self.lock_path = (
            Path(lock_path)
            if lock_path is not None
            else self.path.with_name(f".{self.path.name}.lock")
        )
        self.lock_timeout_seconds = lock_timeout_seconds
        self.mode = mode

    def _lock(self) -> CrossProcessFileLock:
        return CrossProcessFileLock(
            self.lock_path,
            timeout_seconds=self.lock_timeout_seconds,
        )

    def _validate_record(
        self,
        record: Any,
        *,
        line_number: int | None = None,
    ) -> T:
        try:
            if self.model_type is None:
                # Canonicalization both validates and detaches the JSON value.
                return cast(T, json.loads(canonical_json_bytes(record)))
            validator = getattr(self.model_type, "model_validate", None)
            if validator is None:
                raise RuntimeFileValidationError(
                    "model_type must provide model_validate(): "
                    f"{self.model_type!r}",
                )
            return cast(T, validator(record))
        except (PydanticValidationError, RuntimeFileValidationError) as exc:
            if line_number is not None:
                raise JsonlCorruptionError(
                    self.path,
                    f"line {line_number} record validation failed: {exc}",
                ) from exc
            raise RuntimeFileValidationError(
                f"JSONL record validation failed: {exc}",
            ) from exc

    @staticmethod
    def _dump_record(record: T) -> Any:
        if isinstance(record, BaseModel):
            return record.model_dump(mode="json", by_alias=True)
        return json.loads(canonical_json_bytes(record))

    def _scan_bytes(
        self,
        payload: bytes,
    ) -> tuple[list[JsonlEnvelope], int, bool]:
        """Return envelopes, durable byte length and torn-tail flag."""

        envelopes: list[JsonlEnvelope] = []
        durable_length = 0
        lines = payload.splitlines(keepends=True)
        for index, line in enumerate(lines, start=1):
            if not line.endswith(b"\n"):
                if index != len(
                    lines,
                ):  # pragma: no cover - splitlines contract
                    raise JsonlCorruptionError(
                        self.path,
                        f"unterminated non-final line {index}",
                    )
                return envelopes, durable_length, True
            try:
                decoded = strict_json_loads(line)
                envelope = JsonlEnvelope.model_validate(decoded)
            except (
                UnicodeDecodeError,
                ValueError,
                PydanticValidationError,
            ) as exc:
                logger.error(
                    "jsonl corruption: %s line %d: %s",
                    self.path,
                    index,
                    exc,
                )
                raise JsonlCorruptionError(
                    self.path,
                    f"complete line {index} is invalid: {exc}",
                ) from exc
            expected_seq = len(envelopes) + 1
            if envelope.seq != expected_seq:
                logger.error(
                    "jsonl sequence gap: %s line %d seq=%d expected=%d",
                    self.path,
                    index,
                    envelope.seq,
                    expected_seq,
                )
                raise JsonlCorruptionError(
                    self.path,
                    f"line {index} has seq {envelope.seq}, "
                    f"expected {expected_seq}",
                )
            self._validate_record(envelope.record, line_number=index)
            envelopes.append(envelope)
            durable_length += len(line)
        return envelopes, durable_length, False

    def _read_bytes_unlocked(self) -> bytes:
        try:
            return self.path.read_bytes()
        except FileNotFoundError:
            return b""

    def _read_tail_line_unlocked(self) -> tuple[bytes | None, bool]:
        """Return the last complete line and whether the file is terminated.

        Normal appends only need the durable tail sequence. Reading backwards
        avoids rescanning an ever-growing stream for every provider token. An
        unterminated tail is reported separately so the existing full recovery
        path can validate and truncate it before the next append.
        """

        try:
            handle = self.path.open("rb")
        except FileNotFoundError:
            return None, True
        with handle:
            handle.seek(0, os.SEEK_END)
            end = handle.tell()
            if end == 0:
                return None, True
            handle.seek(end - 1)
            if handle.read(1) != b"\n":
                return None, False

            cursor = end - 1
            chunks: list[bytes] = []
            while cursor > 0:
                start = max(0, cursor - 8192)
                handle.seek(start)
                chunk = handle.read(cursor - start)
                boundary = chunk.rfind(b"\n")
                if boundary >= 0:
                    chunks.append(chunk[boundary + 1 :])
                    break
                chunks.append(chunk)
                cursor = start
            return b"".join(reversed(chunks)), True

    def _tail_envelope_unlocked(self) -> JsonlEnvelope | None:
        line, terminated = self._read_tail_line_unlocked()
        if not terminated:
            envelopes, _removed = self._recover_unlocked()
            return envelopes[-1] if envelopes else None
        if line is None:
            return None
        try:
            envelope = JsonlEnvelope.model_validate(strict_json_loads(line))
            self._validate_record(envelope.record, line_number=envelope.seq)
            return envelope
        except (
            UnicodeDecodeError,
            ValueError,
            PydanticValidationError,
            JsonlCorruptionError,
        ):
            # Preserve the precise full-stream corruption diagnostics for a
            # malformed complete tail. The normal valid-tail path stays O(1).
            envelopes, _removed = self._recover_unlocked()
            return envelopes[-1] if envelopes else None

    def _recover_unlocked(self) -> tuple[list[JsonlEnvelope], int]:
        payload = self._read_bytes_unlocked()
        envelopes, durable_length, torn_tail = self._scan_bytes(payload)
        if not torn_tail:
            return envelopes, 0
        removed = len(payload) - durable_length
        with self.path.open("r+b") as handle:
            handle.truncate(durable_length)
            handle.flush()
            os.fsync(handle.fileno())
        return envelopes, removed

    def recover(self) -> int:
        """Remove an unterminated crash tail and return removed byte count."""

        with self._lock():
            _envelopes, removed = self._recover_unlocked()
        return removed

    def append(
        self,
        record: Any,
        *,
        expected_next_seq: int | None = None,
        written_at: datetime | None = None,
    ) -> JsonlEnvelope:
        validated = self._validate_record(record)
        dumped = self._dump_record(validated)
        timestamp = written_at or utc_now()
        with self._lock():
            tail = self._tail_envelope_unlocked()
            next_seq = (tail.seq if tail is not None else 0) + 1
            if expected_next_seq is not None and expected_next_seq != next_seq:
                raise SequenceConflictError(
                    expected=expected_next_seq,
                    actual=next_seq,
                )
            envelope = JsonlEnvelope(
                seq=next_seq,
                written_at=timestamp,
                record=dumped,
            )
            line = canonical_json_bytes(envelope) + b"\n"
            self.path.parent.mkdir(parents=True, exist_ok=True)
            existed = self.path.exists()
            flags = os.O_CREAT | os.O_WRONLY | os.O_APPEND
            if hasattr(os, "O_CLOEXEC"):
                flags |= os.O_CLOEXEC
            descriptor = os.open(self.path, flags, self.mode)
            try:
                chmod_descriptor_if_supported(descriptor, self.mode)
                view = memoryview(line)
                while view:
                    written = os.write(descriptor, view)
                    if (
                        written <= 0
                    ):  # pragma: no cover - defensive POSIX guard
                        raise OSError(
                            "zero-byte write while appending Runtime JSONL",
                        )
                    view = view[written:]
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            if not existed:
                fsync_directory(self.path.parent)
            logger.debug(
                "jsonl append: %s seq=%d",
                self.path,
                next_seq,
            )
            return envelope

    def read_all(self) -> list[JsonlEnvelope]:
        with self._lock():
            envelopes, _removed = self._recover_unlocked()
        return envelopes

    def read_records(self) -> list[T]:
        return [
            self._validate_record(envelope.record, line_number=envelope.seq)
            for envelope in self.read_all()
        ]

    def read_records_after(
        self,
        after_seq: int,
        *,
        limit: int | None = None,
    ) -> list[T]:
        """Return records with ``seq > after_seq`` without scanning the head.

        The stream is append-only with monotonic contiguous seqs, so a reader
        that only wants a tail window can read backwards from EOF instead of
        ``read_bytes``-ing and ``json.loads``-ing the whole file (which on long
        sessions dominates CPU and holds the lock for hundreds of ms).  Cost is
        proportional to the window size, not the stream length.

        Seq contiguity is validated over the returned range.  A torn
        (unterminated) crash tail is skipped, never returned; it is repaired by
        the next locked append.  ``limit`` caps the count from the tail.
        """
        if after_seq < 0:
            after_seq = 0
        with self._read_lock():
            if after_seq == 0 and limit is None:
                # Full read under the shared lock.  Scan only (no torn-tail
                # repair: that is a write and belongs to the next append).
                envelopes, _durable, _torn_tail = self._scan_bytes(
                    self._read_bytes_unlocked(),
                )
                return [
                    self._validate_record(e.record, line_number=e.seq)
                    for e in envelopes
                ]
            envelopes = self._read_envelopes_after_unlocked(after_seq, limit)
        return [
            self._validate_record(e.record, line_number=e.seq)
            for e in envelopes
        ]

    def _read_lock(self) -> CrossProcessFileLock:
        return CrossProcessFileLock(
            self.lock_path,
            timeout_seconds=self.lock_timeout_seconds,
            shared=True,
        )

    def _iter_complete_lines_reverse(self) -> Iterator[bytes]:
        """Yield complete lines newest-first, dropping any trailing torn fragment.

        Opens the file once and reads 8 KiB blocks backward from EOF, yielding
        each complete line as soon as it is assembled.  A trailing fragment
        with no terminating ``\\n`` (a crash tail) is silently dropped.  Because
        lines are yielded lazily, a caller that stops at a cursor ``seq`` only
        reads the tail window it actually consumes instead of the whole stream.
        """

        try:
            size = self.path.stat().st_size
        except FileNotFoundError:
            return
        if size == 0:
            return
        chunk_size = 8192
        cursor = size
        # ``pending`` holds bytes from the start of the current block that
        # belong to a line continuing into the next (earlier) block; carry it
        # backward.  ``torn_tail`` is True until the first newline is found,
        # meaning everything after it is the crash fragment to drop.
        pending = b""
        torn_tail = True
        with self.path.open("rb") as handle:
            while cursor > 0:
                start = max(0, cursor - chunk_size)
                handle.seek(start)
                block = handle.read(cursor - start) + pending
                cursor = start
                pending = b""
                if torn_tail:
                    nl = block.rfind(b"\n")
                    if nl < 0:
                        # No newline in this block; the whole thing is part of
                        # the torn tail (possibly spanning earlier blocks).
                        # Keep reading back, carrying it as pending.
                        pending = block
                        continue
                    block = block[:nl]  # drop everything after the last \n
                    torn_tail = False
                # ``block`` now ends at a \n boundary; split into complete lines.
                parts = block.split(b"\n")
                # parts[0] may be a partial line continuing into the previous
                # block; parts[1:] are complete, newest-first in reverse.
                for line in reversed(parts[1:]):
                    if line:
                        yield line
                if parts[0]:
                    pending = parts[0]
        if pending and not torn_tail:
            # The file's first line, complete (begins at offset 0).
            yield pending

    def _read_envelopes_after_unlocked(
        self,
        after_seq: int,
        limit: int | None,
    ) -> list[JsonlEnvelope]:
        collected: list[JsonlEnvelope] = []
        for raw in self._iter_complete_lines_reverse():  # newest-first
            try:
                envelope = JsonlEnvelope.model_validate(strict_json_loads(raw))
                self._validate_record(
                    envelope.record,
                    line_number=envelope.seq,
                )
            except (
                UnicodeDecodeError,
                ValueError,
                PydanticValidationError,
                JsonlCorruptionError,
            ):
                # Malformed line in the durable range: fall back to the
                # authoritative full scan for exact diagnostics + torn repair.
                envelopes_all, _removed = self._recover_unlocked()
                tail = [e for e in envelopes_all if e.seq > after_seq]
                if limit is not None:
                    tail = tail[:limit]
                return tail
            if envelope.seq <= after_seq:
                # Reached the cursor: older lines are outside the window.
                # Because ``_iter_complete_lines_reverse`` is lazy, this break
                # also stops reading earlier blocks instead of scanning the
                # whole file.
                break
            collected.append(envelope)
        collected.reverse()  # oldest-first
        expected = after_seq + 1
        for env in collected:
            if env.seq != expected:
                envelopes_all, _removed = self._recover_unlocked()
                tail = [e for e in envelopes_all if e.seq > after_seq]
                if limit is not None:
                    tail = tail[:limit]
                return tail
            expected += 1
        if limit is not None:
            return collected[:limit]
        return collected

    def last_seq(self) -> int:
        # The durable tail envelope carries the last contiguous seq; reading it
        # backwards is O(1) instead of scanning the whole stream.  A torn crash
        # tail is repaired by ``_tail_envelope_unlocked`` exactly as a full
        # ``read_all`` would, so the returned seq stays authoritative.
        with self._lock():
            tail = self._tail_envelope_unlocked()
        return tail.seq if tail is not None else 0
