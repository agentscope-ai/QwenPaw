# -*- coding: utf-8 -*-
"""Unit tests for ``qwenpaw.app.crons.heartbeat`` helpers.

Covers:
- ``is_cron_expression`` — 5-field detection including named DOW support
- ``parse_heartbeat_every`` — interval string parsing
- ``_extract_message_preview`` — content block extraction
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument
from __future__ import annotations

from qwenpaw.app.crons.heartbeat import (
    _extract_message_preview,
    is_cron_expression,
    parse_heartbeat_every,
)


# ---------------------------------------------------------------------------
# is_cron_expression
# ---------------------------------------------------------------------------


class TestIsCronExpression:
    """Tests for ``is_cron_expression``."""

    @staticmethod
    def test_numeric_cron():
        assert is_cron_expression("0 9 * * *") is True
        assert is_cron_expression("0 9 * * 1") is True
        assert is_cron_expression("0 9 1,15 * 1-5") is True

    @staticmethod
    def test_named_dow_accepted():
        """Named DOW abbreviations (mon–sun) are valid in POSIX cron and
        APScheduler ``CronTrigger``."""
        assert is_cron_expression("0 9 * * mon") is True
        assert is_cron_expression("0 9 * * MON") is True
        assert is_cron_expression("0 9 * * fri") is True

    @staticmethod
    def test_named_dow_range_accepted():
        """Named DOW ranges like ``mon-fri`` are valid cron expressions."""
        assert is_cron_expression("0 9 * * mon-fri") is True
        assert is_cron_expression("0 9 * * tue-sat") is True

    @staticmethod
    def test_named_dow_with_step():
        """Named DOW with step values like ``tue/2`` are valid."""
        assert is_cron_expression("0 9 * * tue/2") is True
        assert is_cron_expression("0 9 * * mon-thu/2") is True

    @staticmethod
    def test_named_dow_range_with_step():
        assert is_cron_expression("0 9 * * mon-fri/2") is True

    @staticmethod
    def test_invalid_named_dow_rejected():
        assert is_cron_expression("0 9 * * xyz") is False

    @staticmethod
    def test_full_dow_name_rejected():
        """Full weekday names (e.g. ``monday``) are not valid 3-letter
        cron abbreviations."""
        assert is_cron_expression("0 9 * * monday") is False

    @staticmethod
    def test_interval_string_not_cron():
        assert is_cron_expression("30m") is False
        assert is_cron_expression("1h") is False

    @staticmethod
    def test_wrong_field_count():
        assert is_cron_expression("0 9 * * * extra") is False
        assert is_cron_expression("0 9 * *") is False

    @staticmethod
    def test_empty_and_none():
        assert is_cron_expression("") is False
        assert is_cron_expression(None) is False

    @staticmethod
    def test_4_field_cron_rejected():
        """4-field cron (minute hour day month, no DOW) is NOT accepted."""
        assert is_cron_expression("0 9 * *") is False


# ---------------------------------------------------------------------------
# parse_heartbeat_every
# ---------------------------------------------------------------------------


class TestParseHeartbeatEvery:
    @staticmethod
    def test_minutes():
        assert parse_heartbeat_every("30m") == 30 * 60

    @staticmethod
    def test_hours():
        assert parse_heartbeat_every("1h") == 3600

    @staticmethod
    def test_combined():
        assert parse_heartbeat_every("2h30m") == 2 * 3600 + 30 * 60

    @staticmethod
    def test_seconds():
        assert parse_heartbeat_every("90s") == 90

    @staticmethod
    def test_default_on_empty():
        assert parse_heartbeat_every("") == 30 * 60
        assert parse_heartbeat_every(None) == 30 * 60

    @staticmethod
    def test_default_on_invalid():
        assert parse_heartbeat_every("invalid") == 30 * 60


# ---------------------------------------------------------------------------
# _extract_message_preview
# ---------------------------------------------------------------------------


class TestExtractMessagePreview:
    @staticmethod
    def test_extracts_text_blocks():
        msg = {
            "content": [
                {"type": "text", "text": "Hello"},
                {"type": "text", "text": "World"},
            ],
        }
        assert _extract_message_preview(msg) == "Hello\nWorld"

    @staticmethod
    def test_includes_thinking_blocks():
        msg = {
            "content": [
                {"type": "thinking", "thinking": "Let me think..."},
                {"type": "text", "text": "Answer"},
            ],
        }
        assert _extract_message_preview(msg) == "Let me think...\nAnswer"

    @staticmethod
    def test_includes_tool_result_text():
        msg = {
            "content": [
                {
                    "type": "tool_result",
                    "output": [{"type": "text", "text": "Tool output"}],
                },
            ],
        }
        assert _extract_message_preview(msg) == "Tool output"

    @staticmethod
    def test_non_list_content_returns_none():
        assert _extract_message_preview({"content": "plain string"}) is None
        assert _extract_message_preview({"content": 42}) is None

    @staticmethod
    def test_empty_text_returns_none():
        msg = {"content": [{"type": "text", "text": "   "}]}
        assert _extract_message_preview(msg) is None

    @staticmethod
    def test_image_block_skipped():
        msg = {
            "content": [
                {"type": "image", "url": "https://x.png"},
                {"type": "text", "text": "Caption"},
            ],
        }
        assert _extract_message_preview(msg) == "Caption"