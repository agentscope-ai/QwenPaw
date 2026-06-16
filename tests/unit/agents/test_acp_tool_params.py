# -*- coding: utf-8 -*-
"""Tool-call arguments stream in, so the first sighting of a call often
carries empty input. The ACP server must emit the populated ``raw_input``
once it arrives (as a follow-up update) rather than pinning the empty
``rawInput`` from the initial ``start`` event."""

from __future__ import annotations

from types import SimpleNamespace

from qwenpaw.agents.acp.server import _StreamTracker, _msg_to_updates


def _msg(tool_calls):
    return SimpleNamespace(
        metadata={"tool_calls": tool_calls},
        content=None,
        role="assistant",
    )


def test_streamed_tool_input_emitted_when_it_arrives():
    tracker = _StreamTracker()
    name = "execute_shell_command"

    # Snapshot 1: tool call appears with empty (still-streaming) args.
    u1 = _msg_to_updates(
        _msg([{"id": "t1", "name": name, "input": {}}]),
        tracker,
    )
    assert [u.session_update for u in u1] == ["tool_call"]
    assert u1[0].raw_input == {}

    # Snapshot 2: arguments finished streaming → follow-up update carries
    # the populated input.
    u2 = _msg_to_updates(
        _msg([{"id": "t1", "name": name, "input": {"command": "echo hi"}}]),
        tracker,
    )
    assert [u.session_update for u in u2] == ["tool_call_update"]
    assert u2[0].raw_input == {"command": "echo hi"}

    # Snapshot 3: unchanged input → nothing re-emitted.
    u3 = _msg_to_updates(
        _msg([{"id": "t1", "name": name, "input": {"command": "echo hi"}}]),
        tracker,
    )
    assert not u3


def test_tool_input_present_on_start_is_not_resent():
    tracker = _StreamTracker()
    args = {"command": "ls"}

    u1 = _msg_to_updates(
        _msg([{"id": "t2", "name": "execute_shell_command", "input": args}]),
        tracker,
    )
    assert [u.session_update for u in u1] == ["tool_call"]
    assert u1[0].raw_input == args

    # Same input on the next snapshot must not produce a redundant update.
    u2 = _msg_to_updates(
        _msg([{"id": "t2", "name": "execute_shell_command", "input": args}]),
        tracker,
    )
    assert not u2
