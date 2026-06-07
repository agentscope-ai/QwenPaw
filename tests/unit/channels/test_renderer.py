# -*- coding: utf-8 -*-
"""
MessageRenderer unit tests.

These tests cover attachment rendering edge cases that directly affect
channel compatibility and user-visible output.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from qwenpaw.app.channels.renderer import MessageRenderer, RenderStyle


def test_audio_tool_output_preserves_media_type() -> None:
    """Base64 audio blocks should keep their declared media type."""
    from agentscope_runtime.engine.schemas.agent_schemas import (
        AudioContent,
        ContentType,
        MessageType,
    )

    renderer = MessageRenderer(
        RenderStyle(
            show_tool_details=False,
            internal_tools=frozenset(),
        ),
    )
    message = SimpleNamespace(
        type=MessageType.MCP_TOOL_CALL_OUTPUT,
        content=[
            SimpleNamespace(
                type=ContentType.DATA,
                data={
                    "name": "voice_tool",
                    "output": json.dumps(
                        [
                            {
                                "type": "audio",
                                "source": {
                                    "type": "base64",
                                    "data": "QUJD",
                                    "media_type": "audio/wav",
                                },
                            },
                        ],
                    ),
                },
            ),
        ],
    )

    parts = renderer.message_to_parts(message)

    assert len(parts) == 1
    assert isinstance(parts[0], AudioContent)
    assert parts[0].data.startswith("data:audio/wav;base64,")
    assert parts[0].format == "audio/wav"


def test_tool_output_keeps_text_and_media_when_details_hidden() -> None:
    """Tool output should keep visible text and attachments without labels."""
    from agentscope_runtime.engine.schemas.agent_schemas import (
        AudioContent,
        ContentType,
        TextContent,
        MessageType,
    )

    renderer = MessageRenderer(
        RenderStyle(
            show_tool_details=False,
            internal_tools=frozenset(),
        ),
    )
    message = SimpleNamespace(
        type=MessageType.MCP_TOOL_CALL_OUTPUT,
        content=[
            SimpleNamespace(
                type=ContentType.DATA,
                data={
                    "name": "mixed_tool",
                    "output": json.dumps(
                        [
                            {"type": "text", "text": "Caption"},
                            {
                                "type": "audio",
                                "source": {
                                    "type": "base64",
                                    "data": "QUJD",
                                    "media_type": "audio/mpeg",
                                },
                            },
                        ],
                    ),
                },
            ),
        ],
    )

    parts = renderer.message_to_parts(message)

    assert len(parts) == 2
    assert isinstance(parts[0], TextContent)
    assert parts[0].text == "Caption"
    assert isinstance(parts[1], AudioContent)
    assert parts[1].format == "audio/mpeg"
