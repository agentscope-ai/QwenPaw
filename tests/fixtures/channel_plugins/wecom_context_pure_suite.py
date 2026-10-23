# -*- coding: utf-8 -*-
"""Unit tests for the WeCom card context helpers.

Covers the metadata / body-text extraction shared by every WeCom card
kind and the ``wecom:``-prefixed routing context builder.  The stream
drain helper (``send_stream_detail``) is exercised through the
tool-guard render tests.
"""
# pylint: disable=protected-access
from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "plugins/channel/wecom"))

from types import SimpleNamespace

import pytest

from qwenpaw_channel_wecom.cards import context as wecom_ctx


class _Text:
    def __init__(self, text):
        self.text = text


class TestExtractMeta:
    def test_inner_metadata_is_unwrapped(self):
        event = SimpleNamespace(metadata={"metadata": {"a": 1}})

        assert wecom_ctx.extract_meta(event) == {"a": 1}

    def test_flat_metadata_is_returned_as_is(self):
        event = SimpleNamespace(metadata={"a": 1})

        assert wecom_ctx.extract_meta(event) == {"a": 1}

    def test_non_dict_inner_falls_back_to_the_outer(self):
        event = SimpleNamespace(metadata={"metadata": 7, "b": 2})

        assert wecom_ctx.extract_meta(event) == {"metadata": 7, "b": 2}

    @pytest.mark.parametrize("metadata", ["string", 42, ["a"]])
    def test_non_dict_metadata_is_rejected(self, metadata):
        event = SimpleNamespace(metadata=metadata)

        assert wecom_ctx.extract_meta(event) is None

    def test_missing_metadata_yields_empty_dict(self):
        assert wecom_ctx.extract_meta(SimpleNamespace()) == {}

    def test_none_metadata_yields_empty_dict(self):
        assert wecom_ctx.extract_meta(SimpleNamespace(metadata=None)) == {}


class TestExtractBodyText:
    @pytest.mark.parametrize("content", ["", None, [], 0])
    def test_empty_content(self, content):
        assert wecom_ctx.extract_body_text(content) == ""

    def test_plain_string_is_returned(self):
        assert wecom_ctx.extract_body_text("hello") == "hello"

    @pytest.mark.parametrize("content", [42, {"a": 1}, object()])
    def test_non_list_non_string_is_empty(self, content):
        assert wecom_ctx.extract_body_text(content) == ""

    def test_text_objects_are_joined(self):
        assert wecom_ctx.extract_body_text([_Text("a"), _Text("b")]) == "ab"

    def test_dict_text_blocks_are_joined(self):
        content = [
            {"type": "text", "text": "x"},
            {"type": "text", "text": "y"},
        ]

        assert wecom_ctx.extract_body_text(content) == "xy"

    def test_dict_without_text_key_contributes_empty(self):
        assert wecom_ctx.extract_body_text([{"type": "text"}]) == ""

    def test_non_text_dicts_are_skipped(self):
        content = [
            {"type": "image", "url": "u"},
            {"type": "text", "text": "k"},
        ]

        assert wecom_ctx.extract_body_text(content) == "k"

    def test_objects_with_empty_text_are_skipped(self):
        content = [_Text(""), _Text("kept")]

        assert wecom_ctx.extract_body_text(content) == "kept"


class TestBuildSessionCtx:
    def test_prefixed_handle_becomes_the_session_id(self):
        ctx = wecom_ctx.build_session_ctx(
            "wecom:session-1",
            {
                "wecom_sender_id": "sender-1",
                "wecom_chatid": "chat-1",
                "wecom_chat_type": "group",
            },
        )

        assert ctx == {
            "session_id": "wecom:session-1",
            "sender_id": "sender-1",
            "chatid": "chat-1",
            "chat_type": "group",
        }

    def test_unprefixed_handle_yields_no_session(self):
        ctx = wecom_ctx.build_session_ctx("plain-handle", {})

        assert ctx["session_id"] == ""
        assert ctx["chat_type"] == "single"

    @pytest.mark.parametrize("handle", ["", None, "   ", "  wecom:s1  "])
    def test_blank_or_padded_handles(self, handle):
        ctx = wecom_ctx.build_session_ctx(handle, {})

        if isinstance(handle, str) and handle.strip().startswith("wecom:"):
            assert ctx["session_id"] == handle.strip()
        else:
            assert ctx["session_id"] == ""

    def test_empty_send_meta_yields_blank_routing(self):
        """Unlike the QQ helper, no ``send_meta or {}`` guard exists here.

        The signature promises a dict and the only caller (``render``)
        always passes one, so an empty dict is the meaningful floor.
        """
        ctx = wecom_ctx.build_session_ctx("wecom:s1", {})

        assert ctx["sender_id"] == ""
        assert ctx["chatid"] == ""
        assert ctx["chat_type"] == "single"

    def test_none_send_meta_is_not_tolerated(self):
        """Documents the asymmetry with the QQ helper (no ``or {}``)."""
        with pytest.raises(AttributeError):
            wecom_ctx.build_session_ctx("wecom:s1", None)

    def test_non_string_values_are_coerced(self):
        ctx = wecom_ctx.build_session_ctx(
            "wecom:s1",
            {"wecom_sender_id": 42, "wecom_chatid": 7},
        )

        assert ctx["sender_id"] == "42"
        assert ctx["chatid"] == "7"
