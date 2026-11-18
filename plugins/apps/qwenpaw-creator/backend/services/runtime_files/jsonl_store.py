# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=consider-using-max-builtin,not-callable
"""Append-only JSONL streams with durable monotonic sequence numbers."""

from __future__ import annotations

from collections.abc import Callable
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

    def _tail_envelope_unlocked(
        self,
        *,
        repair: bool = True,
    ) -> JsonlEnvelope | None:
        line, terminated = self._read_tail_line_unlocked()
        if not terminated:
            if repair:
                envelopes, _removed = self._recover_unlocked()
            else:
                envelopes, _durable, _torn = self._scan_bytes(
                    self._read_bytes_unlocked(),
                )
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
            if repair:
                envelopes, _removed = self._recover_unlocked()
            else:
                envelopes, _durable, _torn = self._scan_bytes(
                    self._read_bytes_unlocked(),
                )
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
        # Lock-free: complete lines are never rewritten and a torn crash tail
        # is simply ignored here; the next locked append repairs it.
        envelopes, _durable, _torn = self._scan_bytes(
            self._read_bytes_unlocked(),
        )
        return envelopes

    def read_records(self) -> list[T]:
        return [
            self._validate_record(envelope.record, line_number=envelope.seq)
            for envelope in self.read_all()
        ]

    def read_record_at(self, seq: int) -> T | None:
        """Return the record whose line number is *seq*, or ``None``.

        Seqs are 1-based line numbers by construction -- one envelope per line,
        contiguity asserted on every read path -- so a targeted lookup can walk
        newline boundaries and parse exactly one line. This is what lets a
        caller fetch one historical record without materializing the stream:
        the full read dominated both CPU and the peak heap on long sessions
        (observed: 853 MB of Python heap for one 285 MB messages file).

        Lock-free like every other read path: complete lines are immutable, and
        an unrepaired crash tail reads as absent rather than being repaired here.
        """

        if seq < 1:
            raise ValueError("record seq must be positive")
        raw = b""
        line_number = 0
        try:
            handle = self.path.open("rb")
        except FileNotFoundError:
            # An absent stream is an empty stream, matching read_records().
            return None
        with handle:
            while line_number < seq:
                raw = handle.readline()
                if not raw or not raw.endswith(b"\n"):
                    return None
                line_number += 1
            try:
                envelope = JsonlEnvelope.model_validate(strict_json_loads(raw))
            except (
                UnicodeDecodeError,
                ValueError,
                PydanticValidationError,
            ) as error:
                raise JsonlCorruptionError(
                    self.path,
                    f"complete line {seq} is invalid: {error}",
                ) from error
            if envelope.seq != line_number:
                raise JsonlCorruptionError(
                    self.path,
                    f"line {line_number} has seq {envelope.seq}, "
                    f"expected {line_number}",
                )
            return cast(
                T,
                self._validate_record(
                    envelope.record,
                    line_number=line_number,
                ),
            )

    def forward_reader(
        self,
        after_seq: int = 0,
        *,
        skip_noise: Callable[[bytes], bool] | None = None,
        replay_boundary_seq: int | None = None,
    ) -> JsonlReadCursor[T]:
        """Create a bounded, sequential reader for one durable subscription.

        ``replay_boundary_seq`` bounds where ``skip_noise`` applies: lines
        at or past that seq are treated as live appends and go through
        the full parse path. Without it a long-lived SSE connection would
        drop every live streaming delta -- the filter would run for the
        whole connection lifetime, not just the replay it was designed
        to shorten (review #243 blocking #1).
        """
        return JsonlReadCursor(
            self,
            after_seq,
            skip_noise=skip_noise,
            replay_boundary_seq=replay_boundary_seq,
        )

    def read_records_after(
        self,
        after_seq: int,
        *,
        limit: int | None = None,
        where: Callable[[T], bool] | None = None,
    ) -> list[T]:
        """Return records with ``seq > after_seq`` without scanning the head.

        The stream is append-only with monotonic contiguous seqs, so a reader
        that only wants a tail window can read backwards from EOF instead of
        ``read_bytes``-ing and ``json.loads``-ing the whole file (which on long
        sessions dominates CPU).  Cost is proportional to the window size, not
        the stream length.  Reads are lock-free: complete lines are immutable
        and a torn (unterminated) crash tail is skipped, never returned; it is
        repaired by the next locked append.

        Seq contiguity is validated over the returned range.  ``limit`` caps
        the count from the tail.  ``where`` filters after that validation, so
        a filtered page cannot hide a gap in the durable stream.
        """
        if after_seq < 0:
            after_seq = 0
        if after_seq == 0 and limit is None and where is None:
            envelopes, _durable, _torn_tail = self._scan_bytes(
                self._read_bytes_unlocked(),
            )
            return [
                self._validate_record(e.record, line_number=e.seq)
                for e in envelopes
            ]
        envelopes = self._read_envelopes_after_unlocked(after_seq, None)
        records = [
            cast(T, self._validate_record(e.record, line_number=e.seq))
            for e in envelopes
        ]
        if where is not None:
            records = [record for record in records if where(record)]
        return records[:limit] if limit is not None else records

    def read_tail(
        self,
        limit: int,
        *,
        where: Callable[[T], bool] | None = None,
        max_scan: int | None = None,
    ) -> list[T]:
        """Return the last *limit* records, oldest-first, without a full scan.

        Paging backwards used to read the whole stream because the only
        available cursor stopped at a caller-supplied ``seq`` and a page open
        passed no lower bound at all. This walks backwards from EOF and stops
        as soon as the window is full, so opening a filtered page costs what it
        reads instead of the session's entire history.

        ``limit`` caps what is returned, which is not what caps the work: a
        ``where`` that matches rarely still walks back to the start of the
        stream. ``max_scan`` bounds the lines actually read so a caller that
        asks a tail question can afford to be told "not in the tail" and take
        an explicit fallback, instead of paying a full scan for a miss.

        Seq contiguity is checked over the scanned range *before* ``where``
        filters, so a gap inside the window is still reported; a gap older than
        the window is simply never read, which is the accepted trade of a
        bounded page. A malformed line falls back to the authoritative full
        scan so diagnostics stay exact rather than silently skipping history.
        """
        if limit < 1:
            raise ValueError("JSONL page limit must be positive")
        collected: list[T] = []
        expected: int | None = None
        scanned = 0
        for raw in self._iter_complete_lines_reverse():  # newest-first
            scanned += 1
            try:
                envelope = JsonlEnvelope.model_validate(
                    strict_json_loads(raw),
                )
                record = cast(
                    T,
                    self._validate_record(
                        envelope.record,
                        line_number=envelope.seq,
                    ),
                )
            except (
                UnicodeDecodeError,
                ValueError,
                PydanticValidationError,
                JsonlCorruptionError,
            ):
                return self._tail_fallback(limit, where)
            if expected is not None and envelope.seq != expected:
                return self._tail_fallback(limit, where)
            expected = envelope.seq - 1
            if where is None or where(record):
                collected.append(record)
                if len(collected) >= limit:
                    break
            if max_scan is not None and scanned >= max_scan:
                break
        collected.reverse()
        return collected

    def _tail_fallback(
        self,
        limit: int,
        where: Callable[[T], bool] | None,
    ) -> list[T]:
        envelopes, _durable, _torn = self._scan_bytes(
            self._read_bytes_unlocked(),
        )
        records = [
            cast(T, self._validate_record(e.record, line_number=e.seq))
            for e in envelopes
        ]
        if where is not None:
            records = [record for record in records if where(record)]
        return records[-limit:]

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

    def _line_seq(self, line: bytes) -> int | None:
        """The envelope seq of one complete line, None when unparseable."""

        try:
            return JsonlEnvelope.model_validate(strict_json_loads(line)).seq
        except (
            UnicodeDecodeError,
            ValueError,
            PydanticValidationError,
        ):
            return None

    def _scan_block_for_seq(
        self,
        parts: list[bytes],
        block_start: int,
        after_seq: int,
    ) -> tuple[int | None, bool]:
        """Locate ``after_seq`` inside one backwards block.

        Returns ``(offset, missing)``: the byte offset just past the cursor
        line when found, and ``missing=True`` when the walk already passed a
        smaller seq or met an unparseable line, meaning the cursor is not
        durable in this block and the caller must fall back.
        """

        # ``parts[0]`` starts at ``block_start``; later lines each start one
        # previous line further on.
        line_start = block_start + len(parts[0]) + 1
        offsets = []
        for part in parts[1:]:
            offsets.append(line_start)
            line_start += len(part) + 1
        for index in range(len(parts) - 1, 0, -1):
            line = parts[index]
            if not line:
                continue
            seq = self._line_seq(line)
            if seq is None or seq < after_seq:
                return None, True
            if seq == after_seq:
                return offsets[index - 1] + len(line) + 1, False
        return None, False

    def _offset_after_seq_unlocked(self, after_seq: int) -> int | None:
        """Byte offset just past the line carrying ``after_seq``, newest-first.

        A reconnecting SSE cursor used to start at byte zero and walk every
        line forward until ``after_seq``; on the field's 146 MB / 76k-event
        stream that paid a full scan on every reconnect.  Walking backwards
        and stopping at the cursor costs only the tail window it consumes.
        ``None`` means the seq is not durable here, and the caller then falls
        back to the authoritative forward walk instead of trusting a guessed
        offset.
        """

        try:
            size = self.path.stat().st_size
        except FileNotFoundError:
            return None
        if size == 0 or after_seq <= 0:
            return None
        chunk_size = 8192
        cursor = size
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
                    newline = block.rfind(b"\n")
                    if newline < 0:
                        pending = block
                        continue
                    block = block[:newline]
                    torn_tail = False
                parts = block.split(b"\n")
                found, missing = self._scan_block_for_seq(
                    parts,
                    cursor,
                    after_seq,
                )
                if missing or found is not None:
                    return found
                if parts[0]:
                    pending = parts[0]
        if pending and not torn_tail and self._line_seq(pending) == after_seq:
            return len(pending) + 1
        return None

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
                # authoritative full scan for exact diagnostics.  Torn-tail
                # repair is a write and belongs to the next locked append.
                envelopes_all, _durable, _torn = self._scan_bytes(
                    self._read_bytes_unlocked(),
                )
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
                envelopes_all, _durable, _torn = self._scan_bytes(
                    self._read_bytes_unlocked(),
                )
                tail = [e for e in envelopes_all if e.seq > after_seq]
                if limit is not None:
                    tail = tail[:limit]
                return tail
            expected += 1
        if limit is not None:
            return collected[:limit]
        return collected

    def last_seq(self) -> int:
        # Lock-free: the durable tail envelope carries the last contiguous
        # seq; reading it backwards is O(1) instead of scanning the whole
        # stream.  A torn crash tail is ignored (never repaired here); the
        # next locked append repairs it, so the returned seq stays
        # authoritative.
        tail = self._tail_envelope_unlocked(repair=False)
        return tail.seq if tail is not None else 0


_SEQ_MARKER = b'"seq":'


def _seq_of_line(raw: bytes) -> int | None:
    """Read one line's envelope seq off the bytes, without parsing it.

    The top-level ``seq`` is written last and is the only place the quoted
    marker appears -- ``event_seq`` inside ``record`` carries a different key --
    so a reverse search plus a digit run proves contiguity for a line we intend
    to drop. ``None`` means "not cheaply determinable" and the caller parses.
    """

    marker = raw.rfind(_SEQ_MARKER)
    if marker < 0:
        return None
    start = marker + len(_SEQ_MARKER)
    end = start
    while end < len(raw) and 48 <= raw[end] <= 57:
        end += 1
    if end == start:
        return None
    return int(raw[start:end])


class JsonlReadCursor(Generic[T]):
    """Follow complete lines once, retaining an offset instead of the history.

    Fresh subscriptions must replay old events to reconstruct detached work.
    Repeating a reverse tail scan for every page makes that replay quadratic.
    This per-subscription cursor validates each line once and keeps at most one
    requested page in memory. It reopens the file for each read, so disconnects
    and cancelled worker calls cannot leak a retained file descriptor.

    ``skip_noise`` may classify a raw line before it is parsed. A replay that
    intends to drop a line still has to prove the stream is contiguous there,
    so the seq is read straight off the bytes; anything that cannot be confirmed
    cheaply falls back to the full parse, which keeps the corruption diagnostics
    exactly as strict as they were.
    """

    # pylint: disable=too-few-public-methods,protected-access
    def __init__(
        self,
        store: DurableJsonlStore[T],
        after_seq: int,
        *,
        skip_noise: Callable[[bytes], bool] | None = None,
        replay_boundary_seq: int | None = None,
    ) -> None:
        self.store = store
        self.after_seq = max(0, after_seq)
        self.skip_noise = skip_noise
        # A None boundary means the caller wants the filter to apply for
        # the whole reader lifetime, which is what a bounded replay (a
        # single page pull) wants. SSE subscriptions pass the tail seq so
        # live appends past that point fall through to the parse path
        # instead of being dropped as replay noise.
        self.replay_boundary_seq = replay_boundary_seq
        self.offset = 0
        self.seq = 0
        self.identity: tuple[int, int] | None = None
        if self.after_seq:
            # Position at the cursor instead of walking the whole stream on
            # the first read. A miss keeps offset zero: correctness first.
            positioned = store._offset_after_seq_unlocked(self.after_seq)
            if positioned is not None:
                self.offset = positioned
                self.seq = self.after_seq

    def read(self, limit: int = 200) -> list[T]:
        """Read the next bounded page, or [] at a possibly incomplete tail."""
        if limit < 1:
            raise ValueError("JSONL page limit must be positive")
        try:
            handle = self.store.path.open("rb")
        except FileNotFoundError:
            if self.identity is not None:
                raise JsonlCorruptionError(
                    self.store.path,
                    "durable stream disappeared during replay",
                ) from None
            return []
        records: list[T] = []
        with handle:
            stat = os.fstat(handle.fileno())
            identity = (stat.st_dev, stat.st_ino)
            if (
                self.identity is not None and self.identity != identity
            ) or stat.st_size < self.offset:
                raise JsonlCorruptionError(
                    self.store.path,
                    "durable stream was replaced or truncated during replay",
                )
            self.identity = identity
            handle.seek(self.offset)
            while len(records) < limit:
                raw = handle.readline()
                if not raw or not raw.endswith(b"\n"):
                    # Do not advance past a concurrent write or crash fragment.
                    # The next append may complete or repair this same offset.
                    break
                if (
                    self.skip_noise is not None
                    and (
                        self.replay_boundary_seq is None
                        or self.seq < self.replay_boundary_seq
                    )
                    and self.skip_noise(raw)
                ):
                    cheap = _seq_of_line(raw)
                    if cheap == self.seq + 1:
                        # Contiguity proven without parsing: the line is
                        # dropped, the cursor still moves past it.
                        self.offset = handle.tell()
                        self.seq = cheap
                        continue
                try:
                    envelope = JsonlEnvelope.model_validate(
                        strict_json_loads(raw),
                    )
                except (
                    UnicodeDecodeError,
                    ValueError,
                    PydanticValidationError,
                ) as error:
                    raise JsonlCorruptionError(
                        self.store.path,
                        f"complete line {self.seq + 1} is invalid: {error}",
                    ) from error
                if envelope.seq != self.seq + 1:
                    raise JsonlCorruptionError(
                        self.store.path,
                        f"line {self.seq + 1} has seq {envelope.seq}, "
                        f"expected {self.seq + 1}",
                    )
                record = self.store._validate_record(
                    envelope.record,
                    line_number=envelope.seq,
                )
                self.offset = handle.tell()
                self.seq = envelope.seq
                if self.seq > self.after_seq:
                    records.append(record)
        return records
