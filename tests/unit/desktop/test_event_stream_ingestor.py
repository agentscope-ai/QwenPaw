# -*- coding: utf-8 -*-
"""Safety and transaction tests for EventStream artifact import."""

from __future__ import annotations

import hashlib
import errno
import json
from pathlib import Path
import pytest

from record_replay.errors import (
    RecordingPrivacyError,
    RecordingProtocolError,
    RecordingStoreError,
)
from record_replay.ingestor import EventStreamArtifact, RecordingIngestor
from record_replay.models import RecordingState
from record_replay.session_store import RecordingStore


def _artifact(
    root: Path,
    recording_id: str,
    records: list[dict],
) -> EventStreamArtifact:
    root.mkdir(mode=0o700)
    directory = root / recording_id
    directory.mkdir(mode=0o700)
    payload = b"".join(
        json.dumps(record, separators=(",", ":")).encode() + b"\n"
        for record in records
    )
    events = directory / "events.jsonl"
    events.write_bytes(payload)
    events.chmod(0o600)
    event_count = sum(record.get("kind") == "event" for record in records)
    dropped = sum(
        record["last_seq"] - record["first_seq"] + 1
        for record in records
        if record.get("kind") == "drop"
    )
    last_seq = -1
    for record in records:
        if record.get("kind") == "event":
            last_seq = record["event"]["seq"]
        elif record.get("kind") == "drop":
            last_seq = record["last_seq"]
    digest = hashlib.sha256(payload).hexdigest()
    metadata = directory / "metadata.json"
    metadata.write_text(
        json.dumps(
            {
                "artifact_schema_version": 1,
                "recording_id": recording_id,
                "state": "completed",
                "event_count": event_count,
                "dropped_event_count": dropped,
                "last_seq": last_seq,
                "sha256": digest,
            },
        )
        + "\n",
        encoding="utf-8",
    )
    metadata.chmod(0o600)
    return EventStreamArtifact.from_stop_result(
        root,
        {
            "recording_id": recording_id,
            "events_ref": f"{recording_id}/events.jsonl",
            "metadata_ref": f"{recording_id}/metadata.json",
            "event_count": event_count,
            "dropped_event_count": dropped,
            "last_seq": last_seq,
            "sha256": digest,
        },
    )


def _event(seq: int, event_type: str, event_input: dict) -> dict:
    return {
        "artifact_schema_version": 1,
        "kind": "event",
        "event": {
            "event_schema_version": 1,
            "seq": seq,
            "t_monotonic_ms": seq + 10,
            "type": event_type,
            "input": event_input,
            "redaction": {"redacted": False, "reasons": []},
        },
    }


def _recording_store(tmp_path: Path) -> tuple[RecordingStore, str]:
    store = RecordingStore(tmp_path / "workspace")
    session = store.create(
        workspace_id="agent",
        user_id="user",
        agent_id="agent",
    )
    recording_id = str(session.recording_id)
    store.transition(recording_id, RecordingState.RECORDING)
    return store, recording_id


def test_streaming_import_normalizes_and_commits_atomically(
    tmp_path: Path,
) -> None:
    """A verified stream is normalized before one atomic Workspace commit."""
    store, recording_id = _recording_store(tmp_path)
    artifact = _artifact(
        tmp_path / "staging",
        recording_id,
        [
            _event(
                0,
                "pointer_down",
                {"button": "left", "phase": "down", "x": 1, "y": 2},
            ),
            _event(
                1,
                "pointer_up",
                {"button": "left", "phase": "up", "x": 1, "y": 2},
            ),
            {
                "artifact_schema_version": 1,
                "kind": "drop",
                "first_seq": 2,
                "last_seq": 3,
                "reason": "native_queue_full",
            },
            _event(4, "scroll", {"delta_x": 0, "delta_y": -1}),
        ],
    )

    imported = RecordingIngestor().import_artifact(store, artifact)

    assert imported.event_count == 2
    assert imported.dropped_event_count == 2
    assert imported.last_seq == 4
    events = store.read_events(recording_id, limit=10)
    assert [event.type for event in events] == ["click", "scroll"]


def test_privacy_failure_leaves_workspace_events_empty(
    tmp_path: Path,
) -> None:
    """Forbidden native fields never leave a partial final JSONL."""
    store, recording_id = _recording_store(tmp_path)
    unsafe = _event(0, "key_down", {"key_class": "printable", "length": 1})
    unsafe["event"]["characters"] = "secret"
    artifact = _artifact(tmp_path / "staging", recording_id, [unsafe])

    with pytest.raises(RecordingPrivacyError):
        RecordingIngestor().import_artifact(store, artifact)

    assert store.get(recording_id).event_count == 0
    assert not store.read_events(recording_id, limit=10)


def test_privacy_gap_breaks_click_pair_and_preserves_counts(tmp_path):
    store, recording_id = _recording_store(tmp_path)
    artifact = _artifact(
        tmp_path / "staging",
        recording_id,
        [
            _event(0, "pointer_down", {"button": "left", "x": 1, "y": 2}),
            {
                "artifact_schema_version": 1,
                "kind": "drop",
                "first_seq": 1,
                "last_seq": 3,
                "reason": "privacy_filtered",
            },
            _event(4, "pointer_up", {"button": "left", "x": 1, "y": 2}),
        ],
    )
    imported = RecordingIngestor().import_artifact(store, artifact)
    assert imported.dropped_event_count == 3
    assert imported.last_seq == 4
    assert all(
        event.type != "click"
        for event in store.read_events(recording_id, limit=10)
    )


def test_excluded_app_rejection_is_atomic_after_a_valid_event(tmp_path):
    store, recording_id = _recording_store(tmp_path)
    bad = _event(1, "scroll", {"delta_y": 1})
    bad["event"]["app"] = {"bundle_id": "com.bitwarden.desktop"}
    artifact = _artifact(
        tmp_path / "staging",
        recording_id,
        [
            _event(0, "scroll", {"delta_y": 1}),
            bad,
        ],
    )
    with pytest.raises(RecordingPrivacyError, match="excluded_recording_app"):
        RecordingIngestor().import_artifact(store, artifact)
    assert store.get(recording_id).event_count == 0
    assert not store.read_events(recording_id, limit=10)


def test_keyboard_code_after_valid_event_never_publishes_partial_import(
    tmp_path,
):
    store, recording_id = _recording_store(tmp_path)
    safe = _event(0, "scroll", {"delta_y": 1})
    unsafe = _event(1, "key_down", {"key_class": "printable", "length": 1})
    unsafe["event"]["input"]["key_code"] = 42
    artifact = _artifact(tmp_path / "staging", recording_id, [safe, unsafe])
    with pytest.raises(
        RecordingPrivacyError,
        match="forbidden_plaintext_field",
    ):
        RecordingIngestor().import_artifact(store, artifact)
    assert store.get(recording_id).event_count == 0
    assert not store.read_events(recording_id, limit=10)


def test_unreported_sequence_gap_never_publishes_partial_events(
    tmp_path: Path,
) -> None:
    store, recording_id = _recording_store(tmp_path)
    artifact = _artifact(
        tmp_path / "staging",
        recording_id,
        [
            _event(0, "scroll", {"delta_y": 1}),
            _event(2, "scroll", {"delta_y": 1}),
        ],
    )
    with pytest.raises(RecordingProtocolError, match="sequence gap"):
        RecordingIngestor().import_artifact(store, artifact)
    assert store.get(recording_id).event_count == 0
    assert not store.read_events(recording_id, limit=10)


def test_stop_result_without_last_sequence_is_rejected(tmp_path: Path) -> None:
    _, recording_id = _recording_store(tmp_path)
    with pytest.raises(RecordingProtocolError):
        EventStreamArtifact.from_stop_result(
            tmp_path / "staging",
            {
                "recording_id": recording_id,
                "events_ref": f"{recording_id}/events.jsonl",
                "metadata_ref": f"{recording_id}/metadata.json",
                "event_count": 1,
                "dropped_event_count": 0,
                "sha256": "0" * 64,
            },
        )


@pytest.mark.parametrize(
    "malformed",
    [
        {"target": {"bounds": {"x": {"annotation": "FAKE_PRIVATE"}}}},
        {"app": {"name": ["FAKE_PRIVATE"]}},
        {"input": {"modifiers": [{"annotation": "FAKE_PRIVATE"}]}},
    ],
)
def test_shape_failure_after_valid_event_does_not_publish_partial_import(
    tmp_path: Path,
    malformed: dict,
) -> None:
    """Python protects the transaction even if an older producer missed it."""
    store, recording_id = _recording_store(tmp_path)
    unsafe = _event(1, "scroll", {"delta_y": 1})
    unsafe["event"].update(malformed)
    artifact = _artifact(
        tmp_path / "staging",
        recording_id,
        [_event(0, "scroll", {"delta_y": 1}), unsafe],
    )
    with pytest.raises(RecordingPrivacyError, match="invalid_"):
        RecordingIngestor().import_artifact(store, artifact)
    assert store.get(recording_id).event_count == 0
    assert not store.read_events(recording_id, limit=10)


def test_symlinked_artifact_is_rejected(
    tmp_path: Path,
) -> None:
    """Artifact files do not follow attacker-controlled links."""
    store, recording_id = _recording_store(tmp_path)
    artifact = _artifact(
        tmp_path / "staging",
        recording_id,
        [_event(0, "scroll", {"delta_x": 0, "delta_y": 1})],
    )
    events = artifact.root / artifact.events_ref
    real = events.with_name("real-events.jsonl")
    events.rename(real)
    events.symlink_to(real.name)

    with pytest.raises((OSError, RecordingStoreError)):
        RecordingIngestor().import_artifact(store, artifact)


def test_metadata_recording_id_must_match_stop_result(
    tmp_path: Path,
) -> None:
    """A valid hash cannot bind another recording's metadata."""
    store, recording_id = _recording_store(tmp_path)
    artifact = _artifact(
        tmp_path / "staging",
        recording_id,
        [_event(0, "scroll", {"delta_x": 0, "delta_y": 1})],
    )
    metadata = artifact.root / artifact.metadata_ref
    value = json.loads(metadata.read_text(encoding="utf-8"))
    value["recording_id"] = "00000000-0000-0000-0000-000000000000"
    metadata.write_text(json.dumps(value) + "\n", encoding="utf-8")

    with pytest.raises(RecordingProtocolError):
        RecordingIngestor().import_artifact(store, artifact)


def test_stop_result_requires_a_hex_digest(tmp_path: Path) -> None:
    """The stop result digest must be exactly one SHA-256 value."""
    root = tmp_path / "staging"
    root.mkdir()

    with pytest.raises(RecordingProtocolError):
        EventStreamArtifact.from_stop_result(
            root.resolve(),
            {
                "recording_id": "00000000-0000-0000-0000-000000000000",
                "events_ref": (
                    "00000000-0000-0000-0000-000000000000/events.jsonl"
                ),
                "metadata_ref": (
                    "00000000-0000-0000-0000-000000000000/metadata.json"
                ),
                "event_count": 0,
                "dropped_event_count": 0,
                "last_seq": -1,
                "sha256": "z" * 64,
            },
        )


@pytest.mark.parametrize("failure_point", ["fsync", "replace"])
def test_import_enospc_never_publishes_partial_events(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_point: str,
) -> None:
    """Inject ENOSPC at import without filling the host disk."""
    import record_replay.session_store as store_module

    store, recording_id = _recording_store(tmp_path)
    artifact = _artifact(
        tmp_path / "staging",
        recording_id,
        [_event(0, "scroll", {"delta_y": 1})],
    )

    def no_space(*_args: object, **_kwargs: object) -> None:
        raise OSError(errno.ENOSPC, "isolated ENOSPC fixture")

    with monkeypatch.context() as patch:
        patch.setattr(store_module.os, failure_point, no_space)
        with pytest.raises(OSError) as error:
            RecordingIngestor().import_artifact(store, artifact)
        assert error.value.errno == errno.ENOSPC
    assert store.get(recording_id).event_count == 0
    assert not store.read_events(recording_id)
    directory = store.workspace_dir / "recordings" / recording_id
    assert not list(directory.glob(".events.import-*"))
    # The original verified artifact is still available to its owner.
    assert (artifact.root / artifact.events_ref).is_file()
