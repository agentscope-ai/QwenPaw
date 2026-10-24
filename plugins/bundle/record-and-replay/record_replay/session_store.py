# -*- coding: utf-8 -*-
"""Crash-aware plugin store for desktop recording sessions."""

from __future__ import annotations

import os
import stat
import threading
from collections.abc import Iterable
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from .errors import RecordingStateError, RecordingStoreError
from .models import (
    RecordingEvent,
    RecordingSession,
    RecordingState,
    RecordingSummary,
    utc_now,
)
from qwenpaw.utils.io_utils import read_json, write_json_atomic

_ACTIVE_STATES = frozenset(
    {
        RecordingState.STARTING,
        RecordingState.RECORDING,
        RecordingState.PAUSED,
        RecordingState.FINALIZING,
    },
)
_APPEND_STATES = frozenset(
    {RecordingState.RECORDING, RecordingState.PAUSED},
)
_TRANSITIONS: dict[RecordingState, set[RecordingState]] = {
    RecordingState.STARTING: {
        RecordingState.RECORDING,
        RecordingState.FAILED,
        RecordingState.INTERRUPTED,
    },
    RecordingState.RECORDING: {
        RecordingState.PAUSED,
        RecordingState.FINALIZING,
        RecordingState.FAILED,
        RecordingState.INTERRUPTED,
    },
    RecordingState.PAUSED: {
        RecordingState.RECORDING,
        RecordingState.FINALIZING,
        RecordingState.FAILED,
        RecordingState.INTERRUPTED,
    },
    RecordingState.FINALIZING: {
        RecordingState.COMPLETED,
        RecordingState.FAILED,
        RecordingState.INTERRUPTED,
    },
    RecordingState.COMPLETED: {RecordingState.DELETED},
    RecordingState.INTERRUPTED: {RecordingState.DELETED},
    RecordingState.FAILED: {RecordingState.DELETED},
    RecordingState.DELETED: set(),
}


class RecordingStore:
    """Persist recordings below one workspace without exposing file paths."""

    def __init__(self, workspace_dir: str | Path) -> None:
        root = Path(workspace_dir).expanduser().resolve()
        self._workspace_dir = root
        self._root = root / "recordings"
        self._lock = threading.RLock()

    @property
    def workspace_dir(self) -> Path:
        """Return the resolved workspace root owned by this store."""
        return self._workspace_dir

    def create(
        self,
        *,
        workspace_id: str,
        user_id: str,
        agent_id: str,
    ) -> RecordingSession:
        """Create a private ``starting`` session and its fixed layout."""
        with self._lock:
            self._ensure_root()
            recording_id = uuid4()
            directory = self._root / str(recording_id)
            directory.mkdir(mode=0o700)
            now = utc_now()
            session = RecordingSession(
                recording_id=recording_id,
                workspace_id=workspace_id,
                user_id=user_id,
                agent_id=agent_id,
                state=RecordingState.STARTING,
                created_at=now,
                updated_at=now,
            )
            self._write_session(session)
            self._touch_private(directory / "events.jsonl")
            return session

    def get(self, recording_id: str | UUID) -> RecordingSession:
        """Load one session by opaque recording id."""
        with self._lock:
            return self._read_session(recording_id)

    def transition(
        self,
        recording_id: str | UUID,
        state: RecordingState,
        *,
        failure_code: str | None = None,
    ) -> RecordingSession:
        """Apply one validated durable state transition."""
        with self._lock:
            session = self._read_session(recording_id)
            if state not in _TRANSITIONS[session.state]:
                raise RecordingStateError(
                    f"invalid transition {session.state} -> {state}",
                )
            update: dict[str, Any] = {
                "state": state,
                "updated_at": utc_now(),
            }
            if failure_code is not None:
                update["failure_code"] = failure_code
            if state in {
                RecordingState.COMPLETED,
                RecordingState.FAILED,
                RecordingState.INTERRUPTED,
            }:
                update["completed_at"] = update["updated_at"]
            session = session.model_copy(update=update)
            self._write_session(session)
            return session

    def append_events(
        self,
        recording_id: str | UUID,
        events: Iterable[RecordingEvent],
    ) -> RecordingSession:
        """Durably append a strictly ordered event batch."""
        batch = list(events)
        if not batch:
            return self.get(recording_id)
        with self._lock:
            session = self._read_session(recording_id)
            if session.state not in _APPEND_STATES:
                raise RecordingStateError(
                    f"cannot append events while {session.state}",
                )
            previous = session.last_seq
            for event in batch:
                if previous is not None and event.seq <= previous:
                    raise RecordingStoreError(
                        "event sequence is not increasing",
                    )
                previous = event.seq

            path = self._recording_dir(recording_id) / "events.jsonl"
            self._append_json_lines(path, batch)
            session = session.model_copy(
                update={
                    "event_count": session.event_count + len(batch),
                    "last_seq": batch[-1].seq,
                    "updated_at": utc_now(),
                },
            )
            self._write_session(session)
            return session

    def add_dropped_events(
        self,
        recording_id: str | UUID,
        count: int,
    ) -> RecordingSession:
        """Persist an explicit native drop count."""
        if count <= 0:
            raise RecordingStoreError("dropped event count must be positive")
        with self._lock:
            session = self._read_session(recording_id)
            if session.state not in _APPEND_STATES:
                raise RecordingStateError(
                    f"cannot report drops while {session.state}",
                )
            session = session.model_copy(
                update={
                    "dropped_event_count": (
                        session.dropped_event_count + count
                    ),
                    "updated_at": utc_now(),
                },
            )
            self._write_session(session)
            return session

    def import_events_atomic(
        self,
        recording_id: str | UUID,
        events: Iterable[RecordingEvent],
        *,
        dropped_event_count: int,
    ) -> RecordingSession:
        """Replace an empty live event file from a verified stream.

        EventStream artifacts are verified before this method is entered. The
        iterable is nevertheless allowed to fail during its second, import
        pass; in that case only the private temporary file is removed and the
        recording never exposes a partial imported JSONL.
        """
        if dropped_event_count < 0:
            raise RecordingStoreError(
                "dropped event count must be nonnegative",
            )
        with self._lock:
            session = self._read_session(recording_id)
            if session.state not in _APPEND_STATES:
                raise RecordingStateError(
                    f"cannot import events while {session.state}",
                )
            destination = self._recording_dir(recording_id) / "events.jsonl"
            try:
                if destination.stat().st_size != 0 or session.event_count != 0:
                    raise RecordingStoreError(
                        "recording already contains imported events",
                    )
            except OSError as exc:
                raise RecordingStoreError(
                    "unable to inspect recording events",
                ) from exc

            temporary = destination.with_name(
                f".events.import-{uuid4().hex}.jsonl",
            )
            count = 0
            last_seq: int | None = None
            try:
                flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
                if hasattr(os, "O_NOFOLLOW"):
                    flags |= os.O_NOFOLLOW
                fd = os.open(temporary, flags, 0o600)
                with os.fdopen(
                    fd,
                    "w",
                    encoding="utf-8",
                    newline="\n",
                ) as handle:
                    for event in events:
                        if last_seq is not None and event.seq <= last_seq:
                            raise RecordingStoreError(
                                "event sequence is not increasing",
                            )
                        handle.write(event.model_dump_json())
                        handle.write("\n")
                        count += 1
                        last_seq = event.seq
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, destination)
            except BaseException:
                temporary.unlink(missing_ok=True)
                raise

            session = session.model_copy(
                update={
                    "event_count": count,
                    "dropped_event_count": dropped_event_count,
                    "last_seq": last_seq,
                    "updated_at": utc_now(),
                },
            )
            self._write_session(session)
            return session

    def complete(self, recording_id: str | UUID) -> RecordingSession:
        """Finalize a session and publish its small summary atomically."""
        with self._lock:
            session = self._read_session(recording_id)
            if session.state is not RecordingState.FINALIZING:
                raise RecordingStateError("recording is not finalizing")
            completed = self.transition(
                recording_id,
                RecordingState.COMPLETED,
            )
            self._write_summary(completed)
            return completed

    def recover_unfinished(self) -> list[RecordingSession]:
        """Mark crash-left active sessions ``interrupted`` on startup."""
        recovered: list[RecordingSession] = []
        with self._lock:
            if not self._root.exists():
                return recovered
            for entry in self._root.iterdir():
                if not entry.is_dir() or entry.is_symlink():
                    continue
                try:
                    UUID(entry.name)
                    session = self._read_session(entry.name)
                except (ValueError, RecordingStoreError):
                    continue
                if session.state in _ACTIVE_STATES:
                    session = self._repair_counts(session)
                    interrupted = self.transition(
                        session.recording_id,
                        RecordingState.INTERRUPTED,
                        failure_code="process_interrupted",
                    )
                    self._write_summary(interrupted)
                    recovered.append(interrupted)
                elif (
                    session.state is RecordingState.COMPLETED
                    and not (entry / "summary.json").is_file()
                ):
                    self._write_summary(session)
        return recovered

    def read_events(
        self,
        recording_id: str | UUID,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> list[RecordingEvent]:
        """Read a bounded page without exposing the underlying path."""
        if offset < 0 or not 1 <= limit <= 1000:
            raise RecordingStoreError("invalid event page")
        with self._lock:
            path = self._recording_dir(recording_id) / "events.jsonl"
            events: list[RecordingEvent] = []
            try:
                with path.open("r", encoding="utf-8") as handle:
                    for index, line in enumerate(handle):
                        if index < offset:
                            continue
                        if len(events) >= limit:
                            break
                        events.append(RecordingEvent.model_validate_json(line))
            except (OSError, ValueError) as exc:
                raise RecordingStoreError(
                    "unable to read recording events",
                ) from exc
            return events

    def _ensure_root(self) -> None:
        self._workspace_dir.mkdir(parents=True, exist_ok=True)
        self._root.mkdir(mode=0o700, exist_ok=True)
        if self._root.is_symlink() or not self._root.is_dir():
            raise RecordingStoreError("unsafe recordings directory")
        try:
            self._root.chmod(0o700)
        except OSError as exc:
            raise RecordingStoreError(
                "unable to secure recordings directory",
            ) from exc

    def _recording_dir(self, recording_id: str | UUID) -> Path:
        try:
            normalized = str(UUID(str(recording_id)))
        except ValueError as exc:
            raise RecordingStoreError("invalid recording id") from exc
        directory = self._root / normalized
        if directory.is_symlink():
            raise RecordingStoreError("unsafe recording directory")
        resolved = directory.resolve(strict=False)
        if resolved.parent != self._root.resolve(strict=False):
            raise RecordingStoreError("recording escaped workspace")
        return directory

    def _read_session(self, recording_id: str | UUID) -> RecordingSession:
        path = self._recording_dir(recording_id) / "session.json"
        try:
            return RecordingSession.model_validate(read_json(path))
        except (OSError, ValueError) as exc:
            raise RecordingStoreError(
                "unable to load recording session",
            ) from exc

    def _write_session(self, session: RecordingSession) -> None:
        path = self._recording_dir(session.recording_id) / "session.json"
        write_json_atomic(
            path,
            session.model_dump(mode="json"),
            sort_keys=True,
        )

    @staticmethod
    def _touch_private(path: Path) -> None:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            fd = os.open(path, flags, 0o600)
        except OSError as exc:
            raise RecordingStoreError("unable to create events file") from exc
        os.close(fd)

    @staticmethod
    def _append_json_lines(
        path: Path,
        events: list[RecordingEvent],
    ) -> None:
        flags = os.O_WRONLY | os.O_APPEND
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            path_stat = os.lstat(path)
            if not stat.S_ISREG(path_stat.st_mode):
                raise RecordingStoreError("unsafe events file")
            fd = os.open(path, flags)
            with os.fdopen(fd, "a", encoding="utf-8", newline="\n") as handle:
                for event in events:
                    handle.write(event.model_dump_json())
                    handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as exc:
            raise RecordingStoreError(
                "unable to append recording events",
            ) from exc

    def _first_seq(self, recording_id: str | UUID) -> int | None:
        page = self.read_events(recording_id, offset=0, limit=1)
        if not page:
            return None
        source_first = page[0].source.get("raw_first_seq")
        return source_first if isinstance(source_first, int) else page[0].seq

    def _write_summary(self, session: RecordingSession) -> None:
        summary = RecordingSummary(
            recording_id=session.recording_id,
            state=session.state,
            event_count=session.event_count,
            dropped_event_count=session.dropped_event_count,
            first_seq=self._first_seq(session.recording_id),
            last_seq=session.last_seq,
        )
        write_json_atomic(
            self._recording_dir(session.recording_id) / "summary.json",
            summary.model_dump(mode="json"),
            sort_keys=True,
        )

    def _repair_counts(self, session: RecordingSession) -> RecordingSession:
        path = self._recording_dir(session.recording_id) / "events.jsonl"
        count = 0
        last_seq: int | None = None
        try:
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    event = RecordingEvent.model_validate_json(line)
                    count += 1
                    last_seq = event.seq
        except (OSError, ValueError) as exc:
            raise RecordingStoreError("unable to repair recording") from exc
        if count == session.event_count and last_seq == session.last_seq:
            return session
        repaired = session.model_copy(
            update={
                "event_count": count,
                "last_seq": last_seq,
                "updated_at": utc_now(),
            },
        )
        self._write_session(repaired)
        return repaired


__all__ = ["RecordingStore"]
