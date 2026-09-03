# -*- coding: utf-8 -*-
"""Unit tests for the QQ / WeCom card context helpers.

Both channels ship a ``cards/context.py`` with the same two extraction
helpers (``extract_meta`` unwraps the runtime's ``metadata.metadata``
nesting, ``extract_body_text`` flattens message content) plus a
``build_session_ctx`` routing builder.  The QQ helpers are exercised
here; the WeCom ones differ only in the routing keys and are covered by
their own test module.
"""
# pylint: disable=protected-access
from __future__ import annotations

from types import SimpleNamespace

import pytest

from qwenpaw.app.channels.qq.cards import context as qq_ctx


class _Text:
    def __init__(self, text):
        self.text = text


class TestExtractMeta:
    def test_inner_metadata_is_unwrapped(self):
        event = SimpleNamespace(metadata={"metadata": {"a": 1}})

        assert qq_ctx.extract_meta(event) == {"a": 1}

    def test_flat_metadata_is_returned_as_is(self):
        event = SimpleNamespace(metadata={"a": 1})

        assert qq_ctx.extract_meta(event) == {"a": 1}

    def test_non_dict_inner_falls_back_to_the_outer(self):
        event = SimpleNamespace(metadata={"metadata": "nope", "b": 2})

        assert qq_ctx.extract_meta(event) == {"metadata": "nope", "b": 2}

    @pytest.mark.parametrize("metadata", ["string", 42, ["a"]])
    def test_non_dict_metadata_is_rejected(self, metadata):
        assert qq_ctx.extract_meta(SimpleNamespace(metadata=metadata)) is None

    def test_missing_metadata_yields_empty_dict(self):
        assert qq_ctx.extract_meta(SimpleNamespace()) == {}

    def test_none_metadata_yields_empty_dict(self):
        assert qq_ctx.extract_meta(SimpleNamespace(metadata=None)) == {}


class TestExtractBodyText:
    @pytest.mark.parametrize("content", ["", None, [], 0])
    def test_empty_content(self, content):
        assert qq_ctx.extract_body_text(content) == ""

    def test_plain_string_is_returned(self):
        assert qq_ctx.extract_body_text("hello") == "hello"

    @pytest.mark.parametrize("content", [42, {"a": 1}, object()])
    def test_non_list_non_string_is_empty(self, content):
        assert qq_ctx.extract_body_text(content) == ""

    def test_text_objects_are_joined(self):
        assert qq_ctx.extract_body_text([_Text("a"), _Text("b")]) == "ab"

    def test_dict_text_blocks_are_joined(self):
        content = [
            {"type": "text", "text": "x"},
            {"type": "text", "text": "y"},
        ]

        assert qq_ctx.extract_body_text(content) == "xy"

    def test_dict_without_text_key_contributes_empty(self):
        assert qq_ctx.extract_body_text([{"type": "text"}]) == ""

    def test_non_text_dicts_are_skipped(self):
        content = [
            {"type": "image", "url": "u"},
            {"type": "text", "text": "k"},
        ]

        assert qq_ctx.extract_body_text(content) == "k"

    def test_objects_with_empty_text_are_skipped(self):
        assert qq_ctx.extract_body_text([_Text(""), _Text("kept")]) == "kept"

    def test_mixed_shapes_are_flattened_in_order(self):
        content = [_Text("a"), {"type": "text", "text": "b"}, "ignored-str"]

        # A bare string inside a list has no ``.text`` and is not a dict,
        # so it contributes nothing.
        assert qq_ctx.extract_body_text(content) == "ab"


class TestBuildSessionCtx:
    def test_all_fields_are_mapped(self):
        ctx = qq_ctx.build_session_ctx(
            "handle-1",
            {
                "message_type": "group",
                "sender_id": "sender-1",
                "session_id": "session-1",
                "group_openid": "goid-1",
                "channel_id": "cid-1",
                "guild_id": "gid-1",
                "message_id": "msg-1",
            },
        )

        assert ctx == {
            "sid": "session-1",
            "sender": "sender-1",
            "mt": "group",
            "goid": "goid-1",
            "cid": "cid-1",
            "gid": "gid-1",
            "mid": "msg-1",
        }

    def test_handle_fills_a_missing_session_id(self):
        ctx = qq_ctx.build_session_ctx("handle-1", {})

        assert ctx["sid"] == "handle-1"
        assert ctx["mt"] == "c2c"

    def test_explicit_session_id_wins_over_the_handle(self):
        ctx = qq_ctx.build_session_ctx("handle-1", {"session_id": "s-9"})

        assert ctx["sid"] == "s-9"

    def test_missing_send_meta_is_tolerated(self):
        ctx = qq_ctx.build_session_ctx("handle-1", None)

        assert ctx["mt"] == "c2c"
        assert ctx["sender"] == ""

    def test_non_string_values_are_coerced(self):
        ctx = qq_ctx.build_session_ctx("handle-1", {"sender_id": 42})

        assert ctx["sender"] == "42"
