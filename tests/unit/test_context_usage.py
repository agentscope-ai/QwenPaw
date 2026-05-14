# -*- coding: utf-8 -*-
"""Tests for context usage snapshots."""

from qwenpaw.context_usage import (
    clear_context_usage,
    pop_context_usage_for_session,
    record_context_usage,
)


def test_context_usage_pop_removes_snapshot():
    """Stored snapshots should be returned once and then cleared."""
    clear_context_usage()

    usage = record_context_usage(
        "session-1",
        total_tokens=3200,
        max_input_length=128000,
        total_messages=7,
    )

    assert usage == {
        "total_tokens": 3200,
        "max_input_length": 128000,
        "pct": 2.5,
        "total_messages": 7,
    }
    assert pop_context_usage_for_session("session-1") == usage
    assert pop_context_usage_for_session("session-1") is None


def test_context_usage_handles_zero_context_window():
    """Invalid token counts should be normalized without division errors."""
    clear_context_usage()

    usage = record_context_usage(
        "session-2",
        total_tokens=-10,
        max_input_length=0,
    )

    assert usage == {
        "total_tokens": 0,
        "max_input_length": 0,
        "pct": 0.0,
    }
