# -*- coding: utf-8 -*-
from __future__ import annotations

from qwenpaw.app.inbox_trace_store import (
    _to_jsonable,
    flatten_session_messages,
    parse_session_timestamp,
)


# ---------------------------------------------------------------------------
# _to_jsonable — recursive JSON serialization
# ---------------------------------------------------------------------------


def test_to_jsonable_primitives():
    assert _to_jsonable(None) is None
    assert _to_jsonable("hello") == "hello"
    assert _to_jsonable(42) == 42
    assert _to_jsonable(3.14) == 3.14
    assert _to_jsonable(True) is True


def test_to_jsonable_list():
    assert _to_jsonable([1, "a", None]) == [1, "a", None]


def test_to_jsonable_dict():
    assert _to_jsonable({"x": 1}) == {"x": 1}


def test_to_jsonable_nested():
    data = {"items": [1, {"k": "v"}], "n": None}
    assert _to_jsonable(data) == {"items": [1, {"k": "v"}], "n": None}


def test_to_jsonable_pydantic_model():
    from qwenpaw.app.crons.models import CronJobState

    state = CronJobState(last_status="running")
    result = _to_jsonable(state)
    assert isinstance(result, dict)
    assert result["last_status"] == "running"


def test_to_jsonable_fallback_repr():
    class Weird:
        pass

    result = _to_jsonable(Weird())
    assert "repr" in result


# ---------------------------------------------------------------------------
# flatten_session_messages
# ---------------------------------------------------------------------------


def test_flatten_dict_items():
    content = [{"role": "user"}, {"role": "assistant"}]
    assert flatten_session_messages(content) == content


def test_flatten_nested_list_takes_first():
    content = [[{"role": "user"}], [{"role": "assistant"}]]
    result = flatten_session_messages(content)
    assert len(result) == 2
    assert result[0]["role"] == "user"


def test_flatten_skips_non_dict():
    content = [{"role": "user"}, "noise", 42]
    result = flatten_session_messages(content)
    assert len(result) == 1


def test_flatten_empty_list():
    assert len(flatten_session_messages([])) == 0


def test_flatten_non_list_returns_empty():
    assert len(flatten_session_messages("not a list")) == 0


def test_flatten_empty_nested_list():
    assert len(flatten_session_messages([[]])) == 0


# ---------------------------------------------------------------------------
# parse_session_timestamp
# ---------------------------------------------------------------------------


def test_parse_timestamp_with_microseconds():
    result = parse_session_timestamp("2025-06-20 09:30:00.123456")
    assert result is not None
    assert isinstance(result, float)


def test_parse_timestamp_without_microseconds():
    result = parse_session_timestamp("2025-06-20 09:30:00")
    assert result is not None


def test_parse_timestamp_invalid_returns_none():
    assert parse_session_timestamp("not-a-date") is None


def test_parse_timestamp_empty_returns_none():
    assert parse_session_timestamp("") is None
    assert parse_session_timestamp("   ") is None


def test_parse_timestamp_non_string_returns_none():
    assert parse_session_timestamp(12345) is None
