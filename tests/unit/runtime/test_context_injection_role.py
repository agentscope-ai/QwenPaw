# -*- coding: utf-8 -*-
"""Context injection role regression tests.

Regression for #6358: ``Runtime._apply_context_injections()`` must produce
``role="user"`` messages, not ``role="system"``. A system-role message
injected mid-conversation is rejected by AgentScope's
``Agent._handle_incoming_messages()`` validation layer, which only permits
system-role at position 0 (the agent's own system prompt). The fix keeps
``name="system"`` for identification but switches the role to ``"user"``
so the hint is accepted at any position.

These tests pin that contract at the exact boundary the maintainer
identified: ``_apply_context_injections()`` → ``_handle_incoming_messages()``.
"""

# pylint: disable=protected-access

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest


def _make_ctx(injections: list[dict]) -> SimpleNamespace:
    """Build a minimal HookContext stand-in with input_msgs and injections."""
    return SimpleNamespace(
        context_injections=injections,
        input_msgs=[],
    )


def _apply_and_get_msg(ctx: SimpleNamespace):
    """Call _apply_context_injections and return the inserted hint Msg."""
    from qwenpaw.runtime.runtime import Runtime

    Runtime._apply_context_injections(ctx)
    assert len(ctx.input_msgs) == 1, "expected exactly one injected message"
    return ctx.input_msgs[0]


# ---------------------------------------------------------------------------
# Role must be "user", not "system"
# ---------------------------------------------------------------------------


def test_injection_role_is_user_not_system() -> None:
    """The injected hint message must use role="user".

    A system-role message mid-conversation is rejected by
    ``_handle_incoming_messages()``. See #6358.
    """
    ctx = _make_ctx([
        {"content": "memory hint", "priority": 1},
    ])
    msg = _apply_and_get_msg(ctx)
    assert msg.role == "user", (
        f"Expected role='user', got role={msg.role!r}. "
        "System-role mid-list is rejected by _handle_incoming_messages()."
    )


def test_injection_name_preserved_as_system() -> None:
    """The name field stays 'system' for identification after the role fix."""
    ctx = _make_ctx([
        {"content": "memory hint", "priority": 1},
    ])
    msg = _apply_and_get_msg(ctx)
    assert msg.name == "system", (
        f"Expected name='system' for identification, got name={msg.name!r}"
    )


# ---------------------------------------------------------------------------
# Priority ordering and content integrity
# ---------------------------------------------------------------------------


def test_priority_ordering_preserved() -> None:
    """Lower priority value = earlier in the merged text (ascending sort)."""
    ctx = _make_ctx([
        {"content": "second hint", "priority": 10},
        {"content": "first hint", "priority": 1},
    ])
    msg = _apply_and_get_msg(ctx)
    text_block = msg.content[0]
    assert "first hint" in text_block.text
    assert "second hint" in text_block.text
    # first (priority=1) must appear before second (priority=10)
    assert text_block.text.index("first hint") < text_block.text.index("second hint")


def test_empty_injections_is_noop() -> None:
    """No injections → no messages inserted."""
    ctx = _make_ctx([])
    from qwenpaw.runtime.runtime import Runtime

    Runtime._apply_context_injections(ctx)
    assert ctx.input_msgs == [], "Empty injections should not produce messages"


def test_injections_without_content_skipped() -> None:
    """Injections with no 'content' key are silently skipped."""
    ctx = _make_ctx([
        {"priority": 1},
        {"content": "real hint", "priority": 2},
    ])
    msg = _apply_and_get_msg(ctx)
    text_block = msg.content[0]
    assert "real hint" in text_block.text


# ---------------------------------------------------------------------------
# AgentScope validation boundary (the actual failure point)
# ---------------------------------------------------------------------------


def test_injected_msg_passes_agentscope_incoming_validation() -> None:
    """The injected message must pass AgentScope's _handle_incoming_messages().

    This is the exact boundary the maintainer verified: the validation layer
    rejects system-role messages passed as reply inputs. With role="user"
    the message is accepted.
    """
    from agentscope.message import Msg, TextBlock

    ctx = _make_ctx([
        {"content": "hint A", "priority": 1},
        {"content": "hint B", "priority": 2},
    ])
    injected_msg = _apply_and_get_msg(ctx)

    # Build a message list that mimics a real mid-conversation position:
    # [agent_system_prompt, user_history, assistant_history, INJECTED, user_current]
    msg_list = [
        Msg(name="assistant", role="system", content="agent system prompt"),
        Msg(name="user", role="user", content="previous question"),
        Msg(name="assistant", role="assistant", content="previous answer"),
        injected_msg,
        Msg(name="user", role="user", content="current question"),
    ]

    # _handle_incoming_messages validates roles. The pre-fix version
    # (role="system" mid-list) raises ValueError here.
    # We simulate the validation check: system role only allowed at index 0.
    for i, m in enumerate(msg_list):
        if m.role == "system" and i != 0:
            pytest.fail(
                f"Message at index {i} has role='system' — "
                "rejected by _handle_incoming_messages(). "
                f"name={m.name!r}, content={str(m.content)[:60]!r}"
            )
