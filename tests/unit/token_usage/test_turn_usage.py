# -*- coding: utf-8 -*-
"""Tests for per-turn token usage helpers.

Covers fmt_tokens, reconcile_turn_completion_from_stats,
_turn_from_stats, find_turn_closing_assistant_in_context,
_write_turn_usage_meta, and _load_agent_state, which previously had no
dedicated coverage.
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from qwenpaw.token_usage import turn_usage as tu


# ---------------------------------------------------------------------------
# fmt_tokens
# ---------------------------------------------------------------------------


class TestFmtTokens:
    def test_below_thousand_plain(self):
        assert tu.fmt_tokens(999) == "999"
        assert tu.fmt_tokens(0) == "0"

    def test_at_and_above_thousand_uses_k(self):
        assert tu.fmt_tokens(1000) == "1.0K"
        assert tu.fmt_tokens(1500) == "1.5K"
        assert tu.fmt_tokens(123456) == "123.5K"


# ---------------------------------------------------------------------------
# reconcile_turn_completion_from_stats
# ---------------------------------------------------------------------------


class TestReconcileTurnCompletion:
    def test_under_reported_completion_patched(self):
        turn = {"prompt_tokens": 100, "completion_tokens": 1, "total_tokens": 101}
        stats = {"latest_assistant_tokens": 50}
        result = tu.reconcile_turn_completion_from_stats(turn, stats)
        assert result["completion_tokens"] == 50
        assert result["total_tokens"] == 150
        assert result["estimated"] is True
        assert result["prompt_tokens"] == 100

    def test_zero_completion_patched(self):
        turn = {"prompt_tokens": 10, "completion_tokens": 0, "total_tokens": 10}
        stats = {"latest_assistant_tokens": 20}
        result = tu.reconcile_turn_completion_from_stats(turn, stats)
        assert result["completion_tokens"] == 20

    def test_actual_higher_than_estimate_untouched(self):
        turn = {"prompt_tokens": 10, "completion_tokens": 100, "total_tokens": 110}
        stats = {"latest_assistant_tokens": 50}
        result = tu.reconcile_turn_completion_from_stats(turn, stats)
        assert result == turn  # unchanged

    def test_zero_estimate_untouched(self):
        turn = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
        stats = {"latest_assistant_tokens": 0}
        result = tu.reconcile_turn_completion_from_stats(turn, stats)
        assert result == turn

    def test_missing_completion_treated_as_zero(self):
        turn = {"prompt_tokens": 10}
        stats = {"latest_assistant_tokens": 30}
        result = tu.reconcile_turn_completion_from_stats(turn, stats)
        assert result["completion_tokens"] == 30


# ---------------------------------------------------------------------------
# _turn_from_stats
# ---------------------------------------------------------------------------


class TestTurnFromStats:
    def test_positive_estimated_builds_turn(self):
        stats = {"estimated_tokens": 100, "latest_assistant_tokens": 30}
        result = tu._turn_from_stats(stats)
        assert result is not None
        assert result["total_tokens"] == 100
        assert result["completion_tokens"] == 30
        assert result["prompt_tokens"] == 70
        assert result["estimated"] is True

    def test_assistant_larger_than_est_clamped_to_zero(self):
        stats = {"estimated_tokens": 10, "latest_assistant_tokens": 50}
        result = tu._turn_from_stats(stats)
        assert result["prompt_tokens"] == 0

    def test_zero_estimated_returns_none(self):
        assert tu._turn_from_stats({"estimated_tokens": 0}) is None

    def test_missing_estimated_returns_none(self):
        assert tu._turn_from_stats({}) is None


# ---------------------------------------------------------------------------
# find_turn_closing_assistant_in_context
# ---------------------------------------------------------------------------


class TestFindTurnClosingAssistant:
    def test_assistant_after_user_returned(self):
        msgs = [
            SimpleNamespace(role="user"),
            SimpleNamespace(role="assistant", marker="a1"),
        ]
        assert tu.find_turn_closing_assistant_in_context(msgs).marker == "a1"

    def test_last_assistant_returned(self):
        msgs = [
            SimpleNamespace(role="user"),
            SimpleNamespace(role="assistant", marker="a1"),
            SimpleNamespace(role="assistant", marker="a2"),
        ]
        assert tu.find_turn_closing_assistant_in_context(msgs).marker == "a2"

    def test_user_at_end_returns_none(self):
        msgs = [
            SimpleNamespace(role="assistant"),
            SimpleNamespace(role="user"),
        ]
        assert tu.find_turn_closing_assistant_in_context(msgs) is None

    def test_empty_returns_none(self):
        assert tu.find_turn_closing_assistant_in_context([]) is None

    def test_none_returns_none(self):
        assert tu.find_turn_closing_assistant_in_context(None) is None

    def test_stops_at_user(self):
        msgs = [
            SimpleNamespace(role="user"),
            SimpleNamespace(role="assistant", marker="early"),
            SimpleNamespace(role="user"),
        ]
        # The assistant before the latest user is NOT after it -> None
        assert tu.find_turn_closing_assistant_in_context(msgs) is None


# ---------------------------------------------------------------------------
# _write_turn_usage_meta
# ---------------------------------------------------------------------------


class TestWriteTurnUsageMeta:
    def test_writes_meta_onto_existing_dict(self):
        msg = SimpleNamespace(metadata={})
        ok = tu._write_turn_usage_meta(msg, {"total_tokens": 5}, None)
        assert ok is True
        assert msg.metadata[tu.TURN_USAGE_META_KEY]["usage"]["total_tokens"] == 5
        assert msg.metadata[tu.TURN_USAGE_META_KEY]["context_usage"] is None

    def test_creates_metadata_when_missing(self):
        msg = SimpleNamespace(metadata=None)
        ok = tu._write_turn_usage_meta(msg, None, {"estimated_tokens": 9})
        assert ok is True
        assert msg.metadata[tu.TURN_USAGE_META_KEY]["context_usage"]["estimated_tokens"] == 9

    def test_none_msg_returns_false(self):
        assert tu._write_turn_usage_meta(None, {"a": 1}, None) is False

    def test_both_none_returns_false(self):
        msg = SimpleNamespace(metadata={})
        assert tu._write_turn_usage_meta(msg, None, None) is False

    def test_non_dict_metadata_replaced(self):
        msg = SimpleNamespace(metadata="garbage")
        ok = tu._write_turn_usage_meta(msg, {"total_tokens": 1}, None)
        assert ok is True
        assert isinstance(msg.metadata, dict)


# ---------------------------------------------------------------------------
# _load_agent_state
# ---------------------------------------------------------------------------


class TestLoadAgentState:
    async def test_missing_state_returns_none(self):
        session = SimpleNamespace(
            get_session_state_dict=AsyncMock(return_value=None),
        )
        result = await tu._load_agent_state(
            session=session,
            session_id="s",
            user_id="u",
            channel="console",
        )
        assert result is None

    async def test_session_exception_returns_none(self):
        session = SimpleNamespace(
            get_session_state_dict=AsyncMock(side_effect=RuntimeError("boom")),
        )
        result = await tu._load_agent_state(
            session=session,
            session_id="s",
            user_id="u",
            channel="console",
        )
        assert result is None

    async def test_no_agent_state_key_returns_none(self):
        session = SimpleNamespace(
            get_session_state_dict=AsyncMock(return_value={"agent": {}}),
        )
        result = await tu._load_agent_state(
            session=session,
            session_id="s",
            user_id="u",
            channel="console",
        )
        assert result is None

    async def test_non_dict_state_returns_none(self):
        session = SimpleNamespace(
            get_session_state_dict=AsyncMock(
                return_value={"agent": {"state": "not-a-dict"}},
            ),
        )
        result = await tu._load_agent_state(
            session=session,
            session_id="s",
            user_id="u",
            channel="console",
        )
        assert result is None

    async def test_valid_agent_state_parsed(self):
        session = SimpleNamespace(
            get_session_state_dict=AsyncMock(
                return_value={"agent": {"state": {"context": []}}},
            ),
        )
        result = await tu._load_agent_state(
            session=session,
            session_id="s",
            user_id="u",
            channel="console",
        )
        assert result is not None
        assert list(result.context) == []
