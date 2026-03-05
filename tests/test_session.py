# -*- coding: utf-8 -*-
"""Tests for CallSession and CallSessionManager."""
from unittest.mock import MagicMock

from copaw.app.channels.voice.session import CallSessionManager


class TestCallSessionManager:
    def test_create_session(self):
        mgr = CallSessionManager()
        handler = MagicMock()
        session = mgr.create_session(
            call_sid="CA123",
            handler=handler,
            from_number="+15551234567",
            to_number="+15559876543",
        )
        assert session.call_sid == "CA123"
        assert session.from_number == "+15551234567"
        assert session.status == "active"
        assert mgr.active_count() == 1

    def test_get_session(self):
        mgr = CallSessionManager()
        handler = MagicMock()
        mgr.create_session(call_sid="CA123", handler=handler)
        assert mgr.get_session("CA123") is not None
        assert mgr.get_session("CA999") is None

    def test_end_session(self):
        mgr = CallSessionManager()
        handler = MagicMock()
        mgr.create_session(call_sid="CA123", handler=handler)
        assert mgr.active_count() == 1

        mgr.end_session("CA123")
        assert mgr.active_count() == 0
        assert mgr.get_session("CA123") is None

    def test_active_sessions(self):
        mgr = CallSessionManager()
        h1, h2, h3 = MagicMock(), MagicMock(), MagicMock()
        mgr.create_session(call_sid="CA1", handler=h1)
        mgr.create_session(call_sid="CA2", handler=h2)
        mgr.create_session(call_sid="CA3", handler=h3)

        assert mgr.active_count() == 3
        mgr.end_session("CA2")
        assert mgr.active_count() == 2
        active = mgr.active_sessions()
        active_sids = {s.call_sid for s in active}
        assert active_sids == {"CA1", "CA3"}

    def test_all_sessions(self):
        mgr = CallSessionManager()
        h1, h2 = MagicMock(), MagicMock()
        mgr.create_session(call_sid="CA1", handler=h1)
        mgr.create_session(call_sid="CA2", handler=h2)
        mgr.end_session("CA1")
        assert len(mgr.all_sessions()) == 1
