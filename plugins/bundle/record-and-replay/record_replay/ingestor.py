# -*- coding: utf-8 -*-
"""Secure plugin import for sealed EventStream artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from .errors import RecordingProtocolError, RecordingStoreError
from .models import RecordingEvent, RecordingSession
from .normalization import RecordingActionNormalizer
from .redaction import RecordingRedactor
from .session_store import RecordingStore

_MAX_EVENTS_BYTES = 512 * 1024 * 1024
_MAX_METADATA_BYTES = 64 * 1024
_MAX_LINE_BYTES = 1024 * 1024
_ARTIFACT_SCHEMA_VERSION = 1


# pylint: disable=too-many-instance-attributes
@dataclass(frozen=True)
class EventStreamArtifact:
    """Sealed references returned by EventStream stop."""

    root: Path
    recording_id: UUID
    events_ref: str
    metadata_ref: str
    event_count: int
    dropped_event_count: int
    last_seq: int
    sha256: str

    @classmethod
    def from_stop_result(
        cls,
        root: Path,
        result: Mapping[str, Any],
    ) -> "EventStreamArtifact":
        """Validate the low-level stop response and bind its trusted root."""
        try:
            recording_id = UUID(str(result["recording_id"]))
            event_count = _nonnegative_int(result["event_count"])
            dropped = _nonnegative_int(result["dropped_event_count"])
            last_seq = int(result["last_seq"])
            events_ref = str(result["events_ref"])
            metadata_ref = str(result["metadata_ref"])
            digest = str(result["sha256"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RecordingProtocolError(
                "invalid EventStream stop result",
            ) from exc
        try:
            digest_bytes = bytes.fromhex(digest)
        except ValueError as exc:
            raise RecordingProtocolError(
                "invalid EventStream artifact digest",
            ) from exc
        if last_seq < -1 or len(digest_bytes) != 32:
            raise RecordingProtocolError(
                "invalid EventStream artifact summary",
            )
        _validate_ref(events_ref, recording_id, "events.jsonl")
        _validate_ref(metadata_ref, recording_id, "metadata.json")
        if not root.is_absolute() or ".." in root.parts:
            raise RecordingProtocolError("invalid EventStream artifact root")
        return cls(
            root=root,
            recording_id=recording_id,
            events_ref=events_ref,
            metadata_ref=metadata_ref,
            event_count=event_count,
            dropped_event_count=dropped,
            last_seq=last_seq,
            sha256=digest,
        )


# pylint: enable=too-many-instance-attributes


@dataclass(frozen=True)
class _ValidatedArtifact:
    event_count: int
    dropped_event_count: int
    last_seq: int
    sha256: str


class RecordingIngestor:  # pylint: disable=too-few-public-methods
    """Validate, redact, normalize, and atomically import one artifact."""

    def __init__(self, redactor: RecordingRedactor | None = None) -> None:
        self._redactor = redactor or RecordingRedactor()

    def import_artifact(
        self,
        store: RecordingStore,
        artifact: EventStreamArtifact,
    ) -> RecordingSession:
        """Import without ever accepting a Service-provided absolute file."""
        with _open_artifact_files(artifact) as opened:
            validated = _validate_artifact(
                opened.events,
                opened.metadata,
                artifact.recording_id,
            )
            expected = _ValidatedArtifact(
                event_count=artifact.event_count,
                dropped_event_count=artifact.dropped_event_count,
                last_seq=artifact.last_seq,
                sha256=artifact.sha256,
            )
            if validated != expected:
                raise RecordingProtocolError(
                    "EventStream artifact does not match stop result",
                )
            opened.events.seek(0)
            stream = self._normalized_events(opened.events, validated)
            return store.import_events_atomic(
                artifact.recording_id,
                stream,
                dropped_event_count=validated.dropped_event_count,
            )

    # pylint: disable=too-many-locals
    def _normalized_events(
        self,
        events_file: Any,
        expected: _ValidatedArtifact,
    ) -> Iterator[RecordingEvent]:
        normalizer = RecordingActionNormalizer()
        digest = hashlib.sha256()
        event_count = 0
        dropped = 0
        last_seq = -1
        for raw_line in events_file:
            digest.update(raw_line)
            record = _decode_record(raw_line)
            kind = record.get("kind")
            if kind == "drop":
                yield from normalizer.flush(status="native_sequence_gap")
                first = _nonnegative_int(record.get("first_seq"))
                last = _nonnegative_int(record.get("last_seq"))
                dropped += last - first + 1
                last_seq = last
                continue
            raw_event = record.get("event")
            if not isinstance(raw_event, Mapping):
                raise RecordingProtocolError("invalid staged event")
            event = self._redactor.redact_event(raw_event)
            event_count += 1
            last_seq = event.seq
            yield from normalizer.push(event)
        yield from normalizer.flush()
        actual = _ValidatedArtifact(
            event_count=event_count,
            dropped_event_count=dropped,
            last_seq=last_seq,
            sha256=digest.hexdigest(),
        )
        if actual != expected:
            raise RecordingProtocolError(
                "EventStream artifact changed during import",
            )


@dataclass
class _OpenedArtifacts:
    root_fd: int
    recording_fd: int
    events: Any
    metadata: Any

    def __enter__(self) -> "_OpenedArtifacts":
        return self

    def __exit__(self, *_args: object) -> None:
        self.events.close()
        self.metadata.close()
        os.close(self.recording_fd)
        os.close(self.root_fd)


def _open_artifact_files(artifact: EventStreamArtifact) -> _OpenedArtifacts:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        root_fd = os.open(artifact.root, flags)
        _verify_directory_fd(root_fd)
        recording_fd = os.open(
            str(artifact.recording_id),
            flags,
            dir_fd=root_fd,
        )
        _verify_directory_fd(recording_fd)
        events_fd = _open_regular_file(
            recording_fd,
            "events.jsonl",
            _MAX_EVENTS_BYTES,
        )
        try:
            metadata_fd = _open_regular_file(
                recording_fd,
                "metadata.json",
                _MAX_METADATA_BYTES,
            )
        except BaseException:
            os.close(events_fd)
            raise
    except BaseException:
        if "recording_fd" in locals():
            os.close(recording_fd)
        if "root_fd" in locals():
            os.close(root_fd)
        raise
    return _OpenedArtifacts(
        root_fd=root_fd,
        recording_fd=recording_fd,
        events=os.fdopen(events_fd, "rb"),
        metadata=os.fdopen(metadata_fd, "rb"),
    )


def _open_regular_file(directory_fd: int, name: str, maximum: int) -> int:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(name, flags, dir_fd=directory_fd)
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or info.st_size > maximum
            or info.st_uid != os.geteuid()
            or info.st_mode & 0o077
        ):
            raise RecordingStoreError("unsafe EventStream artifact file")
        return fd
    except BaseException:
        if "fd" in locals():
            os.close(fd)
        raise


def _verify_directory_fd(fd: int) -> None:
    info = os.fstat(fd)
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.geteuid()
        or info.st_mode & 0o077
    ):
        raise RecordingStoreError("unsafe EventStream artifact directory")


def _validate_artifact(  # pylint: disable=too-many-locals
    events_file: Any,
    metadata_file: Any,
    recording_id: UUID,
) -> _ValidatedArtifact:
    metadata_bytes = metadata_file.read(_MAX_METADATA_BYTES + 1)
    if len(metadata_bytes) > _MAX_METADATA_BYTES:
        raise RecordingProtocolError("EventStream metadata is too large")
    try:
        metadata = json.loads(metadata_bytes)
    except (UnicodeDecodeError, ValueError) as exc:
        raise RecordingProtocolError("invalid EventStream metadata") from exc
    if not isinstance(metadata, Mapping):
        raise RecordingProtocolError("invalid EventStream metadata")

    digest = hashlib.sha256()
    event_count = 0
    dropped = 0
    expected_seq = 0
    for raw_line in events_file:
        if len(raw_line) > _MAX_LINE_BYTES:
            raise RecordingProtocolError(
                "EventStream artifact line is too large",
            )
        digest.update(raw_line)
        record = _decode_record(raw_line)
        kind = record.get("kind")
        if kind == "event":
            event = record.get("event")
            if not isinstance(event, Mapping):
                raise RecordingProtocolError("invalid staged event")
            seq = _nonnegative_int(event.get("seq"))
            if seq != expected_seq:
                raise RecordingProtocolError(
                    "EventStream sequence gap has no drop record",
                )
            event_count += 1
            expected_seq = seq + 1
        elif kind == "drop":
            first = _nonnegative_int(record.get("first_seq"))
            last = _nonnegative_int(record.get("last_seq"))
            if first != expected_seq or last < first:
                raise RecordingProtocolError("invalid EventStream drop range")
            dropped += last - first + 1
            expected_seq = last + 1
        else:
            raise RecordingProtocolError("unknown EventStream artifact record")
    last_seq = expected_seq - 1
    validated = _ValidatedArtifact(
        event_count=event_count,
        dropped_event_count=dropped,
        last_seq=last_seq,
        sha256=digest.hexdigest(),
    )
    metadata_summary = _ValidatedArtifact(
        event_count=_nonnegative_int(metadata.get("event_count")),
        dropped_event_count=_nonnegative_int(
            metadata.get("dropped_event_count"),
        ),
        last_seq=int(metadata.get("last_seq", -2)),
        sha256=str(metadata.get("sha256") or ""),
    )
    if (
        metadata.get("artifact_schema_version") != _ARTIFACT_SCHEMA_VERSION
        or metadata.get("recording_id") != str(recording_id)
        or metadata.get("state") != "completed"
        or metadata_summary != validated
    ):
        raise RecordingProtocolError("EventStream metadata mismatch")
    return validated


def _decode_record(raw_line: bytes) -> Mapping[str, Any]:
    try:
        record = json.loads(raw_line)
    except (UnicodeDecodeError, ValueError) as exc:
        raise RecordingProtocolError("invalid EventStream JSONL") from exc
    if (
        not isinstance(record, Mapping)
        or record.get("artifact_schema_version") != _ARTIFACT_SCHEMA_VERSION
    ):
        raise RecordingProtocolError("invalid EventStream artifact record")
    return record


def _nonnegative_int(value: Any) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise RecordingProtocolError("expected a nonnegative integer")
    return value


def _validate_ref(reference: str, recording_id: UUID, name: str) -> None:
    path = Path(reference)
    if (
        path.is_absolute()
        or path.parts != (str(recording_id), name)
        or "\\" in reference
    ):
        raise RecordingProtocolError("invalid EventStream artifact reference")


__all__ = ["EventStreamArtifact", "RecordingIngestor"]
