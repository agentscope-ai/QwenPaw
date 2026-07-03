# -*- coding: utf-8 -*-
from __future__ import annotations

from qwenpaw.app.crons.heartbeat import (
    _extract_message_preview,
    is_cron_expression,
    parse_heartbeat_every,
)


# ---------------------------------------------------------------------------
# is_cron_expression
# ---------------------------------------------------------------------------


def test_is_cron_expression_valid_5_field():
    assert is_cron_expression("0 9 * * 1") is True


def test_is_cron_expression_rejects_non_cron():
    assert is_cron_expression("30m") is False


def test_is_cron_expression_rejects_empty():
    assert is_cron_expression("") is False


def test_is_cron_expression_rejects_4_fields():
    assert is_cron_expression("0 9 * *") is False


def test_is_cron_expression_accepts_named_dow():
    """Named DOW abbreviations (mon–sun) are valid in POSIX cron and
    APScheduler ``CronTrigger``."""
    assert is_cron_expression("0 9 * * mon") is True
    assert is_cron_expression("0 9 * * MON") is True
    assert is_cron_expression("0 9 * * fri") is True


def test_is_cron_expression_accepts_named_dow_range():
    assert is_cron_expression("0 9 * * mon-fri") is True


def test_is_cron_expression_accepts_named_dow_with_step():
    assert is_cron_expression("0 9 * * tue/2") is True
    assert is_cron_expression("0 9 * * mon-fri/2") is True


def test_is_cron_expression_rejects_invalid_named_dow():
    assert is_cron_expression("0 9 * * xyz") is False
    assert is_cron_expression("0 9 * * monday") is False


# ---------------------------------------------------------------------------
# parse_heartbeat_every
# ---------------------------------------------------------------------------


def test_parse_heartbeat_every_minutes():
    assert parse_heartbeat_every("5m") == 300


def test_parse_heartbeat_every_hours():
    assert parse_heartbeat_every("1h") == 3600


def test_parse_heartbeat_every_seconds():
    assert parse_heartbeat_every("30s") == 30


def test_parse_heartbeat_every_combined():
    assert parse_heartbeat_every("1h30m") == 5400


def test_parse_heartbeat_every_empty_defaults_to_30m():
    assert parse_heartbeat_every("") == 1800


def test_parse_heartbeat_every_invalid_defaults_to_30m():
    assert parse_heartbeat_every("bogus") == 1800


# ---------------------------------------------------------------------------
# _extract_message_preview
# ---------------------------------------------------------------------------


def test_extract_message_preview_text_block():
    msg = {
        "content": [
            {"type": "text", "text": "Hello world"},
        ],
    }
    assert _extract_message_preview(msg) == "Hello world"


def test_extract_message_preview_empty_content_returns_none():
    assert _extract_message_preview({"content": []}) is None


def test_extract_message_preview_non_list_content_returns_none():
    assert _extract_message_preview({"content": "not a list"}) is None


def test_extract_message_preview_truncates_long_text():
    long_text = "x" * 5000
    msg = {"content": [{"type": "text", "text": long_text}]}
    result = _extract_message_preview(msg)
    assert result == long_text
