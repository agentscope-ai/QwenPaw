# -*- coding: utf-8 -*-
"""How the ACP server surfaces tool output (including files sent via
``send_file_to_user``) to the client.

NOTE: the pre-refactor behavior of rendering ``send_file_to_user`` output as a
clickable ``resource_link`` tool-call content block — together with the
``_media_block_url`` / ``_tool_result_content`` / ``_extract_tool_output`` /
``_msg_to_updates`` helpers it relied on — no longer exists. The server is now
driven by ``stream_query`` envelopes and renders a ``plugin_call_output`` as a
plain-text tool-call content block via ``_EnvelopeTracker``. These tests cover
the surviving behavior: the tool output text reaches the client. If
``resource_link`` rendering is reintroduced, extend these tests accordingly.
"""

from __future__ import annotations

from types import SimpleNamespace

from qwenpaw.agents.acp.server import _EnvelopeTracker
from qwenpaw.schemas import MessageType, RunStatus


def _plugin_call_output(call_id, output):
    return SimpleNamespace(
        object="message",
        type=MessageType.PLUGIN_CALL_OUTPUT,
        status=RunStatus.Completed,
        id=call_id,
        content=[
            SimpleNamespace(
                data={"call_id": call_id, "output": output},
            ),
        ],
    )


def test_send_file_output_surfaces_as_tool_call_text():
    tracker = _EnvelopeTracker()
    # send_file_to_user reports success as a textual output payload.
    [update] = tracker.process(
        _plugin_call_output(
            "f1",
            "File sent successfully: report.pdf",
        ),
    )
    assert update.session_update == "tool_call_update"
    assert update.tool_call_id == "f1"
    texts = [c.content.text for c in update.content]
    assert any("report.pdf" in t for t in texts)
    # Output is rendered as a readable string, not a raw object repr.
    assert all("SimpleNamespace(" not in t for t in texts)


def test_non_dict_output_data_is_ignored():
    tracker = _EnvelopeTracker()
    env = SimpleNamespace(
        object="message",
        type=MessageType.PLUGIN_CALL_OUTPUT,
        status=RunStatus.Completed,
        id="f2",
        content=[SimpleNamespace(data=None)],
    )
    assert not tracker.process(env)
