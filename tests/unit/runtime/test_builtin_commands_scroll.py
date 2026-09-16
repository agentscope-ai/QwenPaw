# -*- coding: utf-8 -*-
"""Tests for the conversation-command adapter's scroll-checkpoint handling.

Pins ``_resolve_scroll_block`` — the rule that keeps the scroll context
manager's persisted bookkeeping consistent with what a command did to the live
window (update on /compact, reset on /clear, preserve otherwise). The prior bug
was that *every* command silently dropped the scroll block.
"""

from types import SimpleNamespace

from qwenpaw.agents.command_handler import ConversationCommandHandlerMixin
from qwenpaw.runtime.builtin_commands import (
    _bind_command_memory_manager,
    _collect_conversation_specs,
    _CONVERSATION_COMMANDS,
    _resolve_scroll_block,
)


def test_conversation_command_binds_trusted_model_authority_and_user():
    calls = []
    bound = object()

    class MemoryManager:
        def for_model_request(self, request_context, authority):
            calls.append((request_context, authority))
            return bound

    authority = object()
    request = SimpleNamespace(user_id="user-a", _model_authority=authority)

    assert _bind_command_memory_manager(
        MemoryManager(),
        request,
        {"conversation_id": "conversation-a"},
    ) is bound
    assert calls == [(
        {"conversation_id": "conversation-a", "user_id": "user-a"},
        authority,
    )]


def test_runtime_registers_every_command_handler_conversation_command():
    assert _CONVERSATION_COMMANDS == (
        ConversationCommandHandlerMixin.SYSTEM_COMMANDS
    )
    assert "reme_status" in {
        spec.name for spec in _collect_conversation_specs()
    }


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
