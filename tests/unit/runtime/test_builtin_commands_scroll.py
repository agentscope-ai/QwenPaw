# -*- coding: utf-8 -*-
"""Tests for the conversation-command adapter's scroll-checkpoint handling.

Pins ``_resolve_scroll_block`` — the rule that keeps the scroll context
manager's persisted bookkeeping consistent with what a command did to the live
window (update on /compact, reset on /clear, preserve otherwise). The prior bug
was that *every* command silently dropped the scroll block.
"""

from qwenpaw.runtime.builtin_commands import _resolve_scroll_block


def test_compact_saves_the_refreshed_block():
    updated = {"tiers": [["block"]]}
    out = _resolve_scroll_block(
        updated=updated,
        context_empty=False,
        existing={"old": True},
    )
    assert out is updated


def test_cleared_context_resets_the_block():
    # /clear, /new empty the window — a stale eviction index must not survive.
    out = _resolve_scroll_block(
        updated=None,
        context_empty=True,
        existing={"tiers": [["old"]]},
    )
    assert out is None


def test_readonly_command_preserves_existing_block():
    # /history, /message, ... must NOT nuke the scroll checkpoint.
    existing = {"persisted_ids": ["a", "b"]}
    out = _resolve_scroll_block(
        updated=None,
        context_empty=False,
        existing=existing,
    )
    assert out is existing


def test_update_wins_even_if_context_empty():
    updated = {"tiers": []}
    out = _resolve_scroll_block(
        updated=updated,
        context_empty=True,
        existing=None,
    )
    assert out is updated


def test_no_existing_block_native_session():
    out = _resolve_scroll_block(
        updated=None,
        context_empty=False,
        existing=None,
    )
    assert out is None
