# -*- coding: utf-8 -*-
"""Tests for BaseChannel message-ID deduplication."""

import pytest

from copaw.app.channels.base import BaseChannel


class _StubChannel(BaseChannel):
    """Minimal concrete subclass for testing."""

    channel = "stub"

    def __init__(self):
        super().__init__(process=_noop_process)

    @classmethod
    def from_env(cls, process, on_reply_sent=None):
        return cls()

    @classmethod
    def from_config(cls, process, config, on_reply_sent=None):
        return cls()

    def resolve_session_id(self, payload):
        return "test-session"

    def build_agent_request_from_native(self, native_payload):
        return None


async def _noop_process(req):
    yield  # pragma: no cover


class TestMessageDedup:
    """Base-level message deduplication."""

    def test_first_message_not_duplicate(self):
        ch = _StubChannel()
        payload = {"message_id": "msg_001", "text": "hello"}
        assert ch.is_duplicate(payload) is False

    def test_same_id_is_duplicate(self):
        ch = _StubChannel()
        payload = {"message_id": "msg_001", "text": "hello"}
        assert ch.is_duplicate(payload) is False
        assert ch.is_duplicate(payload) is True

    def test_different_ids_not_duplicate(self):
        ch = _StubChannel()
        assert ch.is_duplicate({"message_id": "msg_001"}) is False
        assert ch.is_duplicate({"message_id": "msg_002"}) is False

    def test_no_id_skips_dedup(self):
        ch = _StubChannel()
        payload = {"text": "no id here"}
        # Without a message_id, dedup should be skipped (not duplicate)
        assert ch.is_duplicate(payload) is False
        assert ch.is_duplicate(payload) is False  # still not duplicate

    def test_dedup_disabled(self):
        ch = _StubChannel()
        ch._dedup_enabled = False
        payload = {"message_id": "msg_001"}
        assert ch.is_duplicate(payload) is False
        assert ch.is_duplicate(payload) is False  # always passes

    def test_dedup_evicts_old_entries(self):
        ch = _StubChannel()
        ch._dedup_max = 3
        for i in range(5):
            ch.is_duplicate({"message_id": f"msg_{i:03d}"})
        # After 5 inserts with max=3, msg_000 and msg_001 should be evicted
        assert ch.is_duplicate({"message_id": "msg_000"}) is False
        assert ch.is_duplicate({"message_id": "msg_001"}) is False
        # msg_004 should still be there
        assert ch.is_duplicate({"message_id": "msg_004"}) is True

    def test_extract_message_id_from_meta(self):
        ch = _StubChannel()
        payload = {"meta": {"message_id": "meta_id_001"}, "text": "hello"}
        assert ch.is_duplicate(payload) is False
        assert ch.is_duplicate(payload) is True

    def test_extract_message_id_prefers_top_level(self):
        ch = _StubChannel()
        payload = {
            "message_id": "top_level",
            "meta": {"message_id": "meta_level"},
        }
        assert ch.is_duplicate(payload) is False
        # Same top-level id should be duplicate
        assert ch.is_duplicate({"message_id": "top_level"}) is True
        # Meta-level id should not match (different extraction path)
        assert ch.is_duplicate({"meta": {"message_id": "meta_level"}}) is False
