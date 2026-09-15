# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name,unused-argument
"""Unit tests for the query-handler error dump writer.

The module's contract is "never let diagnostics break the request path": it
returns ``None`` instead of raising when the dump itself fails.
"""

import json
import os

import pytest

from qwenpaw.app.chats import query_error_dump as dump_mod


@pytest.fixture()
def tmpdir_for_dumps(monkeypatch, tmp_path):
    """Redirect tempfile.gettempdir() so dumps land in the test dir."""
    target = tmp_path / "dumps"
    target.mkdir()
    monkeypatch.setattr(dump_mod.tempfile, "gettempdir", lambda: str(target))
    return target


class _Request:
    """A plain object exercising the ``vars()`` branch."""

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class _PydanticLike:
    def model_dump(self):
        return {"session_id": "s-1", "user_id": "u-1", "extra": {"a": 1}}


class _LegacyPydantic:
    def dict(self):
        return {"session_id": "legacy", "user_id": "u-legacy"}


class TestSafeJsonSerialize:
    def test_passes_scalars_through(self):
        for value in (None, True, 3, 3.5, "text"):
            assert dump_mod._safe_json_serialize(value) == value

    def test_bool_is_not_coerced_to_int(self):
        assert dump_mod._safe_json_serialize(True) is True

    def test_converts_list_and_tuple_to_list(self):
        assert dump_mod._safe_json_serialize([1, "a"]) == [1, "a"]
        assert dump_mod._safe_json_serialize((1, "a")) == [1, "a"]

    def test_recurses_into_nested_containers(self):
        payload = {"a": [1, {"b": (2, None)}]}
        assert dump_mod._safe_json_serialize(payload) == {
            "a": [1, {"b": [2, None]}],
        }

    def test_stringifies_dict_keys(self):
        result = dump_mod._safe_json_serialize({1: "one", (2,): "two"})
        assert set(result) == {"1", "(2,)"}

    def test_falls_back_to_str_for_unknown_types(self):
        class Opaque:
            def __str__(self):
                return "opaque-repr"

        assert dump_mod._safe_json_serialize(Opaque()) == "opaque-repr"

    def test_result_is_always_json_serializable(self):
        class Opaque:
            pass

        payload = {"obj": Opaque(), "list": [Opaque()], "n": 1}
        json.dumps(dump_mod._safe_json_serialize(payload))


class TestRequestToDict:
    def test_none_request_returns_none(self):
        assert dump_mod._request_to_dict(None) is None

    def test_uses_model_dump_when_available(self):
        result = dump_mod._request_to_dict(_PydanticLike())
        assert result == {
            "session_id": "s-1",
            "user_id": "u-1",
            "extra": {"a": 1},
        }

    def test_prefers_model_dump_over_dict(self):
        class Both:
            def model_dump(self):
                return {"via": "model_dump"}

            def dict(self):
                return {"via": "dict"}

        assert dump_mod._request_to_dict(Both()) == {"via": "model_dump"}

    def test_falls_back_to_legacy_dict(self):
        result = dump_mod._request_to_dict(_LegacyPydantic())
        assert result == {"session_id": "legacy", "user_id": "u-legacy"}

    def test_falls_back_to_vars_for_plain_objects(self):
        result = dump_mod._request_to_dict(_Request(a=1, b="x"))
        assert result == {"a": 1, "b": "x"}

    def test_recovers_when_model_dump_returns_a_non_dict(self):
        class Broken:
            def __init__(self):
                self.real = "value"

            def model_dump(self):
                return ["not", "a", "dict"]

        result = dump_mod._request_to_dict(Broken())
        assert result == {"real": "value"}

    def test_swallows_serialization_errors(self):
        class Exploding:
            def model_dump(self):
                raise RuntimeError("cannot serialize")

            def __str__(self):
                return "exploding-request"

        assert dump_mod._request_to_dict(Exploding()) == {
            "_serialize_error": "exploding-request",
        }


class TestWriteQueryErrorDump:
    def _raise_and_dump(self, request, locals_, exc=None):
        """Produce a real traceback so format_exc() has content.

        The dump call must happen inside the except block: outside it
        sys.exc_info() is cleared and traceback.format_exc() returns
        "NoneType: None".
        """
        result = None
        try:
            raise exc if exc is not None else ValueError("boom")
        except BaseException as caught:  # noqa: BLE001 - mirroring prod usage
            result = dump_mod.write_query_error_dump(request, caught, locals_)
        return result

    def test_returns_a_path_and_writes_valid_json(self, tmpdir_for_dumps):
        path = self._raise_and_dump(_Request(session_id="s", user_id="u"), {})

        assert path is not None
        assert os.path.isfile(path)
        with open(path, encoding="utf-8") as handle:
            payload = json.loads(handle.read())
        assert isinstance(payload, dict)

    def test_file_lands_in_the_configured_temp_dir(self, tmpdir_for_dumps):
        path = self._raise_and_dump(None, {})
        assert os.path.dirname(path) == str(tmpdir_for_dumps)

    def test_filename_uses_the_expected_prefix_and_suffix(
        self, tmpdir_for_dumps
    ):
        path = self._raise_and_dump(None, {})
        name = os.path.basename(path)
        assert name.startswith("qwenpaw_query_error_")
        assert name.endswith(".json")

    def test_records_exception_type_and_message(self, tmpdir_for_dumps):
        path = self._raise_and_dump(None, {}, exc=KeyError("missing-key"))
        with open(path, encoding="utf-8") as handle:
            payload = json.loads(handle.read())

        assert payload["exception_type"] == "KeyError"
        assert "missing-key" in payload["exception_message"]

    def test_records_the_traceback(self, tmpdir_for_dumps):
        path = self._raise_and_dump(None, {})
        with open(path, encoding="utf-8") as handle:
            payload = json.loads(handle.read())

        assert "Traceback" in payload["trace"]
        assert "ValueError" in payload["trace"]

    def test_timestamp_is_utc_and_zulu_formatted(self, tmpdir_for_dumps):
        path = self._raise_and_dump(None, {})
        with open(path, encoding="utf-8") as handle:
            payload = json.loads(handle.read())

        import re

        assert re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", payload["ts_utc"]
        )

    def test_request_fields_are_extracted(self, tmpdir_for_dumps):
        request = _Request(session_id="sess-9", user_id="user-9")
        path = self._raise_and_dump(request, {})
        with open(path, encoding="utf-8") as handle:
            payload = json.loads(handle.read())

        info = payload["request_info"]
        assert info["session_id"] == "sess-9"
        assert info["user_id"] == "user-9"

    def test_channel_defaults_when_absent(self, tmpdir_for_dumps):
        from qwenpaw.app.channels.schema import DEFAULT_CHANNEL

        path = self._raise_and_dump(_Request(session_id="s"), {})
        with open(path, encoding="utf-8") as handle:
            payload = json.loads(handle.read())

        assert payload["request_info"]["channel"] == DEFAULT_CHANNEL

    def test_channel_is_taken_from_the_request_when_present(
        self, tmpdir_for_dumps
    ):
        request = _Request(session_id="s", channel="dingtalk")
        path = self._raise_and_dump(request, {})
        with open(path, encoding="utf-8") as handle:
            payload = json.loads(handle.read())

        assert payload["request_info"]["channel"] == "dingtalk"

    def test_none_request_yields_empty_info_and_null_body(
        self, tmpdir_for_dumps
    ):
        path = self._raise_and_dump(None, {})
        with open(path, encoding="utf-8") as handle:
            payload = json.loads(handle.read())

        assert payload["request_info"] == {}
        assert payload["request"] is None

    def test_full_request_is_serialized(self, tmpdir_for_dumps):
        path = self._raise_and_dump(_PydanticLike(), {})
        with open(path, encoding="utf-8") as handle:
            payload = json.loads(handle.read())

        assert payload["request"]["session_id"] == "s-1"

    def test_agent_state_is_captured_when_present(self, tmpdir_for_dumps):
        class Agent:
            def state_dict(self):
                return {"turns": 3, "pending": ("a", "b")}

        path = self._raise_and_dump(None, {"agent": Agent()})
        with open(path, encoding="utf-8") as handle:
            payload = json.loads(handle.read())

        assert payload["agent_state"] == {"turns": 3, "pending": ["a", "b"]}

    def test_agent_state_is_null_when_no_agent(self, tmpdir_for_dumps):
        path = self._raise_and_dump(None, {})
        with open(path, encoding="utf-8") as handle:
            payload = json.loads(handle.read())

        assert payload["agent_state"] is None

    def test_agent_state_error_is_recorded_not_raised(self, tmpdir_for_dumps):
        class BrokenAgent:
            def state_dict(self):
                raise RuntimeError("state exploded")

        path = self._raise_and_dump(None, {"agent": BrokenAgent()})
        with open(path, encoding="utf-8") as handle:
            payload = json.loads(handle.read())

        assert payload["agent_state"] == {
            "_serialize_error": "state exploded",
        }

    def test_unicode_is_written_not_escaped(self, tmpdir_for_dumps):
        class Agent:
            def state_dict(self):
                return {"note": "中文备注"}

        path = self._raise_and_dump(None, {"agent": Agent()})
        with open(path, encoding="utf-8") as handle:
            raw = handle.read()

        # ensure_ascii=False means the characters appear literally.
        assert "中文备注" in raw
        assert "\\u4e2d" not in raw

    def test_returns_none_when_the_write_fails(self, monkeypatch):
        def deny(*args, **kwargs):
            raise OSError("disk full")

        monkeypatch.setattr(dump_mod.tempfile, "mkstemp", deny)

        result = self._raise_and_dump(None, {})

        assert result is None

    def test_returns_none_when_payload_cannot_be_serialized(self, monkeypatch):
        real_dumps = json.dump

        def deny(*args, **kwargs):
            raise TypeError("not serializable")

        monkeypatch.setattr(dump_mod.json, "dump", deny)
        try:
            result = self._raise_and_dump(None, {})
        finally:
            monkeypatch.setattr(dump_mod.json, "dump", real_dumps)

        assert result is None

    def test_closes_its_descriptor_even_when_dump_fails(self, monkeypatch):
        """No fd leak on the failure path."""
        opened = []
        real_mkstemp = dump_mod.tempfile.mkstemp

        def tracking(*args, **kwargs):
            fd, path = real_mkstemp(*args, **kwargs)
            opened.append(fd)
            return fd, path

        monkeypatch.setattr(dump_mod.tempfile, "mkstemp", tracking)

        def deny(*args, **kwargs):
            raise TypeError("not serializable")

        monkeypatch.setattr(dump_mod.json, "dump", deny)

        self._raise_and_dump(None, {})

        for fd in opened:
            with pytest.raises(OSError):
                os.fstat(fd)

    def test_swallows_oserror_when_closing_the_descriptor(self, monkeypatch):
        """os.close failing must not surface as an error."""
        real_close = os.close

        def noisy_close(fd):
            real_close(fd)
            raise OSError("already closed")

        monkeypatch.setattr(dump_mod.os, "close", noisy_close)

        path = self._raise_and_dump(None, {})

        assert path is not None
        assert os.path.isfile(path)
