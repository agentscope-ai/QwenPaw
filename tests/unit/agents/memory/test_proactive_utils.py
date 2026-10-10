# -*- coding: utf-8 -*-
# pylint: disable=protected-access,unnecessary-lambda,unused-import
"""Unit tests for proactive_utils.py pure helpers.

Coverage-driven backfill (batch 4, coverage-first per the 2026-08-24
instruction: upstream PRs are only considered after backend_unit coverage
rises by at least 5 percentage points). Target: the proactive messaging
utility helpers, which previously sat at ~9% coverage.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from agentscope.message import Msg, TextBlock

from qwenpaw.agents.memory.proactive import proactive_utils as pu


# ---------------------------------------------------------------------------
# ensure_tz_aware
# ---------------------------------------------------------------------------


class TestEnsureTzAware:
    def test_naive_becomes_utc(self):
        naive = datetime(2026, 1, 1, 12, 0)
        aware = pu.ensure_tz_aware(naive)
        assert aware.tzinfo == timezone.utc

    def test_aware_unchanged(self):
        aware = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        assert pu.ensure_tz_aware(aware) == aware


# ---------------------------------------------------------------------------
# is_agent_busy
# ---------------------------------------------------------------------------


class TestIsAgentBusy:
    async def test_busy_when_active_tasks(self):
        tracker = SimpleNamespace(
            has_active_tasks=lambda: _async_true(),
        )
        workspace = SimpleNamespace(task_tracker=tracker)
        assert await pu.is_agent_busy(workspace) is True

    async def test_not_busy_without_tracker(self):
        workspace = SimpleNamespace(task_tracker=None)
        assert await pu.is_agent_busy(workspace) is False

    async def test_error_returns_false(self):
        async def boom():
            raise RuntimeError("tracker down")

        workspace = SimpleNamespace(
            task_tracker=SimpleNamespace(has_active_tasks=boom),
        )
        assert await pu.is_agent_busy(workspace) is False


async def _async_true():
    return True


# ---------------------------------------------------------------------------
# load_json_safely
# ---------------------------------------------------------------------------


class TestLoadJsonSafely:
    def test_plain_json(self):
        assert pu.load_json_safely('{"a": 1}') == {"a": 1}

    def test_json_code_block(self):
        assert pu.load_json_safely('```json\n{"a": 1}\n```') == {"a": 1}

    def test_plain_code_block(self):
        assert pu.load_json_safely('```\n{"a": 1}\n```') == {"a": 1}

    def test_embedded_object(self):
        raw = 'prefix {"a": {"b": 2}} suffix'
        assert pu.load_json_safely(raw) == {"a": {"b": 2}}

    def test_invalid_returns_none(self):
        assert pu.load_json_safely("not json at all") is None

    def test_non_string_returns_none(self):
        assert pu.load_json_safely(123) is None

    def test_broken_braces_returns_none(self):
        assert pu.load_json_safely("{broken") is None


# ---------------------------------------------------------------------------
# extract_content
# ---------------------------------------------------------------------------


class TestExtractContent:
    def test_string_passthrough(self):
        assert pu.extract_content("hello") == "hello"

    def test_block_list_joined(self):
        blocks = [TextBlock(type="text", text="a"), {"other": 1}]
        out = pu.extract_content(blocks)
        assert "a" in out

    def test_non_string_coerced(self):
        assert pu.extract_content(42) == "42"


# ---------------------------------------------------------------------------
# _clean_message_content
# ---------------------------------------------------------------------------


class TestCleanMessageContent:
    def _msg(self, role, content):
        # Msg validates block types strictly; the cleaner only reads
        # .role/.content, so a plain namespace is sufficient.
        return SimpleNamespace(role=role, content=content)

    def test_system_message_dropped(self):
        msg = self._msg("system", [TextBlock(type="text", text="x")])
        assert pu._clean_message_content(msg) is None

    def test_text_blocks_kept(self):
        msg = self._msg("user", [TextBlock(type="text", text="hi")])
        cleaned = pu._clean_message_content(msg)
        assert cleaned is not None
        assert len(cleaned.content) == 1

    def test_non_text_blocks_dropped(self):
        msg = self._msg("user", [{"type": "image", "url": "x"}])
        assert pu._clean_message_content(msg) is None

    def test_plain_string_content_dropped(self):
        # content is a list containing a non-block item
        msg = self._msg("user", ["plain string"])
        assert pu._clean_message_content(msg) is None

    def test_block_object_with_type_attr_kept(self):
        block = SimpleNamespace(type="text", text="obj")
        msg = self._msg("user", [block])
        cleaned = pu._clean_message_content(msg)
        assert cleaned is not None


# ---------------------------------------------------------------------------
# _filter_recent_sessions
# ---------------------------------------------------------------------------


class TestFilterRecentSessions:
    def _session(self, name: str, days_ago: float) -> dict:
        return {
            "session_id": name,
            "user_id": "u",
            "mod_time": datetime.now(timezone.utc) - timedelta(days=days_ago),
        }

    def test_recent_only_kept_when_enough(self):
        # Provide ≥5 recent sessions so the fallback (top-5) is not used.
        sessions = [self._session(f"new{i}", 1) for i in range(6)]
        sessions.append(self._session("old", 30))
        result = pu._filter_recent_sessions(sessions, days=7)
        ids = [s["session_id"] for s in result]
        assert "old" not in ids
        assert len(ids) == 6

    def test_fallback_to_top_five(self):
        sessions = [self._session(f"s{i}", 100) for i in range(8)]
        result = pu._filter_recent_sessions(sessions, days=7)
        assert len(result) == 5

    def test_sorted_desc_by_mod_time(self):
        sessions = [
            self._session("a", 2),
            self._session("b", 1),
            self._session("c", 3),
            self._session("d", 4),
            self._session("e", 5),
        ]
        result = pu._filter_recent_sessions(sessions, days=7)
        assert [s["session_id"] for s in result] == ["b", "a", "c", "d", "e"]


# ---------------------------------------------------------------------------
# _format_session_messages
# ---------------------------------------------------------------------------


class TestFormatSessionMessages:
    def _msg(self, role: str, text: str, ts: float) -> dict:
        return {
            "message": Msg(
                name=role,
                role=role,
                content=[TextBlock(type="text", text=text)],
            ),
            "timestamp": ts,
        }

    def test_formats_newest_first(self):
        messages = [
            self._msg("user", "first", 1.0),
            self._msg("assistant", "second", 2.0),
        ]
        out = pu._format_session_messages(messages)
        assert "[user]: first" in out
        assert "[assistant]: second" in out

    def test_proactive_helper_skipped(self):
        messages = [
            self._msg("user", "[Agent proactive_helper requesting] x", 1.0),
            self._msg("user", "real", 2.0),
        ]
        out = pu._format_session_messages(messages)
        assert "proactive_helper" not in out
        assert "real" in out

    def test_max_messages_limit(self):
        messages = [self._msg("user", f"m{i}", float(i)) for i in range(10)]
        out = pu._format_session_messages(messages, max_messages=3)
        assert out.count("[user]:") == 3

    def test_char_limit_stops_early(self):
        messages = [self._msg("user", "x" * 100, float(i)) for i in range(20)]
        out = pu._format_session_messages(messages, max_chars=200)
        assert len(out) <= 300

    def test_empty_list(self):
        assert pu._format_session_messages([]).strip() == ""


# ---------------------------------------------------------------------------
# get_last_message_ts
# ---------------------------------------------------------------------------


class TestGetLastMessageTs:
    async def test_none_workspace(self):
        assert await pu.get_last_message_ts(None) is None

    async def test_returns_latest_timestamp(self):
        older = datetime(2026, 1, 1, tzinfo=timezone.utc)
        newer = datetime(2026, 6, 1, tzinfo=timezone.utc)

        async def list_chats():
            return [
                SimpleNamespace(updated_at=older),
                SimpleNamespace(updated_at=newer),
            ]

        workspace = SimpleNamespace(
            chat_manager=SimpleNamespace(list_chats=list_chats),
        )
        ts = await pu.get_last_message_ts(workspace)
        assert ts == newer.timestamp()

    async def test_naive_updated_at_handled(self):
        async def list_chats():
            return [SimpleNamespace(updated_at=datetime(2026, 1, 1, 12))]

        workspace = SimpleNamespace(
            chat_manager=SimpleNamespace(list_chats=list_chats),
        )
        ts = await pu.get_last_message_ts(workspace)
        assert ts is not None

    async def test_error_returns_none(self):
        async def boom():
            raise RuntimeError("down")

        workspace = SimpleNamespace(
            chat_manager=SimpleNamespace(list_chats=boom),
        )
        assert await pu.get_last_message_ts(workspace) is None
