# -*- coding: utf-8 -*-
"""Unit tests for the WeCom card context helpers.

Covers the metadata / body-text extraction shared by every WeCom card
kind and the ``wecom:``-prefixed routing context builder.  The stream
drain helper (``send_stream_detail``) is exercised through the
tool-guard render tests.
"""
# pylint: disable=protected-access
from __future__ import annotations

from types import SimpleNamespace

import pytest

from qwenpaw.app.channels.wecom.cards import context as wecom_ctx


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


class TestSendStreamDetail:
    class _Client:
        def __init__(self, error=None):
            self.streams = []
            self._error = error

        async def reply_stream(self, frame, *, stream_id, content, finish):
            if self._error is not None:
                raise self._error
            self.streams.append(
                {
                    "frame": frame,
                    "stream_id": stream_id,
                    "content": content,
                    "finish": finish,
                },
            )

    def _channel(self, client=None):
        return SimpleNamespace(
            _client=client if client is not None else self._Client(),
            _keepalive_tasks={},
        )

    async def test_new_stream_id_is_generated(self):
        channel = self._channel()

        await wecom_ctx.send_stream_detail(channel, {"f": 1}, {}, "body")

        stream = channel._client.streams[0]
        assert stream["content"] == "body"
        assert stream["finish"] is True
        assert stream["frame"] == {"f": 1}

    async def test_processing_stream_id_is_reused_and_popped(self):
        channel = self._channel()
        send_meta = {"wecom_processing_stream_id": "sid-1"}

        await wecom_ctx.send_stream_detail(channel, {}, send_meta, "body")

        assert channel._client.streams[0]["stream_id"] == "sid-1"
        assert "wecom_processing_stream_id" not in send_meta

    async def test_stream_failure_is_swallowed(self):
        channel = self._channel(self._Client(error=RuntimeError("down")))

        await wecom_ctx.send_stream_detail(channel, {}, {}, "body")

        assert channel._client.streams == []

    async def test_no_keepalive_entry_is_fine(self):
        channel = self._channel()

        await wecom_ctx.send_stream_detail(
            channel,
            {},
            {"wecom_processing_stream_id": "sid-2"},
            "body",
        )

        assert channel._client.streams[0]["stream_id"] == "sid-2"
