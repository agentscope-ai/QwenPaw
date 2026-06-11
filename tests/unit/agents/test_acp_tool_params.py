# -*- coding: utf-8 -*-
"""The ACP server converts ``stream_query`` envelopes into ACP session
updates via ``_EnvelopeTracker``. A completed ``plugin_call`` envelope must
start the tool call (carrying its name), and the matching
``plugin_call_output`` envelope must complete it (carrying its output).

NOTE: the pre-refactor ``_StreamTracker`` / ``_msg_to_updates`` Msg-snapshot
API (which diffed streamed ``raw_input``) no longer exists — the server is now
driven by ``stream_query`` envelopes, so these tests exercise the current
``_EnvelopeTracker`` envelope-to-update behavior instead.
"""

from __future__ import annotations

from types import SimpleNamespace

from qwenpaw.agents.acp.server import _EnvelopeTracker
from qwenpaw.schemas import MessageType, RunStatus


def _content(data):
    return SimpleNamespace(data=data)


def _plugin_call(call_id, name, status=RunStatus.Completed):
    return SimpleNamespace(
        object="message",
        type=MessageType.PLUGIN_CALL,
        status=status,
        id=call_id,
        content=[_content({"call_id": call_id, "name": name})],
    )


def _plugin_call_output(call_id, output, status=RunStatus.Completed):
    return SimpleNamespace(
        object="message",
        type=MessageType.PLUGIN_CALL_OUTPUT,
        status=status,
        id=call_id,
        content=[_content({"call_id": call_id, "output": output})],
    )


def test_plugin_call_starts_tool_call_with_name():
    tracker = _EnvelopeTracker()
    updates = tracker.process(
        _plugin_call("t1", "execute_shell_command"),
    )
    assert [u.session_update for u in updates] == ["tool_call"]
    start = updates[0]
    assert start.tool_call_id == "t1"
    assert start.title == "execute_shell_command"
    assert start.status == "in_progress"


def test_plugin_call_output_completes_tool_call_with_output():
    tracker = _EnvelopeTracker()
    updates = tracker.process(
        _plugin_call_output("t1", "hello from shell"),
    )
    assert [u.session_update for u in updates] == ["tool_call_update"]
    upd = updates[0]
    assert upd.tool_call_id == "t1"
    assert upd.status == "completed"
    # The tool output is surfaced as a text content block.
    texts = [c.content.text for c in upd.content]
    assert "hello from shell" in texts


def test_non_completed_plugin_call_emits_nothing():
    tracker = _EnvelopeTracker()
    # An in-progress (not yet completed) call produces no update.
    assert not tracker.process(
        _plugin_call("t1", "execute_shell_command", status=None),
    )


def test_unknown_envelope_object_is_ignored():
    tracker = _EnvelopeTracker()
    assert not tracker.process(SimpleNamespace(object="unknown"))
