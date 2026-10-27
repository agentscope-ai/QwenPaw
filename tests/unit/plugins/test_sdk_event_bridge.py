# -*- coding: utf-8 -*-
"""Lossless immutable runtime event snapshots; no renderer-specific
truncation.
"""

from copy import deepcopy

import pytest


def test_runtime_snapshot_preserves_multimodal_tools_and_unknown_fields():
    from qwenpaw.plugins._events import chat_event

    original = {
        "object": "response",
        "id": "run-1",
        "status": "completed",
        "output": [
            {
                "id": "message-1",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [
                    {
                        "type": "reasoning",
                        "text": "reason",
                        "provider_signature": "signature",
                    },
                    {
                        "type": "tool_call",
                        "id": "call-1",
                        "name": "tool",
                        "arguments": {"x": [1, 2]},
                    },
                    {
                        "type": "image",
                        "data": {
                            "url": "https://example.test/image.png",
                            "mime_type": "image/png",
                        },
                    },
                    {"type": "refusal", "text": "declined", "reason": "test"},
                ],
                "metadata": {"nested": {"values": [1, 2]}},
                "provider_field": "retained",
            },
        ],
        "usage": {"input_tokens": 5, "output_tokens": 3},
    }
    before = deepcopy(original)
    event = chat_event(original)
    assert original == before
    message = event.output[0]
    assert [item.type for item in message.content] == [
        "reasoning",
        "tool_call",
        "image",
        "refusal",
    ]
    assert message.content[0].attributes["provider_signature"] == "signature"
    assert message.content[1].attributes["arguments"]["x"] == (1, 2)
    assert message.content[2].data["url"] == "https://example.test/image.png"
    assert message.content[3].attributes["reason"] == "test"
    assert message.attributes["provider_field"] == "retained"
    assert event.attributes["usage"]["input_tokens"] == 5
    with pytest.raises(TypeError):
        message.metadata["nested"]["values"] = ()
    original["output"][0]["content"][1]["arguments"]["x"].append(3)
    assert message.content[1].attributes["arguments"]["x"] == (1, 2)
