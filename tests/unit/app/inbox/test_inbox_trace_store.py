# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,protected-access,unused-argument
# pylint: disable=use-implicit-booleaness-not-comparison
"""Unit tests for qwenpaw.app.inbox_trace_store.

Real file IO through a monkeypatched ``_TRACE_DIR`` — no over-mocking.
Covers: create_trace, append_trace_events (normalization, pydantic
model_dump, non-dict filtering, default timestamps), flatten_session_messages,
parse_session_timestamp, read_session_messages (with a fake runner),
append_trace_from_session_delta (baseline→delta calc), finalize_trace,
get_trace, delete_trace, and low-level _to_jsonable / _read_trace edges.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from qwenpaw.app import inbox_trace_store as trace_store


@pytest.fixture
def trace_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect module-level _TRACE_DIR to a tmp directory."""
    target = tmp_path / "inbox_traces"
    monkeypatch.setattr(trace_store, "_TRACE_DIR", target)
    return target


# ---------------------------------------------------------------------------
# _to_jsonable
# ---------------------------------------------------------------------------


def test_to_jsonable_primitives_passthrough():
    assert trace_store._to_jsonable(None) is None
    assert trace_store._to_jsonable("s") == "s"
    assert trace_store._to_jsonable(1) == 1
    assert trace_store._to_jsonable(1.5) == 1.5
    assert trace_store._to_jsonable(True) is True


def test_to_jsonable_list_and_dict_recursive():
    payload = {"a": [1, {"b": "c"}], "n": None}
    out = trace_store._to_jsonable(payload)
    assert out == {"a": [1, {"b": "c"}], "n": None}


def test_to_jsonable_dict_keys_stringified():
    out = trace_store._to_jsonable({1: "a", 2: "b"})
    assert out == {"1": "a", "2": "b"}


def test_to_jsonable_pydantic_like_model_dump():
    class FakeModel:
        def model_dump(self, mode: str = "python"):
            return {"k": "v", "mode": mode}

    out = trace_store._to_jsonable(FakeModel())
    assert out == {"k": "v", "mode": "json"}


def test_to_jsonable_falls_back_to_repr():
    class _Weird:
        pass

    out = trace_store._to_jsonable(_Weird())
    assert isinstance(out, dict)
    assert "repr" in out
    assert "_Weird" in out["repr"]


# ---------------------------------------------------------------------------
# create_trace
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_trace_writes_initial_payload(trace_dir: Path):
    await trace_store.create_trace("run-1", meta={"agent": "a"})
    path = trace_dir / "run-1.json"
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["run_id"] == "run-1"
    assert data["status"] == "running"
    assert data["completed_at"] is None
    assert data["meta"] == {"agent": "a"}
    assert data["events"] == []
    assert isinstance(data["created_at"], float)


@pytest.mark.asyncio
async def test_create_trace_default_meta_is_empty_dict(trace_dir: Path):
    await trace_store.create_trace("run-2")
    data = json.loads((trace_dir / "run-2.json").read_text(encoding="utf-8"))
    assert data["meta"] == {}


# ---------------------------------------------------------------------------
# append_trace_events
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_append_trace_events_appends_to_existing(trace_dir: Path):
    await trace_store.create_trace("run-1")
    await trace_store.append_trace_events(
        "run-1",
        [{"at": 1.0, "event": {"text": "first"}}],
    )
    await trace_store.append_trace_events(
        "run-1",
        [{"at": 2.0, "event": {"text": "second"}}],
    )
    data = json.loads((trace_dir / "run-1.json").read_text(encoding="utf-8"))
    events = data["events"]
    assert len(events) == 2
    assert events[0]["event"]["text"] == "first"
    assert events[1]["event"]["text"] == "second"


@pytest.mark.asyncio
async def test_append_trace_events_creates_trace_if_missing(trace_dir: Path):
    # _read_trace returns a default payload when the file is missing, so
    # append_trace_events bootstraps the trace on first call.
    await trace_store.append_trace_events(
        "run-bootstrap",
        [{"at": 1.0, "event": {"x": 1}}],
    )
    data = json.loads(
        (trace_dir / "run-bootstrap.json").read_text(encoding="utf-8"),
    )
    assert len(data["events"]) == 1


@pytest.mark.asyncio
async def test_append_trace_events_defaults_at_timestamp(trace_dir: Path):
    before = time.time()
    await trace_store.create_trace("run-1")
    await trace_store.append_trace_events(
        "run-1",
        [{"event": {"text": "no-at"}}],
    )
    data = json.loads((trace_dir / "run-1.json").read_text(encoding="utf-8"))
    at = data["events"][0]["at"]
    assert isinstance(at, float)
    assert at >= before


@pytest.mark.asyncio
async def test_append_trace_events_filters_non_dict_items(trace_dir: Path):
    await trace_store.create_trace("run-1")
    await trace_store.append_trace_events(
        "run-1",
        [
            {"at": 1.0, "event": {"keep": True}},
            "not-a-dict",
            42,
            None,
        ],
    )
    data = json.loads((trace_dir / "run-1.json").read_text(encoding="utf-8"))
    assert len(data["events"]) == 1
    assert data["events"][0]["event"] == {"keep": True}


@pytest.mark.asyncio
async def test_append_trace_events_normalizes_pydantic_event(trace_dir: Path):
    class FakeModel:
        def model_dump(self, mode: str = "python"):
            return {"role": "assistant", "content": "hi"}

    await trace_store.create_trace("run-1")
    await trace_store.append_trace_events(
        "run-1",
        [{"at": 1.0, "event": FakeModel()}],
    )
    data = json.loads((trace_dir / "run-1.json").read_text(encoding="utf-8"))
    assert data["events"][0]["event"] == {
        "role": "assistant",
        "content": "hi",
    }


@pytest.mark.asyncio
async def test_append_trace_events_empty_list_is_noop(trace_dir: Path):
    await trace_store.create_trace("run-1")
    # Empty input should not raise and should not mutate the file.
    await trace_store.append_trace_events("run-1", [])
    data = json.loads((trace_dir / "run-1.json").read_text(encoding="utf-8"))
    assert data["events"] == []


@pytest.mark.asyncio
async def test_append_trace_events_all_non_dict_is_noop(trace_dir: Path):
    await trace_store.create_trace("run-1")
    await trace_store.append_trace_events("run-1", ["x", 1, None])
    data = json.loads((trace_dir / "run-1.json").read_text(encoding="utf-8"))
    assert data["events"] == []


# ---------------------------------------------------------------------------
# flatten_session_messages
# ---------------------------------------------------------------------------


def test_flatten_session_messages_non_list_returns_empty():
    assert trace_store.flatten_session_messages("not a list") == []
    assert trace_store.flatten_session_messages(None) == []
    assert trace_store.flatten_session_messages({"a": 1}) == []


def test_flatten_session_messages_dicts_kept_as_is():
    msgs = [{"role": "user", "content": "hi"}, {"role": "assistant"}]
    assert trace_store.flatten_session_messages(msgs) == msgs


def test_flatten_session_messages_nested_list_unwraps_first_dict():
    # agentscope sometimes returns [[{message}], ...] — unwrap first dict.
    msgs = [[{"role": "user", "content": "x"}], [{"role": "assistant"}]]
    flat = trace_store.flatten_session_messages(msgs)
    assert flat == [{"role": "user", "content": "x"}, {"role": "assistant"}]


def test_flatten_session_messages_skips_empty_or_non_dict_inner_lists():
    msgs = [{"a": 1}, [], [42, "str"], {"b": 2}]
    flat = trace_store.flatten_session_messages(msgs)
    # Empty inner list and inner list whose first item isn't a dict are
    # skipped; bare dicts are kept.
    assert flat == [{"a": 1}, {"b": 2}]


# ---------------------------------------------------------------------------
# parse_session_timestamp
# ---------------------------------------------------------------------------


def test_parse_session_timestamp_iso():
    from datetime import datetime

    raw = "2024-01-02T03:04:05"
    ts = trace_store.parse_session_timestamp(raw)
    assert ts is not None
    # Compare against the same naive-datetime interpretation (tz-independent).
    assert ts == pytest.approx(datetime.fromisoformat(raw).timestamp())


def test_parse_session_timestamp_iso_with_fractional():
    from datetime import datetime

    raw = "2024-01-02T03:04:05.123456"
    ts = trace_store.parse_session_timestamp(raw)
    assert ts is not None
    assert ts == pytest.approx(datetime.fromisoformat(raw).timestamp())


def test_parse_session_timestamp_space_separated_with_microseconds():
    ts = trace_store.parse_session_timestamp("2024-01-02 03:04:05.123456")
    assert ts is not None


def test_parse_session_timestamp_space_separated_seconds():
    ts = trace_store.parse_session_timestamp("2024-01-02 03:04:05")
    assert ts is not None


def test_parse_session_timestamp_invalid_returns_none():
    assert trace_store.parse_session_timestamp("not a date") is None


def test_parse_session_timestamp_empty_returns_none():
    assert trace_store.parse_session_timestamp("") is None
    assert trace_store.parse_session_timestamp("   ") is None


def test_parse_session_timestamp_non_string_returns_none():
    assert trace_store.parse_session_timestamp(None) is None
    assert trace_store.parse_session_timestamp(123) is None


# ---------------------------------------------------------------------------
# read_session_messages (with a fake runner)
# ---------------------------------------------------------------------------


class _FakeSession:
    def __init__(self, state: dict | Exception):
        self._state = state

    async def get_session_state_dict(
        self,
        session_id,
        user_id,
        channel,
        *,
        allow_not_exist,
    ):
        if isinstance(self._state, Exception):
            raise self._state
        return self._state


@pytest.mark.asyncio
async def test_read_session_messages_no_session_returns_empty(trace_dir: Path):
    runner = SimpleNamespace(session=None)
    out = await trace_store.read_session_messages(
        runner=runner,
        session_id="s",
        user_id="u",
        channel="c",
    )
    assert out == []


@pytest.mark.asyncio
async def test_read_session_messages_exception_returns_empty(trace_dir: Path):
    runner = SimpleNamespace(
        session=_FakeSession(RuntimeError("session backend down")),
    )
    out = await trace_store.read_session_messages(
        runner=runner,
        session_id="s",
        user_id="u",
        channel="c",
    )
    assert out == []


@pytest.mark.asyncio
async def test_read_session_messages_extracts_context_messages(
    trace_dir: Path,
):
    state = {
        "agent": {
            "state": {
                "context": [
                    {"role": "user", "content": "hi"},
                    {"role": "assistant", "content": "hello"},
                ],
            },
        },
    }
    runner = SimpleNamespace(session=_FakeSession(state))
    out = await trace_store.read_session_messages(
        runner=runner,
        session_id="s",
        user_id="u",
        channel="c",
    )
    assert len(out) == 2
    assert out[0]["role"] == "user"
    assert out[1]["role"] == "assistant"


@pytest.mark.asyncio
async def test_read_session_messages_missing_context_returns_empty(
    trace_dir: Path,
):
    state = {"agent": {"state": {}}}
    runner = SimpleNamespace(session=_FakeSession(state))
    out = await trace_store.read_session_messages(
        runner=runner,
        session_id="s",
        user_id="u",
        channel="c",
    )
    assert out == []


# ---------------------------------------------------------------------------
# append_trace_from_session_delta
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_append_trace_from_session_delta_appends_only_new(
    trace_dir: Path,
):
    state = {
        "agent": {
            "state": {
                "context": [
                    {
                        "role": "user",
                        "content": "m1",
                        "created_at": "2024-01-02T03:04:05",
                    },
                    {
                        "role": "assistant",
                        "content": "m2",
                        "created_at": "2024-01-02T03:04:06",
                    },
                    {
                        "role": "user",
                        "content": "m3",
                        "created_at": "2024-01-02T03:04:07",
                    },
                ],
            },
        },
    }
    runner = SimpleNamespace(session=_FakeSession(state))
    await trace_store.create_trace("run-delta")
    delta = await trace_store.append_trace_from_session_delta(
        run_id="run-delta",
        runner=runner,
        session_id="s",
        user_id="u",
        channel="c",
        baseline_count=1,
    )
    # Only the 2 messages beyond the baseline should be returned & appended.
    assert len(delta) == 2
    assert delta[0]["content"] == "m2"
    assert delta[1]["content"] == "m3"
    data = json.loads(
        (trace_dir / "run-delta.json").read_text(encoding="utf-8"),
    )
    assert len(data["events"]) == 2
    # Parsed timestamps should be floats, not None (ISO strings are parseable).
    assert isinstance(data["events"][0]["at"], float)


@pytest.mark.asyncio
async def test_append_trace_from_session_delta_baseline_zero(trace_dir: Path):
    state = {
        "agent": {
            "state": {
                "context": [
                    {"role": "user", "content": "only"},
                ],
            },
        },
    }
    runner = SimpleNamespace(session=_FakeSession(state))
    await trace_store.create_trace("run-delta-0")
    delta = await trace_store.append_trace_from_session_delta(
        run_id="run-delta-0",
        runner=runner,
        session_id="s",
        user_id="u",
        channel="c",
        baseline_count=0,
    )
    assert len(delta) == 1


@pytest.mark.asyncio
async def test_append_trace_from_session_delta_negative_baseline_clamped(
    trace_dir: Path,
):
    state = {
        "agent": {"state": {"context": [{"content": "a"}, {"content": "b"}]}},
    }
    runner = SimpleNamespace(session=_FakeSession(state))
    await trace_store.create_trace("run-neg")
    delta = await trace_store.append_trace_from_session_delta(
        run_id="run-neg",
        runner=runner,
        session_id="s",
        user_id="u",
        channel="c",
        baseline_count=-5,
    )
    # Negative baseline is clamped to 0, so both messages are returned.
    assert len(delta) == 2


# ---------------------------------------------------------------------------
# finalize_trace
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_finalize_trace_sets_status_and_completed_at(trace_dir: Path):
    await trace_store.create_trace("run-1")
    before = time.time()
    await trace_store.finalize_trace("run-1", status="success")
    data = json.loads((trace_dir / "run-1.json").read_text(encoding="utf-8"))
    assert data["status"] == "success"
    assert isinstance(data["completed_at"], float)
    assert data["completed_at"] >= before


@pytest.mark.asyncio
async def test_finalize_trace_records_error_message(trace_dir: Path):
    await trace_store.create_trace("run-1")
    await trace_store.finalize_trace("run-1", status="error", error="boom")
    data = json.loads((trace_dir / "run-1.json").read_text(encoding="utf-8"))
    assert data["status"] == "error"
    assert data["error"] == "boom"


@pytest.mark.asyncio
async def test_finalize_trace_without_error_keeps_field_absent(
    trace_dir: Path,
):
    await trace_store.create_trace("run-1")
    await trace_store.finalize_trace("run-1", status="success")
    data = json.loads((trace_dir / "run-1.json").read_text(encoding="utf-8"))
    assert "error" not in data


# ---------------------------------------------------------------------------
# get_trace
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_trace_returns_none_when_missing(trace_dir: Path):
    assert await trace_store.get_trace("ghost") is None


@pytest.mark.asyncio
async def test_get_trace_returns_payload(trace_dir: Path):
    await trace_store.create_trace("run-1", meta={"k": "v"})
    out = await trace_store.get_trace("run-1")
    assert out is not None
    assert out["run_id"] == "run-1"
    assert out["meta"] == {"k": "v"}


@pytest.mark.asyncio
async def test_get_trace_on_invalid_json_raises(trace_dir: Path):
    # _read_trace raises ValueError for non-dict JSON. get_trace forwards
    # that — callers must not silently swallow corrupted trace files.
    trace_dir.mkdir(parents=True, exist_ok=True)
    (trace_dir / "run-bad.json").write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid trace file"):
        await trace_store.get_trace("run-bad")


# ---------------------------------------------------------------------------
# delete_trace
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_trace_returns_false_for_empty_id(trace_dir: Path):
    assert await trace_store.delete_trace("") is False


@pytest.mark.asyncio
async def test_delete_trace_returns_false_when_missing(trace_dir: Path):
    assert await trace_store.delete_trace("ghost") is False


@pytest.mark.asyncio
async def test_delete_trace_removes_file_and_returns_true(trace_dir: Path):
    await trace_store.create_trace("run-1")
    path = trace_dir / "run-1.json"
    assert path.exists()
    assert await trace_store.delete_trace("run-1") is True
    assert not path.exists()


@pytest.mark.asyncio
async def test_delete_trace_idempotent(trace_dir: Path):
    await trace_store.create_trace("run-1")
    assert await trace_store.delete_trace("run-1") is True
    assert await trace_store.delete_trace("run-1") is False
