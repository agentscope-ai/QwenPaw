# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import stat
from pathlib import Path
from typing import Any

import pytest

from record_replay.errors import (
    RecordingPrivacyError,
    RecordingStoreError,
)
from record_replay.models import RecordingEvent, RecordingState
from record_replay.normalization import RecordingActionNormalizer
from record_replay.redaction import RecordingRedactor
from record_replay.session_store import RecordingStore


def _raw_event(seq: int) -> dict[str, Any]:
    return {
        "event_schema_version": 1,
        "seq": seq,
        "t_monotonic_ms": seq * 10,
        "type": "click",
        "app": {"bundle_id": "com.apple.finder", "pid": 123},
        "window": {"window_id": 1, "title": "Downloads"},
        "target": {
            "role": "AXButton",
            "name": "Open",
            "bounds": [10, 20, 30, 40],
        },
        "input": {"button": "left", "x": 12, "y": 24},
        "redaction": {"redacted": False},
    }


def test_redactor_rejects_plaintext_fields_and_redacts_sensitive_labels() -> (
    None
):
    redactor = RecordingRedactor()
    raw = _raw_event(0)
    raw["input"]["text"] = "hunter2"
    with pytest.raises(RecordingPrivacyError, match="forbidden_plaintext"):
        redactor.redact_event(raw)

    raw = _raw_event(0)
    raw["app"]["bundle_id"] = "io.agentscope.qwenpaw.desktop"
    raw["window"]["title"] = "api_key=sk-1234567890"
    event = redactor.redact_event(raw)
    assert event.window == {"window_id": 1, "title": "[REDACTED]"}
    assert event.redaction["redacted"] is True
    assert event.redaction["reasons"] == ["sensitive_title"]


def test_redactor_preserves_only_allowlisted_ax_enrichment() -> None:
    raw = _raw_event(0)
    raw["window"].update(
        {"role": "AXWindow", "bounds": {"x": 1}, "private": "drop"},
    )
    raw["target"].update({"secure": False, "private": "drop"})
    raw["enrichment"] = {
        "status": "ok",
        "app_status": "ok",
        "duration_ms": 2.5,
        "private": "drop",
    }
    raw["source"] = {"raw_first_seq": 999, "status": "forged"}
    event = RecordingRedactor().redact_event(raw)
    assert event.window == {
        "window_id": 1,
        "title": "Downloads",
        "role": "AXWindow",
        "bounds": {"x": 1},
    }
    assert event.target == {
        "role": "AXButton",
        "name": "Open",
        "bounds": [10, 20, 30, 40],
        "secure": False,
    }
    assert event.enrichment == {
        "status": "ok",
        "app_status": "ok",
        "duration_ms": 2.5,
    }
    assert event.source == {}


def test_action_normalizer_builds_click_and_drag_with_source_ranges() -> None:
    redactor = RecordingRedactor()
    normalizer = RecordingActionNormalizer()

    def pointer(seq: int, event_type: str, x: int, y: int) -> RecordingEvent:
        raw = _raw_event(seq)
        raw["type"] = event_type
        raw["t_monotonic_ms"] = seq * 10
        raw["input"] = {
            "button": "left",
            "click_count": 1,
            "phase": {
                "pointer_down": "down",
                "pointer_up": "up",
                "drag": "update",
            }[event_type],
            "x": x,
            "y": y,
        }
        return redactor.redact_event(raw)

    output: list[RecordingEvent] = []
    for event in [
        pointer(0, "pointer_down", 10, 20),
        pointer(1, "pointer_up", 10, 20),
        pointer(2, "pointer_down", 30, 40),
        pointer(3, "drag", 40, 50),
        pointer(4, "drag", 50, 60),
        pointer(5, "pointer_up", 60, 70),
    ]:
        output.extend(normalizer.push(event))

    assert [event.type for event in output] == ["click", "drag"]
    assert [event.seq for event in output] == [1, 5]
    assert output[0].source == {
        "raw_first_seq": 0,
        "raw_last_seq": 1,
        "raw_event_count": 2,
        "status": "complete",
    }
    assert output[1].source == {
        "raw_first_seq": 2,
        "raw_last_seq": 5,
        "raw_event_count": 4,
        "status": "complete",
    }
    assert output[1].input["start_x"] == 30
    assert output[1].input["x"] == 60
    assert output[1].input["sample_count"] == 2


def test_action_normalizer_treats_subpixel_drag_update_as_click_jitter() -> (
    None
):
    redactor = RecordingRedactor()
    normalizer = RecordingActionNormalizer()

    def pointer(
        seq: int,
        event_type: str,
        x: float,
        y: float,
    ) -> RecordingEvent:
        raw = _raw_event(seq)
        raw["type"] = event_type
        raw["input"] = {
            "button": "left",
            "click_count": 1,
            "phase": {
                "pointer_down": "down",
                "pointer_up": "up",
                "drag": "update",
            }[event_type],
            "x": x,
            "y": y,
        }
        return redactor.redact_event(raw)

    output: list[RecordingEvent] = []
    for event in [
        pointer(0, "pointer_down", 303.648, 600.980),
        pointer(1, "drag", 303.527, 600.980),
        pointer(2, "pointer_up", 303.527, 600.980),
    ]:
        output.extend(normalizer.push(event))

    assert len(output) == 1
    assert output[0].type == "click"
    assert output[0].input["x"] == 303.648
    assert output[0].source["raw_event_count"] == 3


def test_action_normalizer_uses_maximum_excursion_for_returning_drag() -> None:
    redactor = RecordingRedactor()
    normalizer = RecordingActionNormalizer()

    def pointer(
        seq: int,
        event_type: str,
        x: float,
        y: float,
    ) -> RecordingEvent:
        raw = _raw_event(seq)
        raw["type"] = event_type
        raw["input"] = {
            "button": "left",
            "click_count": 1,
            "phase": {
                "pointer_down": "down",
                "pointer_up": "up",
                "drag": "update",
            }[event_type],
            "x": x,
            "y": y,
        }
        return redactor.redact_event(raw)

    output: list[RecordingEvent] = []
    for event in [
        pointer(0, "pointer_down", 10, 10),
        pointer(1, "drag", 30, 30),
        pointer(2, "pointer_up", 11, 10),
    ]:
        output.extend(normalizer.push(event))

    assert len(output) == 1
    assert output[0].type == "drag"
    assert output[0].input["start_x"] == 10
    assert output[0].input["x"] == 11


def test_action_normalizer_marks_unclosed_pointer_without_guessing() -> None:
    raw = _raw_event(0)
    raw["type"] = "pointer_down"
    raw["input"]["phase"] = "down"
    normalizer = RecordingActionNormalizer()
    assert normalizer.push(RecordingRedactor().redact_event(raw)) == []
    output = normalizer.flush()
    assert len(output) == 1
    assert output[0].type == "pointer_incomplete"
    assert output[0].source["status"] == "missing_pointer_up"


def test_action_normalizer_holds_interleaved_events_in_sequence_order() -> (
    None
):
    redactor = RecordingRedactor()
    normalizer = RecordingActionNormalizer()
    down = _raw_event(0)
    down.update({"type": "pointer_down"})
    down["input"]["phase"] = "down"
    key = _raw_event(1)
    key.update({"type": "key_down"})
    key["input"] = {
        "key_class": "printable",
        "length": 1,
        "phase": "down",
    }
    up = _raw_event(2)
    up.update({"type": "pointer_up"})
    up["input"]["phase"] = "up"

    assert normalizer.push(redactor.redact_event(down)) == []
    assert normalizer.push(redactor.redact_event(key)) == []
    stable = normalizer.push(redactor.redact_event(up))
    assert [(event.seq, event.type) for event in stable] == [
        (1, "key_down"),
        (2, "click"),
    ]


def test_store_writes_private_layout_orders_events_and_pages(
    tmp_path: Path,
) -> None:
    store = RecordingStore(tmp_path)
    session = store.create(
        workspace_id="workspace-a",
        user_id="user-a",
        agent_id="agent-a",
    )
    session = store.transition(session.recording_id, RecordingState.RECORDING)
    events = [
        RecordingEvent.model_validate(_raw_event(0)),
        RecordingEvent.model_validate(_raw_event(1)),
    ]
    session = store.append_events(session.recording_id, events)
    assert session.event_count == 2
    assert session.last_seq == 1
    assert [
        event.seq for event in store.read_events(session.recording_id)
    ] == [
        0,
        1,
    ]

    directory = tmp_path / "recordings" / str(session.recording_id)
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert stat.S_IMODE((directory / "events.jsonl").stat().st_mode) == 0o600
    assert stat.S_IMODE((directory / "session.json").stat().st_mode) == 0o600

    with pytest.raises(RecordingStoreError, match="sequence"):
        store.append_events(session.recording_id, [events[-1]])
    with pytest.raises(RecordingStoreError, match="invalid recording id"):
        store.get("../../outside")

    store.transition(session.recording_id, RecordingState.FINALIZING)
    completed = store.complete(session.recording_id)
    assert completed.state is RecordingState.COMPLETED
    summary = json.loads((directory / "summary.json").read_text())
    assert summary["first_seq"] == 0
    assert summary["last_seq"] == 1
    (directory / "summary.json").unlink()
    assert not RecordingStore(tmp_path).recover_unfinished()
    assert (directory / "summary.json").is_file()


def test_store_recovers_unfinished_session_and_repairs_counts(
    tmp_path: Path,
) -> None:
    store = RecordingStore(tmp_path)
    session = store.create(
        workspace_id="workspace-a",
        user_id="user-a",
        agent_id="agent-a",
    )
    store.transition(session.recording_id, RecordingState.RECORDING)
    event = RecordingEvent.model_validate(_raw_event(0))
    events_path = (
        tmp_path / "recordings" / str(session.recording_id) / "events.jsonl"
    )
    with events_path.open("a", encoding="utf-8") as handle:
        handle.write(event.model_dump_json() + "\n")

    recovered = RecordingStore(tmp_path).recover_unfinished()
    assert len(recovered) == 1
    assert recovered[0].state is RecordingState.INTERRUPTED
    assert recovered[0].failure_code == "process_interrupted"
    assert recovered[0].event_count == 1
    assert recovered[0].last_seq == 0
    assert (
        tmp_path / "recordings" / str(session.recording_id) / "summary.json"
    ).is_file()
